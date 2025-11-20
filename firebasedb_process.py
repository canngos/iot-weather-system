# File Name: database.py
import urequests
import ujson

class FirebaseDB:
    def __init__(self, url, tablename):
        """
        Initializes the Firebase Realtime Database connection.
        """
        self.url = url
        self.tablename = tablename

    def send_data(self, data_dict):
        """
        Sends data to Firebase.
        """
        try:
            # Firebase REST API format: URL/TableName.json
            full_url = f"{self.url}/{self.tablename}.json"
            
            # Make HTTP POST request (POST adds a new unique entry)
            response = urequests.post(full_url, json=data_dict)
            
            # Check response code (200 OK)
            if response.status_code == 200:
                print(">> [Firebase] Upload Success!")
                response.close()
                return True
            else:
                print(f"!! [Firebase] Error: {response.status_code} - {response.text}")
                response.close()
                return False
                
        except Exception as e:
            print(f"!! [Firebase] Connection Error: {e}")
            return False
        
    def get_settings(self):
        """
        Fetches configuration from the 'settings' node (GET).
        Returns: Dictionary (e.g., {'min_temp': 18, 'max_temp': 27}) or None
        """
        try:
            full_url = f"{self.url}/settings.json"
            
            response = urequests.get(full_url)
            
            if response.status_code == 200:
                data = response.json()
                response.close()
                return data
            else:
                response.close()
                return None
        except Exception as e:
            print(f"!! [Firebase] Fetch Error: {e}")
            return None  

