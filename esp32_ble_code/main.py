import network
import urequests
import ujson
import time
import machine
import socket
from machine import Pin, I2S
import credentials

# ─── PIN CONFIG ──────────────────────────────────────────────────────────────
BTN_PIN     = 0
LED_PIN     = 2
MIC_SCK_PIN = 32
MIC_WS_PIN  = 33
MIC_SD_PIN  = 34
SPK_SCK_PIN = 26
SPK_WS_PIN  = 25
SPK_SD_PIN  = 22

# ─── AUDIO CONFIG ─────────────────────────────────────────────────────────────
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

def led_on():  led.value(1)
def led_off(): led.value(0)

def led_blink(times=3, delay_ms=200):
    for _ in range(times):
        led_on();  time.sleep_ms(delay_ms)
        led_off(); time.sleep_ms(delay_ms)

def led_fast_blink():
    for _ in range(6):
        led_on();  time.sleep_ms(80)
        led_off(); time.sleep_ms(80)

def connect_wifi():
    ssid, pwd = credentials.load_credentials()
    if not ssid: return False
    
    print("[WiFi] Connecting to:", ssid)
    wlan_sta.active(True)
    if wlan_sta.isconnected(): return True
    wlan_sta.connect(ssid, pwd)
    
    for _ in range(15):
        if wlan_sta.isconnected():
            print("[WiFi] Connected! IP:", wlan_sta.ifconfig()[0])
            led_blink(3, 150)
            return True
        time.sleep(1)
    return False

def ensure_wifi():
    if not wlan_sta.isconnected():
        print("[WiFi] Lost connection, reconnecting...")
        while not connect_wifi():
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
    mic = I2S(0, sck=Pin(MIC_SCK_PIN), ws=Pin(MIC_WS_PIN), sd=Pin(MIC_SD_PIN),
              mode=I2S.RX, bits=SAMPLE_BITS, format=I2S.MONO, rate=SAMPLE_RATE, ibuf=4000)
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
    return struct.pack('<4sI4s4sIHHIIHH4sI',
        b'RIFF', total_size, b'WAVE', b'fmt ', 16,
        1, CHANNELS, SAMPLE_RATE,
        SAMPLE_RATE * CHANNELS * (SAMPLE_BITS // 8),
        CHANNELS * (SAMPLE_BITS // 8),
        SAMPLE_BITS, b'data', data_size)

def play_wav(wav_data):
    print("[Speaker] Playing...")
    spk = I2S(1, sck=Pin(SPK_SCK_PIN), ws=Pin(SPK_WS_PIN), sd=Pin(SPK_SD_PIN),
              mode=I2S.TX, bits=SAMPLE_BITS, format=I2S.MONO, rate=SAMPLE_RATE, ibuf=4000)
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
        res = urequests.post(SERVER_URL + "/api/stt",
            headers={"Content-Type": "audio/wav", "X-Device-Token": DEVICE_TOKEN},
            data=wav, timeout=15, ssl_params={"cert_reqs": 0})
        data = ujson.loads(res.text)
        res.close()
        return data.get("text", "").strip()
    except Exception as e:
        print("[STT] Error:", e)
        return ""

def ask_ai(text):
    ensure_wifi()
    try:
        res = urequests.post(SERVER_URL + "/api/chat",
            headers={"Content-Type": "application/json", "X-Device-Token": DEVICE_TOKEN},
            data=ujson.dumps({"text": text, "audio": True}), timeout=30, ssl_params={"cert_reqs": 0})
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
    ssid, _ = credentials.load_credentials()
    ip = wlan_sta.ifconfig()[0] if wlan_sta.isconnected() else ""
    signal = wlan_sta.status('rssi') if wlan_sta.isconnected() else 0
    
    payload = {
        "device_id": DEVICE_ID,
        "ip": ip,
        "ssid": ssid,
        "status": "online",
        "signal": signal
    }
    
    try:
        res = urequests.post(
            SERVER_URL + "/api/esp32/heartbeat",
            headers={"Content-Type": "application/json", "X-Device-Token": DEVICE_TOKEN},
            data=ujson.dumps(payload),
            timeout=5,
            ssl_params={"cert_reqs": 0}
        )
        data = ujson.loads(res.text)
        res.close()
        
        cmd = data.get("command", "none")
        if cmd == "disconnect":
            print("[Command] Disconnect received! Wiping credentials and rebooting...")
            credentials.clear_credentials()
            machine.reset()
            
    except Exception as e:
        print("[Heartbeat] Error:", e)

print("[Main] Starting...")
if not connect_wifi():
    print("[Main] WiFi failed. Rebooting...")
    machine.reset()

while not get_device_token():
    time.sleep(5)

led_blink(5, 100)
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
                led_blink(2, 300)
                continue
            led_on()
            text = transcribe_audio(raw_pcm, num_samples)
            if not text:
                led_blink(4, 150); led_off()
                continue
            reply_text, audio_url = ask_ai(text)
            if not reply_text:
                led_blink(4, 150); led_off()
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
