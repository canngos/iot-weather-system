# File Name: main.py
from machine import Pin
import time
import network   # For Wi-Fi
import urequests # For HTTP requests (MongoDB)

# Import our custom library
from thermistor import Thermistor 

# --- HARDWARE SETUP ---
# Initialize Sensor using our library (GP26)
temp_sensor = Thermistor(pin=26)

blue_led = Pin(14, Pin.OUT)    # Cold Indicator
red_led = Pin(15, Pin.OUT)     # Hot Indicator
buzzer = Pin(13, Pin.OUT)      # Alarm
mute_button = Pin(10, Pin.IN, Pin.PULL_UP) # Button on GP10

# --- SETTINGS ---
IDEAL_TEMP_MIN = 21.0  # Below this is COLD
IDEAL_TEMP_MAX = 27.0  # Above this is HOT
BEEP_INTERVAL = 500    # Beep speed in milliseconds (0.5 seconds)
READ_INTERVAL = 0.5    # Data reading frequency in seconds from thermistor
HISTORY_SIZE = 5       # Number of readings to keep for averaging

# --- STATE VARIABLES ---
is_muted = False       # Tracks if the user silenced the alarm
last_beep_time = 0     # Timer for the buzzer (Non-blocking)
buzzer_state = 0       # Current state of buzzer (0 or 1)

last_read_time = 0     # Tracks when we last read the sensor
temp_history = []      # List to store past temperature readings
avg_temp = 0           # Calculated AVERAGE temperature (Used for logic)

print("System Started...")
print(f"Ideal Range: {IDEAL_TEMP_MIN} C - {IDEAL_TEMP_MAX} C")

# --- OPTIONAL: WIFI CONNECTION SETUP ---
# wlan = network.WLAN(network.STA_IF)
# wlan.active(True)
# wlan.connect("YOUR_WIFI_SSID", "YOUR_WIFI_PASSWORD")
# while not wlan.isconnected():
#     time.sleep(1)
# print("Connected to Wi-Fi")


# -------------------------------------------------------
        # --- MONGODB CLOUD DATA UPLOAD (PLACEHOLDER) ---
        # -------------------------------------------------------
        # Here you will send the 'current_temp' to MongoDB Atlas.
        #
        # Example Logic:
        # url = "https://data.mongodb-api.com/app/...../action/insertOne"
        # headers = {"Content-Type": "application/json", "api-key": "YOUR_API_KEY"}
        # payload = {
        #     "collection": "sensor_data",
        #     "database": "home_iot",
        #     "dataSource": "Cluster0",
        #     "document": {"temp": current_temp, "status": "active"}
        # }
        # try:
        #     response = urequests.post(url, headers=headers, json=payload)
        #     # print("Data Sent:", response.text)
        #     response.close()
        # except:
        #     print("Upload Failed")
        # -------------------------------------------------------
        
        
try:
    while True:
        current_time = time.ticks_ms()

        # ---------------------------------------------------------
        # TASK 1: SENSOR READING & AVERAGING (Runs every 3 seconds)
        # ---------------------------------------------------------
        if time.ticks_diff(current_time, last_read_time) > (READ_INTERVAL * 1000):
            
            # 1. Read instant temperature
            raw_temp = temp_sensor.read_temp()
            
            # 2. Add to history list
            temp_history.append(raw_temp)
            
            # 3. Keep only the last N readings (Remove oldest if full)
            if len(temp_history) > HISTORY_SIZE:
                temp_history.pop(0) 
            
            # 4. Calculate Average (Crucial Step)
            avg_temp = sum(temp_history) / len(temp_history)
            avg_temp = round(avg_temp, 1) 
            
            status_msg = "MUTED" if is_muted else "ACTIVE"
            # Print both Raw and Average to compare
            print(f"Raw: {raw_temp} C | Avg (Smooth): {avg_temp} C | System: {status_msg}")
            
            # --- MONGODB CODE GOES HERE ---
            # Ideally send 'avg_temp' to cloud for cleaner data graphs.
            
            last_read_time = current_time

        # ---------------------------------------------------------
        # TASK 2: BUTTON CONTROL (Instant Response)
        # ---------------------------------------------------------
        if mute_button.value() == 0:
            is_muted = not is_muted
            print(">>> BUTTON PRESSED: Mute state changed!")
            time.sleep(0.3) 

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
            else:
                buzzer.value(0)

        elif avg_temp > IDEAL_TEMP_MAX:
            # --- CONDITION: HOT ---
            blue_led.value(0)
            red_led.value(1)
            
            if not is_muted:
                if time.ticks_diff(current_time, last_beep_time) > BEEP_INTERVAL:
                    buzzer_state = not buzzer_state
                    buzzer.value(buzzer_state)
                    last_beep_time = current_time
            else:
                buzzer.value(0)

        else:
            # --- CONDITION: IDEAL ---
            blue_led.value(0)
            red_led.value(0)
            buzzer.value(0)
            
            # Reset mute automatically when temp returns to normal
            if is_muted: is_muted = False

        # Short delay to be CPU friendly
        time.sleep(0.05)

except KeyboardInterrupt:
    # --- CLEANUP ---
    print("\nProgram Stopped. Turning off components...")
    blue_led.value(0)
    red_led.value(0)
    buzzer.value(0)