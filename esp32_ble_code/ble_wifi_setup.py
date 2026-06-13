import bluetooth
import time
import network
import ujson
import machine
from machine import Pin
import credentials

BLE_NAME = "StudyBuddy-ESP32"

# UUIDs from prompt
SERVICE_UUID = bluetooth.UUID('6E400001-B5A3-F393-E0A9-E50E24DCCA9E')
RX_UUID = bluetooth.UUID('6E400002-B5A3-F393-E0A9-E50E24DCCA9E') # Browser writes here
TX_UUID = bluetooth.UUID('6E400003-B5A3-F393-E0A9-E50E24DCCA9E') # ESP notifies browser

# Flags
_FLAG_READ = const(0x0002)
_FLAG_WRITE = const(0x0008)
_FLAG_NOTIFY = const(0x0010)

led = Pin(2, Pin.OUT)
ble = bluetooth.BLE()
tx_handle = None
rx_handle = None
conn_handle = None

setup_complete = False

def blink_led(times):
    for _ in range(times):
        led.value(1)
        time.sleep(0.2)
        led.value(0)
        time.sleep(0.2)

def ble_irq(event, data):
    global conn_handle, tx_handle, rx_handle, setup_complete
    
    if event == 1: # _IRQ_CENTRAL_CONNECT
        conn_handle, _, _ = data
        print("[BLE] Connected")
        led.value(1)
        
    elif event == 2: # _IRQ_CENTRAL_DISCONNECT
        conn_handle = None
        print("[BLE] Disconnected")
        led.value(0)
        if not setup_complete:
            advertise()
            
    elif event == 3: # _IRQ_GATTS_WRITE
        conn, attr_handle = data
        if attr_handle == rx_handle:
            payload = ble.gatts_read(rx_handle)
            process_credentials(payload)

def send_status(status_dict):
    if conn_handle is not None and tx_handle is not None:
        payload = ujson.dumps(status_dict).encode()
        try:
            ble.gatts_notify(conn_handle, tx_handle, payload)
        except Exception as e:
            print("[BLE] Notify failed:", e)

def test_wifi(ssid, password):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(False)
    time.sleep(0.5)
    wlan.active(True)
    wlan.connect(ssid, password)
    
    timeout = 15
    while not wlan.isconnected() and timeout > 0:
        time.sleep(1)
        timeout -= 1
        
    if wlan.isconnected():
        return wlan.ifconfig()[0]
    return None

def process_credentials(payload):
    global setup_complete
    try:
        data_str = payload.decode('utf-8')
        data = ujson.loads(data_str)
        ssid = data.get("ssid")
        password = data.get("password")
        
        if ssid:
            print(f"[BLE] Received credentials for SSID: {ssid}")
            send_status({"status": "connecting"})
            
            ip = test_wifi(ssid, password)
            if ip:
                print(f"[WiFi] Success! IP: {ip}")
                credentials.save_credentials(ssid, password)
                send_status({"status": "connected", "ip": ip})
                setup_complete = True
                led.value(1)
                time.sleep(2) # let browser receive notify
                ble.active(False)
            else:
                print("[WiFi] Connection failed.")
                send_status({"status": "failed"})
                blink_led(3)
    except Exception as e:
        print("[BLE] Parse error:", e)
        send_status({"status": "failed"})

def advertise():
    print(f"[BLE] Advertising as {BLE_NAME}...")
    name = bytes(BLE_NAME, 'utf-8')
    adv_payload = bytearray([len(name) + 1, 0x09]) + name
    resp_payload = bytearray([17, 0x07]) + bytes(SERVICE_UUID)
    ble.gap_advertise(100000, adv_data=adv_payload, resp_data=resp_payload)

def start():
    global tx_handle, rx_handle
    ble.active(True)
    ble.irq(ble_irq)
    
    # Register Services
    service = (
        SERVICE_UUID,
        (
            (TX_UUID, _FLAG_READ | _FLAG_NOTIFY),
            (RX_UUID, _FLAG_WRITE),
        ),
    )
    
    services = (service,)
    ((tx_handle, rx_handle),) = ble.gatts_register_services(services)
    
    advertise()
    
    # Block until setup is complete
    print("[BLE] Waiting for WiFi credentials via Bluetooth...")
    while not setup_complete:
        time.sleep(1)
        
    print("[BLE] Setup complete. Proceeding to main app...")
