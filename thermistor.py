# File Name: thermistor.py
from machine import ADC
import math

class Thermistor:
    def __init__(self, pin, series_resistor=10000, beta=3950):
        """
        NTC Thermistor Library
        
        Parameters:
        pin: ADC pin number (e.g., 26, 27, 28)
        series_resistor: Value of the resistor used in voltage divider (Default: 10000 ohm)
        beta: Beta coefficient of the thermistor (Default: 3950)
        """
        self.adc = ADC(pin)
        self.series_resistor = series_resistor
        self.beta = beta

    def read_temp(self):
        """Reads data from the sensor and returns temperature in Celsius."""
        val = self.adc.read_u16()
        
        # Calculate Voltage (0 - 3.3V)
        voltage = (3.3 / 65535) * val
        
        # Error protection: Avoid division by zero or negative values
        if voltage <= 0: 
            return -999.0 # Error code
            
        try:
            # --- CORRECTED FORMULA ---
            # Circuit Configuration: 3.3V -> Thermistor -> Pin -> 10k Resistor -> GND
            # We calculate the resistance of the thermistor based on the voltage divider logic.
            resistance = (self.series_resistor * (3.3 - voltage)) / voltage
            
            # Steinhart-Hart Equation to convert resistance to temperature
            inv_T = (1 / 298.15) + (1 / self.beta) * math.log(resistance / 10000)
            temp_k = 1 / inv_T
            
            # Convert Kelvin to Celsius and round to 1 decimal place
            return round(temp_k - 273.15, 1)
            
        except Exception as e:
            # In case of any math error (like log of negative number), return 0.0
            return 0.0