
Install MQTT Broker

setup openhasp 

	https://nightly.openhasp.com/
	install

minicom to display and set WIFI:
	
	ssid myAccessPointName 
	pass myWifiPassword 
	reboot
	
getting display IP
copy openhasp_data to display with Webinterface 

install uv (falls noch nicht geschehen) 
```bash

   curl -LsSf https://astral.sh/uv/install.sh | sh
	 #source $HOME/.cargo/env	
   
	 # uv init 
	 # uv add requests paho-mqtt
   
	 uv sync
        
     ENV_FILE=willi.env docker compose --env-file willi.env up -d
```
  
<p align="center">
  <img src="openhasp_data/screen_page1.png" alt="Seite 1" width="250" style="display: inline-block; margin: 0 10px;">
  <img src="openhasp_data/screen_page2.png" alt="Seite 2" width="250" style="display: inline-block; margin: 0 10px;">
  <img src="openhasp_data/screen_page3.png" alt="Seite 3" width="250" style="display: inline-block; margin: 0 10px;">
</p>


