from machine import Pin
import time
import network
import socket
import config
import sys

# Import custom library
from thermistor import Thermistor
from firebasedb_process import FirebaseDB

#wifi info
ssid = config.ssid
password = config.pwd

# --- HARDWARE SETUP ---
# Initialize Sensor using custom library
temp_sensor = Thermistor(pin=26)

blue_led = Pin(14, Pin.OUT)    # Cold Indicator
red_led = Pin(15, Pin.OUT)     # Hot Indicator
buzzer = Pin(13, Pin.OUT)      # Alarm
mute_button = Pin(10, Pin.IN, Pin.PULL_UP) # Button on GP10
green_led = Pin(9, Pin.OUT)    # wifi led

# --- SETTINGS ---
IDEAL_TEMP_MIN = 21.0  # Initial min temp
IDEAL_TEMP_MAX = 27.0  # Initial max temp
BEEP_INTERVAL = 500    # Beep speed in milliseconds (0.5 seconds)
READ_INTERVAL = 1      # Data reading frequency in seconds from thermistor
SETTINGS_INTERVAL = 5.0    # Check Firebase settings every 5 seconds
HISTORY_SIZE = 5       # Number of readings to keep for averaging
WIFI_ATTEMPT = 5
WIFI_CONNECTED_CODE = 3

# --- STATE VARIABLES ---
is_alarm_active = False  # Tracks if the buzzer is currently sounding
is_muted = False       # Tracks if the user silenced the alarm
last_settings_time = 0
last_beep_time = 0     # Timer for the buzzer (Non-blocking)
buzzer_state = 0       # Current state of buzzer (0 or 1)

last_read_time = 0     # Tracks when we last read the sensor
temp_history = []      # List to store past temperature readings
avg_temp = 0           # Calculated AVERAGE temperature (Used for logic)

# --- INTERRUPT HANDLER ---
# Make button press non blockable
last_button_press = 0

def button_handler(pin):
    global is_muted, last_button_press
    current_time = time.ticks_ms()
    
    # Debounce
    if time.ticks_diff(current_time, last_button_press) > 300:
        is_muted = not is_muted
        print(f"\n>>> INTERRUPT: Mute toggled! New state: {is_muted}")
        last_button_press = current_time

# When button pressed, trigger button_handler function
mute_button.irq(trigger=Pin.IRQ_FALLING, handler=button_handler)

# --- WIFI CONNECTION SETUP ---
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wifi_connected = False

# Try to connect WIFI_ATTEMPT times
for attempt in range(0, WIFI_ATTEMPT):
    print(f"Attempt {attempt}/{WIFI_ATTEMPT}...")
    wlan.connect(ssid, password)
    time.sleep(3) # Wait 3 seconds for connection handshake
    
    current_status = wlan.status()
    if current_status == WIFI_CONNECTED_CODE:
        wifi_connected = True
        break

# --- CHECK CONNECTION RESULT ---
if current_status == WIFI_CONNECTED_CODE:
    print("Connected to Wi-Fi!")
    # SUCCESS SEQUENCE: Green LED ON for 3 seconds
    green_led.value(1)
    time.sleep(3)
    green_led.value(0)
else:
    print("Connection Failed after 5 attempts.")
    # FAILURE SEQUENCE: Red LED ON for 3 seconds
    red_led.value(1)
    time.sleep(3)
    red_led.value(0)
    
    print("System Halted due to Wi-Fi failure.")
    sys.exit() # STOP THE PROGRAM
        
db = FirebaseDB(url=config.firebase_url, tablename=config.table_name)

print("System Started...")
print(f"Ideal Range: {IDEAL_TEMP_MIN} C - {IDEAL_TEMP_MAX} C")
try:
    while True:
        current_time = time.ticks_ms()
        
        # ---------------------------------------------------------
        # TASK 1: CHECK FIREBASE SETTINGS
        # ---------------------------------------------------------
        # We do this LESS frequently to avoid slowing down the device
        if time.ticks_diff(current_time, last_settings_time) > (SETTINGS_INTERVAL * 1000):
            print("[System] Checking for new settings...")
            new_settings = db.get_settings()
            
            if new_settings:
                # Update limits only if data is valid
                old_min = IDEAL_TEMP_MIN
                old_max = IDEAL_TEMP_MAX
                
                IDEAL_TEMP_MIN = float(new_settings.get('min_temp', IDEAL_TEMP_MIN))
                IDEAL_TEMP_MAX = float(new_settings.get('max_temp', IDEAL_TEMP_MAX))
                
                # Check if something actually changed to print log
                if old_min != IDEAL_TEMP_MIN or old_max != IDEAL_TEMP_MAX:
                    print(f"!!! UPDATE !!! New Limits -> Min: {IDEAL_TEMP_MIN} | Max: {IDEAL_TEMP_MAX}")
            
            last_settings_time = current_time

        # ---------------------------------------------------------
        # TASK 1: SENSOR READING & AVERAGING (Runs every 3 seconds)
        # ---------------------------------------------------------
        if time.ticks_diff(current_time, last_read_time) > (READ_INTERVAL * 1000):
            
            # 1. Read instant temperature
            raw_temp = temp_sensor.read_temp()
            status_msg = "ACTIVE" if is_alarm_active else "INACTIVE"
            # SEND DATA TO FIREBASEDB
            data_packet = {
                "temperature": raw_temp,
                "alarm_status": status_msg
            }
            db.send_data(data_packet)
            
            # 2. Add to history list
            temp_history.append(raw_temp)
            
            # 3. Keep only the last N readings. Remove oldest if full
            if len(temp_history) > HISTORY_SIZE:
                temp_history.pop(0) 
            
            # 4. Calculate Average
            avg_temp = sum(temp_history) / len(temp_history)
            avg_temp = round(avg_temp, 1) 
            
            # Print both Raw and Average to compare
            print(f"Instant temp: {raw_temp} C | Avg temp (Smooth): {avg_temp} C | System: {status_msg}")
            
            last_read_time = current_time

        # ---------------------------------------------------------
        # TASK 3: ALARM LOGIC (Based on AVERAGE TEMP)
        # ---------------------------------------------------------
        
        if avg_temp < IDEAL_TEMP_MIN:
            # --- CONDITION: COLD ---
            blue_led.value(1)
            red_led.value(0)
            
            if not is_muted:
                if time.ticks_diff(current_time, last_beep_time) > BEEP_INTERVAL:
                    buzzer_state = not buzzer_state
                    buzzer.value(buzzer_state)
                    last_beep_time = current_time
                    is_alarm_active = True
            else:
                buzzer.value(0)
                is_alarm_active = False

        elif avg_temp > IDEAL_TEMP_MAX:
            # --- CONDITION: HOT ---
            blue_led.value(0)
            red_led.value(1)
            
            if not is_muted:
                if time.ticks_diff(current_time, last_beep_time) > BEEP_INTERVAL:
                    buzzer_state = not buzzer_state
                    buzzer.value(buzzer_state)
                    last_beep_time = current_time
                    is_alarm_active = True
            else:
                buzzer.value(0)
                is_alarm_active = False

        else:
            # --- CONDITION: IDEAL ---
            blue_led.value(0)
            red_led.value(0)
            buzzer.value(0)
            
            # Reset mute automatically when temp returns to normal
            is_muted = False
            is_alarm_active = False

        # Short delay to be CPU friendly
        time.sleep(0.05)

except KeyboardInterrupt:
    # --- CLEANUP ---
    print("\nProgram Stopped. Turning off components...")
    blue_led.value(0)
    red_led.value(0)
    buzzer.value(0)