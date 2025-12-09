from umqtt.simple import MQTTClient
from machine import Pin
import time
import network
import socket
import mqtt_config # Credentials for HiveMQ
import config      # Credentials for Firebase
import sys
import ssl
import ujson
import _thread     # For Multithreading
import gc          # For Memory Management

# Import custom libraries
from thermistor import Thermistor
from firebasedb_process import FirebaseDB

# --- WI-FI INFO ---
ssid = mqtt_config.ssid
password = mqtt_config.pwd

# --- HARDWARE SETUP ---
temp_sensor = Thermistor(pin=26)

blue_led = Pin(14, Pin.OUT)    
red_led = Pin(15, Pin.OUT)     
buzzer = Pin(13, Pin.OUT)      
mute_button = Pin(10, Pin.IN, Pin.PULL_UP) 
green_led = Pin(9, Pin.OUT)    

# --- SHARED SETTINGS ---
READ_INTERVAL = 2.0           
IDEAL_TEMP_MIN = 21.0
IDEAL_TEMP_MAX = 27.0
SETTINGS_INTERVAL = 5.0       
system_running = True         
wifi_connected_flag = False   

WIFI_ATTEMPT = 5
WIFI_CONNECTED_CODE = 3
MQTT_TOPIC = b'sensor_data/temp'

# --- STATE VARIABLES ---
is_muted = False
last_button_press = 0

# --- INTERRUPT HANDLER (BUTTON) ---
def button_handler(pin):
    global is_muted, last_button_press
    current_time = time.ticks_ms()
    if time.ticks_diff(current_time, last_button_press) > 300:
        is_muted = not is_muted
        # print(f"Mute: {is_muted}") 
        last_button_press = current_time

mute_button.irq(trigger=Pin.IRQ_FALLING, handler=button_handler)

# -----------------------------------------------------------------
# CORE 1: SETTINGS MANAGER (Control Plane)
# -----------------------------------------------------------------
def core1_settings_task():
    global READ_INTERVAL, IDEAL_TEMP_MIN, IDEAL_TEMP_MAX, system_running
    
    print("[Core 1] Settings Thread Started! Waiting for Wi-Fi...")
    
    while not wifi_connected_flag:
        time.sleep(1)
        
    print("[Core 1] Wi-Fi detected. Connecting to Firebase...")
    
    try:
        settings_db = FirebaseDB(url=config.firebase_url, tablename=config.table_name)
    except Exception as e:
        print(f"[Core 1] DB Init Error: {e}")
        return

    while system_running:
        try:
            gc.collect()
            new_settings = settings_db.get_settings() 
            
            if new_settings:
                # Update Interval
                new_interval = float(new_settings.get('read_interval', READ_INTERVAL))
                if new_interval != READ_INTERVAL:
                    print(f"[Core 1] >>> UPDATE! Interval changed: {READ_INTERVAL}s -> {new_interval}s")
                    READ_INTERVAL = new_interval
                
                # Update Thresholds
                IDEAL_TEMP_MIN = float(new_settings.get('min_temp', IDEAL_TEMP_MIN))
                IDEAL_TEMP_MAX = float(new_settings.get('max_temp', IDEAL_TEMP_MAX))
                    
        except Exception as e:
            print(f"[Core 1] Error: {e}")
            
        time.sleep(SETTINGS_INTERVAL)

# -----------------------------------------------------------------
# MAIN CORE (CORE 0): SENSOR & MQTT PUBLISHER
# -----------------------------------------------------------------

# --- WIFI CONNECTION SETUP ---
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wifi_connected = False

for attempt in range(0, WIFI_ATTEMPT):
    print(f"Attempt {attempt + 1}/{WIFI_ATTEMPT}...")
    wlan.connect(ssid, password)
    time.sleep(3) 
    
    if wlan.status() == WIFI_CONNECTED_CODE:
        wifi_connected = True
        break

if wifi_connected:
    print("Connected to Wi-Fi!")
    green_led.value(1); time.sleep(2); green_led.value(0)
    
    # Start Core 1
    wifi_connected_flag = True
    _thread.stack_size(8 * 1024)
    _thread.start_new_thread(core1_settings_task, ())
    
else:
    print("Connection Failed."); sys.exit()

# --- MQTT SETUP ---
print("Connecting to MQTT Broker...")

try:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT) 
    context.verify_mode = ssl.CERT_NONE 
except AttributeError:
    context = None

try:
    client = MQTTClient(
        client_id=b'sensor_data_fast', 
        server=mqtt_config.MQTT_BROKER, 
        port=mqtt_config.MQTT_PORT,
        user=mqtt_config.MQTT_USER, 
        password=mqtt_config.MQTT_PWD, 
        ssl=context 
    )
    client.connect()
    print("Connected to MQTT Broker!")
except Exception as e:
    print(f"Failed to connect to MQTT: {e}")
    sys.exit()

# --- MAIN LOOP ---
message_id = 0
last_upload_time = 0

# Variables for non-blocking buzzer
last_beep_time = 0
buzzer_state = 0
BEEP_SPEED = 500 # ms

print("System Fully Operational...")

try:
    while True:
        current_time = time.ticks_ms()
        
        # 1. READ SENSOR (Real-time)
        raw_temp = temp_sensor.read_temp()
        
        # 2. ALARM LOGIC (Runs every cycle ~10ms)
        # This ensures LEDs and Buzzer respond instantly, regardless of upload speed
        if raw_temp < IDEAL_TEMP_MIN:
            # Cold
            blue_led.value(1); red_led.value(0); buzzer.value(0)
            
        elif raw_temp > IDEAL_TEMP_MAX:
            # Hot
            blue_led.value(0); red_led.value(1)
            
            if not is_muted:
                # Non-blocking Rhythmic Beep
                if time.ticks_diff(current_time, last_beep_time) > BEEP_SPEED:
                    buzzer_state = not buzzer_state # Toggle
                    buzzer.value(buzzer_state)
                    last_beep_time = current_time
            else:
                buzzer.value(0)
        else:
            # Normal
            blue_led.value(0); red_led.value(0); buzzer.value(0)
            # Optional: Reset mute when back to normal
            if is_muted: is_muted = False


        # 3. UPLOAD LOGIC (Runs on Interval)
        if time.ticks_diff(current_time, last_upload_time) > (READ_INTERVAL * 1000):
            
            message_id += 1
            
            # Prepare Payload
            status_msg = "ACTIVE" if (raw_temp > IDEAL_TEMP_MAX or raw_temp < IDEAL_TEMP_MIN) else "INACTIVE"
            
            payload = ujson.dumps({
                "temperature": raw_temp,
                "msg_id": message_id,
                "timestamp": current_time,
                "interval": READ_INTERVAL
            })
            
            print(f"#{message_id} | {raw_temp}°C | Int: {READ_INTERVAL}s")
            
            # Measure Latency
            t_start = time.ticks_ms()
            client.publish(MQTT_TOPIC, payload)
            t_end = time.ticks_ms()
            
            print(f">> Latency: {time.ticks_diff(t_end, t_start)} ms")
            
            last_upload_time = current_time
        
        # Minimal sleep to keep loop stable but fast
        time.sleep(0.01)

except KeyboardInterrupt:
    print("\nDisconnecting...")
    system_running = False 
    client.disconnect()
    blue_led.value(0); red_led.value(0); buzzer.value(0)
    print("System Stopped.")