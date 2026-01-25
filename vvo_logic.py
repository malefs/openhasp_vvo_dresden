import requests
import re
from datetime import datetime, timezone
from pyproj import Transformer

# --- MOT-FILTER-MAP ---
MOT_FILTER_MAP = {
    "tram": "Tram", 
    "bus": ["CityBus", "RegionalBus", "Bus", "SchoolBus", "BusOnRequest", "IntercityBus", "ClockBus","PlusBus"], 
    "s": "SuburbanRailway", 
    "u":"Subway",
    "zug": ["RegionalTrain", "Train"],
    "faehre": "Ferry"
}

# --- ICON-MAP ---
# Korrektur: Pfade ohne Slash nach dem Doppelpunkt für openHASP
ICON_MAP = {
    "Tram": "L:ico-tram.png",
    "CityBus": "L:ico-bus.png",
    "RegionalBus": "L:ico-bus.png",
    "SchoolBus": "L:school-bus.png",
    "ClockBus": "L:clock-bus.png",
    "PlusBus": "L:ico-plus-bus.png",
    "IntercityBus": "L:ico-bus.png",
    "BusOnRequest": "L:busOnRequest.png",
    "Ferry": "L:ferry-colored.png",
    "SuburbanRailway": "L:ico-metropolitan-railway.png",
    "Subway": "L:U-Bahn_Berlin_logo.png",    
    "RegionalTrain": "L:ico-train.png",
    "Train": "L:ico-train.png",
    "Default": "L:ico-train.png"
}


# Wir nutzen \u + deinen Hex-Code
WEATHER_ICONS = {
    "sunny": "\uE599",
    "partly_cloudy": "\uE595",
    "cloudy": "\uE590",
    "fog": "\uE591",
    "rainy": "\uE597",
    "pouring": "\uE596",
    "snowy": "\uE598",
    "lightning": "\uE593",
    "lightning_rain": "\uE67E",
    "snowy_rainy": "\uE67F",
    "hail": "\uE592",
    "windy": "\uE59D"
}


# Mapping von Open-Meteo WMO Codes zu deinen Icons
WMO_TO_ICON = {
    0: WEATHER_ICONS["sunny"],
    1: WEATHER_ICONS["partly_cloudy"],
    2: WEATHER_ICONS["partly_cloudy"],
    3: WEATHER_ICONS["cloudy"],
    45: WEATHER_ICONS["fog"], 48: WEATHER_ICONS["fog"],
    51: WEATHER_ICONS["rainy"], 53: WEATHER_ICONS["rainy"], 55: WEATHER_ICONS["rainy"],
    61: WEATHER_ICONS["rainy"], 63: WEATHER_ICONS["rainy"], 65: WEATHER_ICONS["pouring"],
    71: WEATHER_ICONS["snowy"], 73: WEATHER_ICONS["snowy"], 75: WEATHER_ICONS["snowy"],
    77: WEATHER_ICONS["snowy"],
    80: WEATHER_ICONS["rainy"], 81: WEATHER_ICONS["rainy"], 82: WEATHER_ICONS["pouring"],
    85: WEATHER_ICONS["snowy"], 86: WEATHER_ICONS["snowy"],
    95: WEATHER_ICONS["lightning"], 96: WEATHER_ICONS["lightning_rain"], 99: WEATHER_ICONS["lightning_rain"]
}

# --- MATHEMATISCHE UMRECHNUNG (GK4 zu WGS84) ---

def gk4_to_wgs84(rechts, hoch):
    """
    Konvertiert Gauß-Krüger Zone 4 (VVO Standard) in WGS84 (Lat/Lon).
    Basierend auf der Transformation für den Raum Deutschland/Sachsen.
    """
    try:
        gk4 = 'epsg:31468'
        wgs84 = 'epsg:4326'

        # Initialize transformer
        transformer = Transformer.from_crs(gk4, wgs84, always_xy=True)
        # Korrektur-Offset für das Potsdam-Datum (DHDN zu WGS84) in Sachsen
        # Diese Offsets verhindern eine Abweichung von ca. 100-200m
        lon, lat = transformer.transform(rechts,hoch)
        return lat, lon 
    except Exception as e:
        print(f"Umrechnungsfehler: {e}")
        return 51.0504, 13.7373 # Fallback Dresden Mitte

# --- WETTER FUNKTION ---

def get_weather(lat, lon):
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            'latitude': lat,
            'longitude': lon,
            'current': ['temperature_2m', 'weather_code'],
            'daily': ['temperature_2m_max', 'temperature_2m_min', 'weather_code'],
            'timezone': 'auto'
        }
        res = requests.get(url, params=params, timeout=5)
        d = res.json()
        
        # Aktuelle Werte
        curr_temp = d['current']['temperature_2m']
        current_code = d['current']['weather_code']
        
        # Tages-Werte (Index 0 ist heute)
        daily_code = d['daily']['weather_code'][0]
        t_max = d['daily']['temperature_2m_max'][0]
        t_min = d['daily']['temperature_2m_min'][0]
        
        # Icons zuordnen
        current_icon = WMO_TO_ICON.get(current_code, WEATHER_ICONS["cloudy"])
        daily_icon =WMO_TO_ICON.get(daily_code, WEATHER_ICONS["cloudy"])
        
        return {
            "temp": f"{curr_temp:.1f}°C",
            "temp_min_max": f"{t_min:.0f}/{t_max:.0f}",
            "icon_now": current_icon,
            "icon_daily": daily_icon,
            "code_now": current_code,
            "code_daily": daily_code
        }
    except Exception as e:
        print(f"Wetter-Fehler: {e}")
        return None
    

def get_clean_display_name(stadt, halt):
    """Baut aus Stadt und Haltestelle einen sauberen Namen für das Display."""
    stadt_simple = re.sub(r'\(.*?\)', '', stadt).strip().lower()
    if stadt_simple in halt.lower():
        name = halt
    else:
        name = f"{stadt} {halt}"

    replacements = {
        r"\boberer Bahnhof\b": "Ob. Bf.",
        r"\bunterer Bahnhof\b": "Unt. Bf.",
        r"\bHauptbahnhof\b": "Hbf.",
        r"\bBahnhof\b": "Bf.",
        r",": "",
    }
    for pattern, replacement in replacements.items():
        name = re.sub(pattern, replacement, name, flags=re.IGNORECASE)
    
    return re.sub(r'\s+', ' ', name).strip()

def parse_vvo_date(vvo_date):
    if not vvo_date: return None
    try:
        millis = int(vvo_date.split("(")[1].split(")")[0].split("+")[0].split("-")[0])
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
    except: return None

def get_vvo_departures(station_name, platform_filter, mot_filter):
    try:
        # 1. Pointfinder (Suche Station und Koordinaten)
        r = requests.post("https://webapi.vvo-online.de/tr/pointfinder?format=json", 
                         json={"query": station_name, "stopsOnly": True, "limit": 1}, timeout=10)
        points = r.json().get("Points", [])
        if not points:
            return [], "Unbekannt", ""

        # Point-String zerlegen: "ID|Typ|Stadt|Name|Rechtswert|Hochwert"
        parts = points[0].split("|")
        stopid = parts[0]
        actual_name = get_clean_display_name(parts[2], parts[3])
        
        # Wetterdaten über Koordinaten beziehen
        weather = {}
        try:
            # VVO liefert Koordinaten an Position 4 und 5
            rechts = int(parts[5])
            hoch = int(parts[4])
            print(rechts,hoch)
            
            if rechts > 0 and hoch > 0:
                # Umrechnung GK4 -> WGS84
                lat, lon = gk4_to_wgs84(rechts, hoch)
                print("Koordinaten:",lat,lon)
                # Wetter abrufen
                weather = get_weather(lat, lon)
        except (IndexError, ValueError):
            print("Keine Koordinaten für Wetter gefunden.")

        # 2. Abfahrten laden
        payload = {
            "stopid": stopid, 
            "time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "isarrival": False, 
            "limit": 50, 
            "mot": ["Tram", "CityBus", "SuburbanRailway", "RegionalTrain", "RegionalBus", 
                    "Train", "BusOnRequest", "PlusBus", "ClockBus", "Ferry", "SchoolBus"]
        }
        res = requests.post("https://webapi.vvo-online.de/dm?format=json", json=payload, timeout=10)
        data = res.json()
        
        now = datetime.now(timezone.utc)
        departures = []
        
        # 3. Filter-Vorbereitung
        active_mots = []
        if mot_filter:
            for m in mot_filter:
                mapped = MOT_FILTER_MAP.get(m.lower())
                if isinstance(mapped, list): active_mots.extend(mapped)
                elif mapped: active_mots.append(mapped)

        for dep in data.get("Departures", []):
            platform = dep.get("Platform", {}).get("Name", "")
            mot_type = dep.get("Mot", "Default")
            
            
            if platform_filter and str(platform) != str(platform_filter): continue
            if active_mots and mot_type not in active_mots: continue
            
            sch_dt = parse_vvo_date(dep.get("ScheduledTime"))
            rt_str = dep.get("RealTime")
            real_dt = parse_vvo_date(rt_str) if rt_str else sch_dt
            
            if not real_dt or not sch_dt: continue

            delay_sec = (real_dt - sch_dt).total_seconds()
            diff_min = int(((real_dt - now).total_seconds() + 30) / 60)
            
            time_label = "jetzt" if (real_dt - now).total_seconds() < 45 else f"{diff_min} min"
            
            line_val = dep.get("LineName", "")
            if mot_type == "BusOnRequest": line_val = f"{line_val}*"
            elif mot_type == "IntercityBus" or line_val == "SEV": line_val = "SEV"

            destination = dep.get('Direction', '')
            #print(mot_type,destination)
            if not platform_filter and platform:
                label = "Gl." if mot_type in ["Train", "RegionalTrain", "SuburbanRailway"] else "St."
                destination = f"{label}{platform} {destination}"

            departures.append({
                "time": time_label,
                "line": line_val,
                "direction": destination,
                "icon": ICON_MAP.get(mot_type, ICON_MAP["Default"]),
                "is_urgent": diff_min <= 2,
                "is_delayed": delay_sec > 45
            })
            
        return departures, actual_name,weather

    except Exception as e:
        print(f"Fehler in vvo_logic: {e}")
        return [], station_name

