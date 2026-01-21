import requests
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from datetime import datetime, timezone
import time
import argparse

# --- PARAMETER-STEUERUNG ---
parser = argparse.ArgumentParser(description='VVO Abfahrtsmonitor für openHASP (480px) - 5 Zeilen')
parser.add_argument('station', type=str, help='Name der Haltestelle')
parser.add_argument('--gleis', type=str, default=None, help='Optionale Gleisnummer')
parser.add_argument('--filter', nargs='+', help='Filter: tram bus s zug')
parser.add_argument('--page', type=int, default=1, help='Display-Seite (p1, p2, etc.)')
args = parser.parse_args()

MQTT_BROKER = ""
# Topic-Format wie gewünscht: p1b11, p1b12 etc.
MQTT_TOPIC_BASE = f"hasp/plate/command/p{args.page}b"

COLOR_URGENT = "#FF0000"
COLOR_NORMAL = "#7F8C8D"

MOT_FILTER_MAP = {"tram": "Tram", "bus": "CityBus", "s": "SuburbanRailway", "zug": "RegionalTrain"}
ICON_MAP = {
    "Tram": "L:/ico-tram.png", "CityBus": "L:/ico-bus.png", "RegionalBus": "L:/ico-bus.png",
    "SuburbanRailway": "L:/ico-metropolitan-railway.png", "RegionalTrain": "L:/ico-train.png", "Default": "L:/ico-tram.png"
}

def parse_vvo_date(vvo_date):
    if not vvo_date: return None
    try:
        millis = int(vvo_date.split("(")[1].split(")")[0].split("+")[0].split("-")[0])
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
    except: return None


def get_vvo_departures(station_name, platform_filter, mot_filter):
    try:
        # 1. Haltestellen-ID (StopID) finden
        r = requests.post("https://webapi.vvo-online.de/tr/pointfinder?format=json", 
                         json={"query": station_name, "stopsOnly": True, "limit": 1}, timeout=10)
        points = r.json().get("Points", [])
        if not points: return [], "Unbekannt"
        
        # Extrahiere StopID und den offiziellen Namen der Haltestelle
        stopid, _, _, actual_name = points[0].split("|")[0:4]

        # 2. Abfahrtsdaten abrufen
        payload = {
            "stopid": stopid, 
            "time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "isarrival": False, 
            "limit": 50, 
            "mot": ["Tram", "CityBus", "SuburbanRailway", "RegionalTrain", "RegionalBus"]
        }
        res = requests.post("https://webapi.vvo-online.de/dm?format=json", json=payload, timeout=10)
        data = res.json()
        
        now = datetime.now(timezone.utc)
        departures = []
        
        # Filter-Mapping für Verkehrsmittel
        active_mots = [MOT_FILTER_MAP[m.lower()] for m in mot_filter if m.lower() in MOT_FILTER_MAP] if mot_filter else []
        if "CityBus" in active_mots: active_mots.append("RegionalBus")

        for dep in data.get("Departures", []):
            platform = dep.get("Platform", {}).get("Name", "")
            mot_type = dep.get("Mot", "Default")
            
            # Filter: Gleis (falls in Kommandozeile angegeben)
            if platform_filter and platform != platform_filter: continue
            
            # Filter: Verkehrsmittel (falls in Kommandozeile angegeben)
            if active_mots and mot_type not in active_mots: continue
            
            # Zeit-Parsing: Geplante Zeit vs. Echtzeit
            sch_dt = parse_vvo_date(dep.get("ScheduledTime"))
            rt_str = dep.get("RealTime")
            real_dt = parse_vvo_date(rt_str) if rt_str else sch_dt
            
            if not real_dt or not sch_dt: continue

            # Berechnung der Minuten bis zur Abfahrt (Echtzeit minus Jetzt)
            #diff_sec = (real_dt - now).total_seconds()
            #diff_min = int(diff_sec / 60)
	    
            # Berechnung der Sekunden bis zur Abfahrt
            diff_sec = (real_dt - now).total_seconds()
            
            # KORREKTUR: Runden statt Abschneiden
            # Wir addieren 30 Sekunden vor der Ganzzahl-Umwandlung,
            # um ab der 30. Sekunde auf die nächste Minute zu springen.
            diff_min = int((diff_sec + 30) / 60)
            
            # Stern-Logik (unverändert)
            has_offset = abs((real_dt - sch_dt).total_seconds()) > 30 
            
            # Formatierung
            if diff_sec < 30: # Wenn weniger als 30 Sek übrig sind
                time_label = "jetzt"
            else:
                time_label = f"{diff_min} min"
            
            if has_offset:
                time_label += "*"


            
            # Stern-Logik: Prüfen, ob Echtzeit von der Fahrplanzeit abweicht
            # (Toleranz von 30 Sekunden, um Rundungsfehler zu vermeiden)
            has_offset = abs((real_dt - sch_dt).total_seconds()) > 30 
            
            # Formatierung des Zeit-Strings
            if diff_min <= 0:
                time_label = "jetzt"
            else:
                time_label = f"{diff_min} min"
            
            # Sternchen nur anhängen, wenn unpünktlich
            if has_offset:
                time_label += "*"
            
            # Ziel-Text Formatierung: Wenn kein Gleis-Filter aktiv ist, Gleis vor das Ziel schreiben
            destination = dep.get('Direction', '')
            if not platform_filter and platform:
                destination = f"Gl.{platform} {destination}"

            departures.append({
                "time": time_label,
                "line": dep.get("LineName", ""),
                "direction": destination,
                "icon": ICON_MAP.get(mot_type, ICON_MAP["Default"]),
                "is_urgent": diff_min <= 2  # Markierung für rote Farbe
            })
            
        # Rückgabe der ersten 5 Ergebnisse und des Haltestellennamens
        return departures[:5], actual_name

    except Exception as e:
        print(f"Fehler in get_vvo_departures: {e}")
        return [], station_name


def run():
    client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    client.connect(MQTT_BROKER, 1883, 60)
    client.loop_start()

    while True:
        deps, station_full_name = get_vvo_departures(args.station, args.gleis, args.filter)
        now_dt = datetime.now()
        
        # Titel-Anpassung wenn Gleis-Filter aktiv ist
        display_name = station_full_name
        if args.gleis:
            display_name = f"{station_full_name} Gl.{args.gleis}"

        print(f"\n[{now_dt.strftime('%H:%M:%S')}] --- PAGE {args.page}: {display_name} ---")

	# Aktuelle Zeit für dieses Update holen
        current_time = datetime.now().strftime('%H:%M')
        
        # Titel & Footer (ID 1 für Name, ID 99 für Zeit)
        # Wichtig: Wir senden den Namen und die Zeit explizit bei jedem Durchlauf
        client.publish(f"{MQTT_TOPIC_BASE}1.text", f"\uE70E {display_name}", retain=False)
        client.publish(f"{MQTT_TOPIC_BASE}99.text", f"update: {current_time}", retain=False)
        
        # Debug-Ausgabe in der Konsole
        print(f"MQTT Send: {MQTT_TOPIC_BASE}99.text -> update: {current_time}")

        for i in range(5):
            base_id = 11 + (i * 10)
            if i < len(deps):
                d = deps[i]
                print(f"{d['time']:<10} | {d['line']:<3} | {d['direction']}")
                
                # Zeile anzeigen
                for off in [0, 1, 2, 3]: client.publish(f"{MQTT_TOPIC_BASE}{base_id+off}.hidden", 0, retain=False)
                
                client.publish(f"{MQTT_TOPIC_BASE}{base_id}.text", d['time'], retain=False)
                client.publish(f"{MQTT_TOPIC_BASE}{base_id}.text_color", COLOR_URGENT if d['is_urgent'] else COLOR_NORMAL, retain=False)
                client.publish(f"{MQTT_TOPIC_BASE}{base_id+1}.src", d['icon'], retain=False)
                client.publish(f"{MQTT_TOPIC_BASE}{base_id+2}.text", d['line'], retain=False)
                client.publish(f"{MQTT_TOPIC_BASE}{base_id+3}.text", d['direction'][:22], retain=False)
            else:
                # Zeile verstecken
                for off in [0, 1, 2, 3]: client.publish(f"{MQTT_TOPIC_BASE}{base_id+off}.hidden", 1, retain=False)
        
        time.sleep(30)

if __name__ == "__main__":
    run()


