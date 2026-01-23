import requests
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from datetime import datetime, timezone
import time
import argparse
import re 

# --- PARAMETER-STEUERUNG ---
parser = argparse.ArgumentParser(description='VVO Abfahrtsmonitor für openHASP (480px) - 5 Zeilen')
parser.add_argument('station', type=str, help='Name der Haltestelle https://www.vvo-mobil.de/#/timetables/results')   
parser.add_argument('-d', '--device', type=str, default="plate", help='Name des Displays (Node Name in openHASP)')
parser.add_argument('-b', '--host', type=str, default="127.0.0.1", help='MQTT Broker IP')
parser.add_argument('-u', '--user', type=str, help='MQTT Username')
parser.add_argument('-P', '--password', type=str, help='MQTT Passwort')
parser.add_argument('--gleis', type=str, default=None, help='Optionale Gleisnummer')
parser.add_argument('--filter', nargs='+', help='Filter: tram bus s zug')
parser.add_argument('--page', type=int, default=1, help='Display-Seite (p1, p2, etc.)')
args = parser.parse_args()

MQTT_BROKER = args.host
MQTT_TOPIC_BASE = f"hasp/{args.device}/command/p{args.page}b"

COLOR_URGENT = "#FF0000"
COLOR_NORMAL = "#7F8C8D"


# --- MOT-FILTER ---
# Hier definierst du, welche API-Begriffe zu welcher Gruppe gehören
MOT_FILTER_MAP = {
    "tram": "Tram", 
    "bus": ["CityBus", "RegionalBus", "Bus", "SchoolBus", "BusOnRequest", "IntercityBus", "ClockBus","PlusBus"], 
    "s": "SuburbanRailway", 
    "zug": ["RegionalTrain", "Train"],
    "faehre": "Ferry"
}

# --- ICON-MAP ---
# Hier verknüpfst du die Gruppen/Mots mit deinen Dateien auf dem Display
ICON_MAP = {
    "Tram": "L:/ico-tram.png",
    "CityBus": "L:/ico-bus.png",
    "RegionalBus": "L:/ico-bus.png",
    "SchoolBus": "L:/school-bus.png",
    "ClockBus": "L:/clock-bus.png",
    "PlusBus": "L:/ico-plus-bus.png",
    "IntercityBus": "L:/ico-bus.png", # SEV bleibt Bus-Icon
    "BusOnRequest": "L:/busOnRequest.png",  # Dein Rufbus-Icon
    "Ferry": "L:/ferry-colored.png",        # Dein Fähren-Icon
    "SuburbanRailway": "L:/ico-metropolitan-railway.png",
    "RegionalTrain": "L:/ico-train.png",
    "Train": "L:/ico-train.png",
    "Default": "L:/ico-train.png"
}


def get_clean_display_name(stadt, halt):
    """Baut aus Stadt und Haltestelle einen sauberen Namen für das Display."""
    # 1. Stadt säubern für den Vergleich (z.B. "Plauen (Vogtl)" -> "plauen")
    stadt_simple = re.sub(r'\(.*?\)', '', stadt).strip().lower()
    
    # 2. Prüfen: Ist die Stadt bereits im Haltestellennamen enthalten?
    if stadt_simple in halt.lower():
        # Fall Jocketa: "Jocketa" ist in "Jocketa, Bahnhof" -> nimm nur den Halt
        name = halt
    else:
        # Fall Plauen: "Plauen" fehlt in "oberer Bahnhof" -> kombiniere beides
        name = f"{stadt} {halt}"

    # 3. Abkürzungen anwenden
    replacements = {
        r"\boberer Bahnhof\b": "Ob. Bf.",
        r"\bunterer Bahnhof\b": "Unt. Bf.",
        r"\bHauptbahnhof\b": "Hbf.",
        r"\bBahnhof\b": "Bf.",
        r",": "",  # Entfernt Komma bei "Jocketa, Bahnhof"
    }
    
    for pattern, replacement in replacements.items():
        name = re.sub(pattern, replacement, name, flags=re.IGNORECASE)
    
    # 4. Doppelte Leerzeichen entfernen und trimmen
    return re.sub(r'\s+', ' ', name).strip()


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

        if not points: 
            return [], "Unbekannt"

        # Den String zerlegen (VVO Format: ID|Typ|Stadt|Halt|...)
        parts = points[0].split("|")
        stopid = parts[0]

    	# --- HIER DIE FUNKTION AUFRUFEN ---
        actual_name = get_clean_display_name(parts[2], parts[3])


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

        #print(data)        
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
            print(dep)
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

    # Login nur setzen, wenn User und Passwort angegeben wurden
    if args.user and args.password:
        client.username_pw_set(args.user, args.password)

    client.connect(MQTT_BROKER, 1883, 60)
    client.loop_start()

    while True:
        deps, station_full_name = get_vvo_departures(args.station, args.gleis, args.filter)
        now_dt = datetime.now()
        print(station_full_name)

        # Falls ein Gleis gefiltert wird, hängen wir es an den sauberen Namen an
        display_name = f"{clean_name} Gl.{args.gleis}" if args.gleis else station_full_name

        print(f"\n[{now_dt.strftime('%H:%M:%S')}] --- P{args.page}: {display_name} (Broker: {MQTT_BROKER}) ---")
        
        # Senden an das Display (Icon \uE70E ist das Bahnhof-Symbol)
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



