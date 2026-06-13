# ============================================================
# StudyBuddy ESP32 - Web Bluetooth Provisioning (Combined)
# ============================================================
import network
import urequests
import ujson
import time
import machine
import socket
import bluetooth
from machine import Pin, I2S
import uos

# ─── PIN & AUDIO CONFIG ──────────────────────────────────────────────────────
BTN_PIN     = 0
LED_PIN     = 2
MIC_SCK_PIN = 32
MIC_WS_PIN  = 33
MIC_SD_PIN  = 34
SPK_SCK_PIN = 26
SPK_WS_PIN  = 25
SPK_SD_PIN  = 22
SAMPLE_RATE  = 16000
SAMPLE_BITS  = 16
CHANNELS     = 1
RECORD_SECS  = 5
CHUNK_SIZE   = 512

# ─── SERVER CONFIG ────────────────────────────────────────────────────────────
SERVER_URL   = "https://20.248.194.187"
USERNAME     = "student1"
PASSWORD     = "student123"
DEVICE_ID    = "ESP32-001"

# ─── GLOBALS ──────────────────────────────────────────────────────────────────
led          = Pin(LED_PIN, Pin.OUT)
button       = Pin(BTN_PIN, Pin.IN, Pin.PULL_UP)
wlan_sta     = network.WLAN(network.STA_IF)
DEVICE_TOKEN = ""
CREDENTIALS_FILE = "credentials.json"

# ─── CREDENTIALS HELPERS ─────────────────────────────────────────────────────
def save_credentials(ssid, password):
    try:
        data = ujson.dumps({"ssid": ssid, "password": password})
        with open(CREDENTIALS_FILE, "w") as f:
            f.write(data)
        print("[Credentials] Saved to flash")
        return True
    except Exception as e:
        print("[Credentials] Save failed:", e)
        return False

def load_credentials():
    try:
        with open(CREDENTIALS_FILE, "r") as f:
            data = ujson.loads(f.read())
            return data.get("ssid", ""), data.get("password", "")
    except:
        return "", ""

def clear_credentials():
    try:
        uos.remove(CREDENTIALS_FILE)
        print("[Credentials] Cleared")
    except:
        pass

# ─── BLE SETUP HELPER ────────────────────────────────────────────────────────
BLE_NAME = "StudyBuddy-ESP32"
SERVICE_UUID = bluetooth.UUID('6E400001-B5A3-F393-E0A9-E50E24DCCA9E')
RX_UUID = bluetooth.UUID('6E400002-B5A3-F393-E0A9-E50E24DCCA9E')
TX_UUID = bluetooth.UUID('6E400003-B5A3-F393-E0A9-E50E24DCCA9E')

_FLAG_READ = const(0x0002)
_FLAG_WRITE = const(0x0008)
_FLAG_NOTIFY = const(0x0010)

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
        # Remove null bytes if buffer was padded
        payload = payload.replace(b'\x00', b'')
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
                save_credentials(ssid, password)
                send_status({"status": "connected", "ip": ip})
                setup_complete = True
                led.value(1)
                time.sleep(2)
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

def start_ble_setup():
    global tx_handle, rx_handle
    ble.active(True)
    try:
        ble.config(mtu=256)
    except:
        pass
    ble.irq(ble_irq)
    service = (SERVICE_UUID, ((TX_UUID, _FLAG_READ | _FLAG_NOTIFY), (RX_UUID, _FLAG_WRITE),),)
    services = (service,)
    ((tx_handle, rx_handle),) = ble.gatts_register_services(services)
    
    # Increase the characteristic buffer size from the default 20 bytes
    try:
        ble.gatts_write(rx_handle, bytes(256))
    except:
        pass
        
    advertise()
    print("[BLE] Waiting for WiFi credentials via Bluetooth...")
    while not setup_complete:
        time.sleep(1)
    print("[BLE] Setup complete.")

# ─── MAIN APP LOGIC ──────────────────────────────────────────────────────────
def led_on():  led.value(1)
def led_off(): led.value(0)
def led_fast_blink():
    for _ in range(6):
        led_on(); time.sleep_ms(80)
        led_off(); time.sleep_ms(80)

def connect_wifi_app():
    ssid, pwd = load_credentials()
    if not ssid: return False
    print("[WiFi] Connecting to:", ssid)
    wlan_sta.active(True)
    if wlan_sta.isconnected(): return True
    wlan_sta.connect(ssid, pwd)
    for _ in range(15):
        if wlan_sta.isconnected():
            print("[WiFi] Connected! IP:", wlan_sta.ifconfig()[0])
            blink_led(3)
            return True
        time.sleep(1)
    return False

def ensure_wifi():
    if not wlan_sta.isconnected():
        print("[WiFi] Lost connection, reconnecting...")
        while not connect_wifi_app():
            time.sleep(5)

def get_device_token():
    global DEVICE_TOKEN
    ensure_wifi()
    try:
        res = urequests.post(
            SERVER_URL + "/api/device/register",
            headers={"Content-Type": "application/json"},
            data=ujson.dumps({"username": USERNAME, "password": PASSWORD}),
            timeout=10,
            ssl_params={"cert_reqs": 0}
        )
        data = ujson.loads(res.text)
        res.close()
        if "token" in data:
            DEVICE_TOKEN = data["token"]
            print("[Auth] Token saved in memory!")
            return True
        return False
    except Exception as e:
        print("[Auth] Failed:", e)
        return False

def record_audio_with_count():
    print("[Mic] Recording...")
    led_on()
    mic = I2S(0, sck=Pin(MIC_SCK_PIN), ws=Pin(MIC_WS_PIN), sd=Pin(MIC_SD_PIN), mode=I2S.RX, bits=SAMPLE_BITS, format=I2S.MONO, rate=SAMPLE_RATE, ibuf=4000)
    audio_data = bytearray()
    max_bytes = SAMPLE_RATE * (SAMPLE_BITS // 8) * CHANNELS * RECORD_SECS
    buf = bytearray(CHUNK_SIZE)
    bytes_read = 0
    try:
        while bytes_read < max_bytes:
            num = mic.readinto(buf)
            audio_data.extend(buf[:num])
            bytes_read += num
            if button.value() == 1:
                break
    finally:
        mic.deinit()
    led_off()
    num_samples = len(audio_data) // (SAMPLE_BITS // 8)
    print("[Mic] Done:", num_samples, "samples")
    return bytes(audio_data), num_samples

def build_wav_header(num_samples):
    import struct
    data_size  = num_samples * CHANNELS * (SAMPLE_BITS // 8)
    total_size = data_size + 36
    return struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', total_size, b'WAVE', b'fmt ', 16, 1, CHANNELS, SAMPLE_RATE, SAMPLE_RATE * CHANNELS * (SAMPLE_BITS // 8), CHANNELS * (SAMPLE_BITS // 8), SAMPLE_BITS, b'data', data_size)

def play_wav(wav_data):
    print("[Speaker] Playing...")
    spk = I2S(1, sck=Pin(SPK_SCK_PIN), ws=Pin(SPK_WS_PIN), sd=Pin(SPK_SD_PIN), mode=I2S.TX, bits=SAMPLE_BITS, format=I2S.MONO, rate=SAMPLE_RATE, ibuf=4000)
    pcm = wav_data[44:]
    offset = 0
    while offset < len(pcm):
        spk.write(pcm[offset:offset+1024])
        offset += 1024
    spk.deinit()
    print("[Speaker] Done")

def transcribe_audio(raw_pcm, num_samples):
    ensure_wifi()
    wav = build_wav_header(num_samples) + raw_pcm
    try:
        res = urequests.post(SERVER_URL + "/api/stt", headers={"Content-Type": "audio/wav", "X-Device-Token": DEVICE_TOKEN}, data=wav, timeout=15, ssl_params={"cert_reqs": 0})
        data = ujson.loads(res.text)
        res.close()
        return data.get("text", "").strip()
    except Exception as e:
        print("[STT] Error:", e)
        return ""

def ask_ai(text):
    ensure_wifi()
    try:
        res = urequests.post(SERVER_URL + "/api/chat", headers={"Content-Type": "application/json", "X-Device-Token": DEVICE_TOKEN}, data=ujson.dumps({"text": text, "audio": True}), timeout=30, ssl_params={"cert_reqs": 0})
        data = ujson.loads(res.text)
        res.close()
        return data.get("text", ""), data.get("audio_url", "")
    except Exception as e:
        print("[AI] Error:", e)
        return "", ""

def download_audio(audio_url):
    ensure_wifi()
    try:
        res = urequests.get(SERVER_URL + audio_url, timeout=20, ssl_params={"cert_reqs": 0})
        wav = res.content
        res.close()
        return wav
    except Exception as e:
        print("[Audio] Error:", e)
        return None

def send_heartbeat():
    ensure_wifi()
    ssid, _ = load_credentials()
    ip = wlan_sta.ifconfig()[0] if wlan_sta.isconnected() else ""
    signal = wlan_sta.status('rssi') if wlan_sta.isconnected() else 0
    payload = {"device_id": DEVICE_ID, "ip": ip, "ssid": ssid, "status": "online", "signal": signal}
    try:
        res = urequests.post(SERVER_URL + "/api/esp32/heartbeat", headers={"Content-Type": "application/json", "X-Device-Token": DEVICE_TOKEN}, data=ujson.dumps(payload), timeout=5, ssl_params={"cert_reqs": 0})
        data = ujson.loads(res.text)
        res.close()
        cmd = data.get("command", "none")
        if cmd == "disconnect":
            print("[Command] Disconnect received! Wiping credentials and rebooting...")
            clear_credentials()
            machine.reset()
    except Exception as e:
        print("[Heartbeat] Error:", e)

# ─── BOOT SEQUENCE ───────────────────────────────────────────────────────────
print("=" * 40)
print("  StudyBuddy ESP32 Booting...")
print("=" * 40)

ssid, pwd = load_credentials()
if not ssid:
    print("[Boot] No WiFi credentials found in flash.")
    print("[Boot] Entering BLE Setup Mode...")
    start_ble_setup()
else:
    print(f"[Boot] Found credentials for: {ssid}")

print("[Main] Starting...")
if not connect_wifi_app():
    print("[Main] WiFi failed. Rebooting...")
    machine.reset()

while not get_device_token():
    time.sleep(5)

blink_led(5)
print("[Main] Ready! Hold button to talk.")

ping_counter = 0

while True:
    ping_counter += 1
    if ping_counter >= 300: # Every 30 seconds
        ping_counter = 0
        send_heartbeat()

    if button.value() == 0:
        time.sleep_ms(50)
        if button.value() == 0:
            print("\n[Loop] Listening...")
            led_fast_blink()
            raw_pcm, num_samples = record_audio_with_count()
            if num_samples < SAMPLE_RATE * 0.5:
                blink_led(2)
                continue
            led_on()
            text = transcribe_audio(raw_pcm, num_samples)
            if not text:
                blink_led(4); led_off()
                continue
            reply_text, audio_url = ask_ai(text)
            if not reply_text:
                blink_led(4); led_off()
                continue
            if audio_url:
                wav = download_audio(audio_url)
                led_off()
                if wav:
                    play_wav(wav)
            else:
                led_off()
            print("[Loop] Ready!")
    time.sleep_ms(100)
