import json
import time
import os
import argparse
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import paho.mqtt.client as mqtt

# Import der VVO Logik
from vvo_logic import get_vvo_departures

config = {}
globals_cfg = {}
FORCE_UPDATE = False

def load_config(file_path):
    global config, globals_cfg
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            globals_cfg = config['global_settings']
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Config geladen: {file_path}")
        return True
    except Exception as e:
        print(f"Fehler beim Laden der Config: {e}")
        return False

class ConfigChangeHandler(FileSystemEventHandler):
    def __init__(self, client, file_path):
        self.client = client
        self.file_path = os.path.abspath(file_path)
        self.last_modified = 0

    def on_modified(self, event):
        # Absoluter Pfadvergleich, um sicherzugehen
        if os.path.abspath(event.src_path) == self.file_path:
            # Entprellen (Debounce), da manche Editoren 2x speichern
            if time.time() - self.last_modified > 2:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ÄNDERUNG ERKANNT: {self.file_path}")
                if load_config(self.file_path):
                    #init_displays(self.client)
                    global FORCE_UPDATE
                    FORCE_UPDATE = True
                self.last_modified = time.time()

def safe_publish(client, topic, payload):
    client.publish(topic, payload)
    # Dein Wunsch-Delay gegen Overflow
    time.sleep(globals_cfg.get('mqtt_delay_sec', 0.1))

def init_displays(client):
    print("Sende Layout-Initialisierung...")
    prefix = globals_cfg['mqtt_topic_prefix']
    cols = globals_cfg['columns_x']
    for page in config['pages']:
        topic_base = f"{prefix}p{page['id']}b"
        for i in range(page['line_count']):
            bid = 11 + (i * 10)
            safe_publish(client, f"{topic_base}{bid}.x", cols['time'])
            safe_publish(client, f"{topic_base}{bid+1}.x", cols['icon'])
            safe_publish(client, f"{topic_base}{bid+2}.x", cols['line'])
            safe_publish(client, f"{topic_base}{bid+3}.x", cols['dest'])
            safe_publish(client, f"{topic_base}{bid+3}.w", 210)

def update_page(client, page_cfg):
    prefix = globals_cfg['mqtt_topic_prefix']
    topic_base = f"{prefix}p{page_cfg['id']}b"
    
    deps, station_name = get_vvo_departures(
        page_cfg['vvo_id_or_name'], 
        page_cfg['platform'], 
        page_cfg['mot_filter']
    )
    
    now_dt = datetime.now()
    display_title = f"{station_name} Gl.{page_cfg['platform']}" if page_cfg['platform'] else station_name
    
    # Konsolenausgabe
    print(f"\n[{now_dt.strftime('%H:%M:%S')}] --- {display_title} ---")
    print(f"{'Zeit':<10} | {'Linie':<5} | {'Ziel'}")
    print("-" * 50)

    safe_publish(client, f"{topic_base}1.text", f"\uE70E {display_title}")
    safe_publish(client, f"{topic_base}99.text", f"Update: {now_dt.strftime('%H:%M')}")

    for i in range(page_cfg['line_count']):
        bid = 11 + (i * 10)
        if i < len(deps):
            d = deps[i]
            color = globals_cfg['colors']['delay'] if d['is_delayed'] else \
                   (globals_cfg['colors']['urgent'] if d['is_urgent'] else globals_cfg['colors']['normal'])
            
            for off in [0, 1, 2, 3]: safe_publish(client, f"{topic_base}{bid+off}.hidden", 0)
            
            safe_publish(client, f"{topic_base}{bid}.text", d['time'])
            safe_publish(client, f"{topic_base}{bid}.text_color", color)
            safe_publish(client, f"{topic_base}{bid+1}.src", d['icon'])
            safe_publish(client, f"{topic_base}{bid+2}.text", d['line'])
            
            dest = d['direction']
            max_c = globals_cfg.get('max_chars_before_scroll', 15)
            mode = globals_cfg['scroll_type'] if len(dest) > max_c else globals_cfg['default_type']
            final_dest = dest + "  +++  " if mode == "loop" else dest
            
            safe_publish(client, f"{topic_base}{bid+3}.mode", mode)
            safe_publish(client, f"{topic_base}{bid+3}.text", final_dest)
            
            print(f"{d['time']:<10} | {d['line']:<5} | {dest}")
        else:
            for off in [0, 1, 2, 3]: safe_publish(client, f"{topic_base}{bid+off}.hidden", 1)

def main():
    global FORCE_UPDATE
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    parser.add_argument('-b', '--broker', default='127.0.0.1')
    parser.add_argument('-u', '--user')
    parser.add_argument('-P', '--password')
    args = parser.parse_args()

    # Pfad absolut machen für watchdog
    config_abs_path = os.path.abspath(args.config)
    config_dir = os.path.dirname(config_abs_path)

    if not load_config(config_abs_path): return

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    if args.user and args.password:
        client.username_pw_set(args.user, args.password)
    
    print(f"Verbinde zu MQTT Broker: {args.broker}")
    client.connect(args.broker, 1883, 60)
    client.loop_start()
    
    init_displays(client)

    # Watchdog Setup
    observer = Observer()
    handler = ConfigChangeHandler(client, config_abs_path)
    # Wir beobachten den Ordner der Datei
    observer.schedule(handler, path=config_dir or '.', recursive=False)
    observer.start()

    print(f"Monitoring läuft für: {config_abs_path}")

    try:
        while True:
            for page in config['pages']:
                update_page(client, page)
                # Kleiner Sleep zwischen den Seiten (falls mehrere)
                time.sleep(1)
            
            wait_time = globals_cfg.get('update_interval_sec', 30)
            FORCE_UPDATE = False
            # Warte-Loop der durch FORCE_UPDATE unterbrochen werden kann
            for _ in range(wait_time * 10):
                if FORCE_UPDATE: break
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nBeende...")
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()

