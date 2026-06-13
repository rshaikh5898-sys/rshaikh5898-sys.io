import time
import machine
import credentials

print("=" * 40)
print("  StudyBuddy ESP32 Booting...")
print("=" * 40)

ssid, password = credentials.load_credentials()

if not ssid:
    print("[Boot] No WiFi credentials found in flash.")
    print("[Boot] Entering BLE Setup Mode...")
    import ble_wifi_setup
    ble_wifi_setup.start()
else:
    print(f"[Boot] Found credentials for: {ssid}")
    # main.py will run automatically after boot.py finishes
