from machine import Pin
import time
import network
import config
import sys
import _thread

# Import custom library
from thermistor import Thermistor
from firebasedb_process import FirebaseDB

# --- CONFIGURATION ---
ssid = config.ssid
password = config.pwd

# --- HARDWARE SETUP ---
temp_sensor = Thermistor(pin=26)
blue_led = Pin(14, Pin.OUT)    # Cold Indicator
red_led = Pin(15, Pin.OUT)     # Hot Indicator
buzzer = Pin(13, Pin.OUT)      # Alarm
mute_button = Pin(10, Pin.IN, Pin.PULL_UP) 
green_led = Pin(9, Pin.OUT)    # Wi-Fi Indicator

# --- SETTINGS ---
IDEAL_TEMP_MIN = 21.0 
IDEAL_TEMP_MAX = 27.0 
READ_INTERVAL = 1.0   
SETTINGS_INTERVAL = 5.0 
HISTORY_SIZE = 5      
WIFI_ATTEMPT = 5
WIFI_CONNECTED_CODE = 3

# --- SHARED VARIABLES ---
avg_temp = 0           
is_muted = False       
system_running = True  
is_sensor_ready = False # Prevents false alarm at startup

# --- INTERRUPT HANDLER (BUTTON) ---
last_button_press = 0

def button_handler(pin):
    global is_muted, last_button_press
    current_time = time.ticks_ms()
    
    if time.ticks_diff(current_time, last_button_press) > 300:
        is_muted = not is_muted
        print(f"\n[IRQ] Mute toggled! New state: {is_muted}")
        last_button_press = current_time

mute_button.irq(trigger=Pin.IRQ_FALLING, handler=button_handler)

# -----------------------------------------------------------------
# SECOND CORE TASK: ALARM & LEDS (CORE 1)
# -----------------------------------------------------------------
def core1_alarm_task():
    global avg_temp, is_muted, IDEAL_TEMP_MIN, IDEAL_TEMP_MAX, system_running, is_sensor_ready
    
    print("[Core 1] Alarm Thread Started! Waiting for sensor...")
    
    while system_running:
        # WAIT HERE if sensor is not ready yet
        if not is_sensor_ready:
            time.sleep(0.5)
            continue # Skip the rest of the loop

        # --- NORMAL LOGIC ---
        if avg_temp < IDEAL_TEMP_MIN:
            blue_led.value(1)
            red_led.value(0)
            
            if not is_muted:
                buzzer.value(1)
                time.sleep(0.5)
                buzzer.value(0)
                time.sleep(0.5)
            else:
                buzzer.value(0)
                time.sleep(0.2) 
            
        elif avg_temp > IDEAL_TEMP_MAX:
            # HOT
            blue_led.value(0)
            red_led.value(1)
            
            if not is_muted:
                # Rhythmic Beep
                buzzer.value(1)
                time.sleep(0.5)
                buzzer.value(0)
                time.sleep(0.5)
            else:
                buzzer.value(0)
                time.sleep(0.2) 

        else:
            # IDEAL
            blue_led.value(0)
            red_led.value(0)
            buzzer.value(0)
            
        time.sleep(0.1)

# -----------------------------------------------------------------
# MAIN CORE (CORE 0): WIFI, SENSOR & DATABASE
# -----------------------------------------------------------------
print("System Starting...")

# --- WIFI CONNECTION SETUP ---
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wifi_connected = False

# Try to connect WIFI_ATTEMPT times
for attempt in range(0, WIFI_ATTEMPT):
    print(f"Attempt {attempt+1}/{WIFI_ATTEMPT}...")
    wlan.connect(ssid, password)
    time.sleep(3) 
    
    current_status = wlan.status()
    if current_status == WIFI_CONNECTED_CODE:
        wifi_connected = True
        break

# --- CHECK CONNECTION RESULT ---
if current_status == WIFI_CONNECTED_CODE:
    print("Connected to Wi-Fi!")
    green_led.value(1)
    time.sleep(2)
    green_led.value(0)
else:
    print("Connection Failed.")
    red_led.value(1)
    time.sleep(3)
    red_led.value(0)
    sys.exit() 

# Start Second Core
_thread.start_new_thread(core1_alarm_task, ())

print("System Fully Operational on Dual Cores...")
db = FirebaseDB(url=config.firebase_url, tablename=config.table_name)

last_settings_time = 0
last_read_time = 0
temp_history = []

try:
    while True:
        current_time = time.ticks_ms()
        
        # TASK A: Check Settings
        if time.ticks_diff(current_time, last_settings_time) > (SETTINGS_INTERVAL * 1000):
            new_settings = db.get_settings() 
            if new_settings:
                IDEAL_TEMP_MIN = float(new_settings.get('min_temp', IDEAL_TEMP_MIN))
                IDEAL_TEMP_MAX = float(new_settings.get('max_temp', IDEAL_TEMP_MAX))
            last_settings_time = current_time

        # TASK B: Read Sensor & Upload Data
        if time.ticks_diff(current_time, last_read_time) > (READ_INTERVAL * 1000):
            raw_temp = temp_sensor.read_temp()
            
            if len(temp_history) == 0:
                for _ in range(HISTORY_SIZE):
                    temp_history.append(raw_temp)
            else:
                temp_history.append(raw_temp)
                if len(temp_history) > HISTORY_SIZE: temp_history.pop(0)
            
            avg_temp = round(sum(temp_history) / len(temp_history), 1)
            
            # --- UNLOCK THE ALARM THREAD ---
            if not is_sensor_ready:
                is_sensor_ready = True
                print("Sensor Ready! Engaging Alarm Logic.")
            # -------------------------------

            is_alarm_effectively_active = (avg_temp > IDEAL_TEMP_MAX or avg_temp < IDEAL_TEMP_MIN) and (not is_muted)
            status_msg = "ACTIVE" if is_alarm_effectively_active else "INACTIVE"
            
            print(f"Instant: {raw_temp} C | Avg: {avg_temp} C | System: {status_msg}")
            
            # Sending raw_temp or avg_temp is your choice, I prefer avg_temp usually
            db.send_data({"temperature": raw_temp, "alarm_status": status_msg})        
            
            last_read_time = current_time

        time.sleep(0.1)

except KeyboardInterrupt:
    print("\n[Main] Stopping System...")
    system_running = False 
    time.sleep(1)          
    print("[Main] System Halted.")