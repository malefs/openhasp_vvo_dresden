import requests
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from datetime import datetime, timezone
import time
import argparse

# --- PARAMETER-STEUERUNG ---
parser = argparse.ArgumentParser(description='VVO Abfahrtsmonitor für openHASP (480px) - 5 Zeilen')
parser.add_argument('station', type=str, help='Name der Haltestelle https://www.vvo-mobil.de/#/timetables/results')   
parser.add_argument('-b', '--host', type=str, default="127.0.0.1", help='MQTT Broker IP')
parser.add_argument('--gleis', type=str, default=None, help='Optionale Gleisnummer')
parser.add_argument('--filter', nargs='+', help='Filter: tram bus s zug')
parser.add_argument('--page', type=int, default=1, help='Display-Seite (p1, p2, etc.)')
args = parser.parse_args()

MQTT_BROKER = args.host
MQTT_TOPIC_BASE = f"hasp/plate/command/p{args.page}b"

COLOR_URGENT = "#FF0000"
COLOR_NORMAL = "#7F8C8D"


# Jetzt wird bei "--filter zug" sowohl Regionalzug als auch Fernzug (Train) gefunden
MOT_FILTER_MAP = {
    "tram": "Tram", 
    "bus": "CityBus", 
    "s": "SuburbanRailway", 
    "zug": ["RegionalTrain", "Train", "RegionalBus"] 
}

ICON_MAP = {
    "Tram": "L:/ico-tram.png", 
    "CityBus": "L:/ico-bus.png", 
    "RegionalBus": "L:/ico-bus.png",
    "SuburbanRailway": "L:/ico-metropolitan-railway.png", 
    "RegionalTrain": "L:/ico-train.png", 
    "Train": "L:/ico-train.png", # Wichtig für IC/RE
    "Default": "L:/ico-tram.png"
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
        
        stopid, _, _, actual_name = points[0].split("|")[0:4]

        # 2. Abfahrtsdaten abrufen
        payload = {
            "stopid": stopid, 
            "time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "isarrival": False, 
            "limit": 50, 
            "mot": ["Tram", "CityBus", "SuburbanRailway", "RegionalTrain", "RegionalBus", "Train"]
        }
        res = requests.post("https://webapi.vvo-online.de/dm?format=json", json=payload, timeout=10)
        data = res.json()
        
        now = datetime.now(timezone.utc)
        departures = []
        
        # 3. Filter-Vorbereitung (Unterstützt Listen für "zug")
        active_mots = []
        if mot_filter:
            for m in mot_filter:
                mapped = MOT_FILTER_MAP.get(m.lower())
                if isinstance(mapped, list):
                    active_mots.extend(mapped)
                elif mapped:
                    active_mots.append(mapped)

        for dep in data.get("Departures", []):
            platform = dep.get("Platform", {}).get("Name", "")
            mot_type = dep.get("Mot", "Default")
            
            # Filter: Gleis
            if platform_filter and platform != platform_filter: continue
            
            # Filter: Verkehrsmittel (Prüft ob mot_type in der Liste der erlaubten Typen ist)
            if active_mots and mot_type not in active_mots: continue
            
            # Zeit-Parsing
            sch_dt = parse_vvo_date(dep.get("ScheduledTime"))
            rt_str = dep.get("RealTime")
            real_dt = parse_vvo_date(rt_str) if rt_str else sch_dt
            
            if not real_dt or not sch_dt: continue

            # --- ZEITBERECHNUNG MIT KAUFMÄNNISCHER RUNDUNG ---
            diff_sec = (real_dt - now).total_seconds()
            # Wir addieren 30 Sek vor der Division durch 60, um korrekt zu runden
            diff_min = int((diff_sec + 30) / 60)
            
            # Stern-Logik: Vergleich Realzeit mit Fahrplanzeit (> 30 Sek Abweichung)
            has_offset = abs((real_dt - sch_dt).total_seconds()) > 30 
            
            if diff_sec < 45: # Puffer für "jetzt" Anzeige
                time_label = "jetzt"
            else:
                time_label = f"{diff_min} min"
            
            if has_offset:
                time_label += "*"
            
            # Ziel-Text Formatierung
            destination = dep.get('Direction', '')
            if not platform_filter and platform:
                # Unterscheidung Gleis (Bahn) vs. Steig (Bus/Tram)
                label = "Gl." if mot_type in ["Train", "RegionalTrain", "SuburbanRailway"] else "St."
                destination = f"{label}{platform} {destination}"

            departures.append({
                "time": time_label,
                "line": dep.get("LineName", ""),
                "direction": destination,
                "icon": ICON_MAP.get(mot_type, ICON_MAP["Default"]),
                "is_urgent": diff_min <= 2
            })
            
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
        
        display_name = f"{station_full_name} Gl.{args.gleis}" if args.gleis else station_full_name

        print(f"\n[{now_dt.strftime('%H:%M:%S')}] --- P{args.page}: {display_name} (Broker: {MQTT_BROKER}) ---")
        
        client.publish(f"{MQTT_TOPIC_BASE}1.text", f"\uE70E {display_name}")
        client.publish(f"{MQTT_TOPIC_BASE}99.text", f"update: {now_dt.strftime('%H:%M')}")

        for i in range(5):
            base_id = 11 + (i * 10)
            if i < len(deps):
                d = deps[i]
                print(f"{d['time']:<10} | {d['line']:<3} | {d['direction']}")
                for off in [0, 1, 2, 3]: client.publish(f"{MQTT_TOPIC_BASE}{base_id+off}.hidden", 0)
                client.publish(f"{MQTT_TOPIC_BASE}{base_id}.text", d['time'])
                client.publish(f"{MQTT_TOPIC_BASE}{base_id}.text_color", COLOR_URGENT if d['is_urgent'] else COLOR_NORMAL)
                client.publish(f"{MQTT_TOPIC_BASE}{base_id+1}.src", d['icon'])
                client.publish(f"{MQTT_TOPIC_BASE}{base_id+2}.text", d['line'])
                client.publish(f"{MQTT_TOPIC_BASE}{base_id+3}.text", d['direction'][:22])
            else:
                for off in [0, 1, 2, 3]: client.publish(f"{MQTT_TOPIC_BASE}{base_id+off}.hidden", 1)
        
        time.sleep(30)

if __name__ == "__main__":
    run()



