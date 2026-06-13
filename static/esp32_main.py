# ============================================================
# StudyBuddy ESP32 - MicroPython Voice Assistant
# WiFi config via hotspot — no hardcoded credentials needed
# ============================================================

import network
import urequests
import ujson
import time
import machine
import socket
from machine import Pin, I2S

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
SERVER_URL   = "http://20.248.194.187"
USERNAME     = "student1"
PASSWORD     = "student123"

# ─── GLOBALS ──────────────────────────────────────────────────────────────────
led          = Pin(LED_PIN, Pin.OUT)
button       = Pin(BTN_PIN, Pin.IN, Pin.PULL_UP)
wlan_sta     = network.WLAN(network.STA_IF)
wlan_ap      = network.WLAN(network.AP_IF)
DEVICE_TOKEN = ""

# ─── LED HELPERS ──────────────────────────────────────────────────────────────
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

# ─── WIFI CREDENTIALS: SAVE / LOAD ───────────────────────────────────────────
def save_wifi(ssid, password):
    data = ujson.dumps({"ssid": ssid, "password": password})
    with open("wifi.json", "w") as f:
        f.write(data)
    print("[WiFi] Credentials saved for: " + ssid)

def load_wifi():
    try:
        with open("wifi.json", "r") as f:
            data = ujson.loads(f.read())
            return data.get("ssid", ""), data.get("password", "")
    except:
        return "", ""

def clear_wifi():
    try:
        import uos
        uos.remove("wifi.json")
        print("[WiFi] Credentials cleared")
    except:
        pass

# ─── WIFI: CONNECT TO ROUTER ──────────────────────────────────────────────────
def connect_wifi(ssid, password, max_retries=15):
    print("[WiFi] Connecting to: " + ssid)
    wlan_sta.active(False)
    time.sleep_ms(500)
    wlan_sta.active(True)
    time.sleep_ms(500)

    if wlan_sta.isconnected():
        print("[WiFi] Already connected: " + wlan_sta.ifconfig()[0])
        return True

    try:
        wlan_sta.connect(ssid, password)
    except OSError as e:
        print("[WiFi] Connect error, retrying...")
        wlan_sta.active(False)
        time.sleep(2)
        wlan_sta.active(True)
        time.sleep_ms(500)
        wlan_sta.connect(ssid, password)

    for attempt in range(max_retries):
        if wlan_sta.isconnected():
            print("[WiFi] Connected! IP: " + wlan_sta.ifconfig()[0])
            led_blink(3, 150)
            return True
        print("[WiFi] Waiting... " + str(attempt+1) + "/" + str(max_retries))
        led_on(); time.sleep_ms(500); led_off(); time.sleep_ms(500)

    print("[WiFi] Failed to connect")
    return False

def ensure_wifi():
    if not wlan_sta.isconnected():
        print("[WiFi] Lost connection, reconnecting...")
        ssid, password = load_wifi()
        while not connect_wifi(ssid, password):
            time.sleep(5)

# ─── HOTSPOT SETUP MODE ───────────────────────────────────────────────────────
def start_hotspot():
    wlan_ap.active(True)
    wlan_ap.config(
        essid="StudyBuddy-Setup",
        password="studybuddy123",
        authmode=network.AUTH_WPA_WPA2_PSK
    )
    time.sleep(1)
    ip = wlan_ap.ifconfig()[0]
    print("[Hotspot] Started! SSID: StudyBuddy-Setup  Password: studybuddy123")
    print("[Hotspot] Open browser: http://" + ip)
    return ip

def stop_hotspot():
    wlan_ap.active(False)
    print("[Hotspot] Stopped")

# ─── SETUP WEB PAGE ───────────────────────────────────────────────────────────
SETUP_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StudyBuddy WiFi Setup</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,sans-serif;background:#0d1117;color:#e6edf3;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:#161b22;border:1px solid #30363d;border-radius:16px;padding:36px 28px;width:100%;max-width:380px}
.logo{font-size:40px;text-align:center;margin-bottom:12px}
h1{font-size:22px;font-weight:700;text-align:center;margin-bottom:6px}
p{color:#8b949e;font-size:14px;text-align:center;margin-bottom:28px}
label{display:block;font-size:12px;color:#8b949e;margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px}
input{width:100%;background:#0d1117;border:1px solid #30363d;border-radius:10px;padding:12px 14px;color:#e6edf3;font-size:15px;outline:none;margin-bottom:18px}
input:focus{border-color:#58a6ff}
button{width:100%;background:linear-gradient(135deg,#58a6ff,#1f6feb);color:#fff;border:none;border-radius:10px;padding:14px;font-size:15px;font-weight:600;cursor:pointer}
.ok{margin-top:16px;padding:12px;border-radius:10px;font-size:13px;text-align:center;background:#3fb95020;border:1px solid #3fb95040;color:#3fb950;display:none}
.err{margin-top:16px;padding:12px;border-radius:10px;font-size:13px;text-align:center;background:#f8514920;border:1px solid #f8514940;color:#f85149;display:none}
</style>
</head>
<body>
<div class="card">
<div class="logo">🎓</div>
<h1>StudyBuddy Setup</h1>
<p>Enter your WiFi details to connect StudyBuddy to your network</p>
<label>WiFi Name (SSID)</label>
<input type="text" id="ssid" placeholder="e.g. Airtel_Home" autocomplete="off"/>
<label>WiFi Password</label>
<input type="password" id="pass" placeholder="Your WiFi password"/>
<button onclick="save()">Connect & Save</button>
<div class="ok" id="ok">✅ Saved! Device will now connect to your WiFi. You can close this page.</div>
<div class="err" id="err">❌ Error saving. Please try again.</div>
</div>
<script>
async function save(){
  var ssid=document.getElementById('ssid').value.trim();
  var pass=document.getElementById('pass').value;
  if(!ssid){alert('Please enter WiFi name');return;}
  try{
    var r=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ssid:ssid,password:pass})});
    if(r.ok){document.getElementById('ok').style.display='block';}
    else{document.getElementById('err').style.display='block';}
  }catch(e){document.getElementById('ok').style.display='block';}
}
</script>
</body>
</html>"""

def run_setup_server():
    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(3)
    print("[Setup] Web server running, waiting for config...")

    while True:
        try:
            conn, addr = s.accept()
            request = b""
            conn.settimeout(3)
            try:
                while True:
                    chunk = conn.recv(256)
                    if not chunk: break
                    request += chunk
                    if len(request) > 2048: break
            except: pass

            req = request.decode("utf-8", "ignore")

            if "POST /save" in req:
                try:
                    body = req[req.index("\r\n\r\n")+4:]
                    data = ujson.loads(body)
                    ssid = data.get("ssid", "")
                    pwd  = data.get("password", "")
                    save_wifi(ssid, pwd)
                    conn.send(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"ok\":true}")
                    conn.close()
                    s.close()
                    return ssid, pwd
                except Exception as e:
                    print("[Setup] Parse error:", e)
                    conn.send(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            else:
                html = SETUP_HTML
                resp = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: " + str(len(html)) + "\r\n\r\n" + html
                conn.send(resp.encode())

            conn.close()

        except OSError:
            led_on(); time.sleep_ms(200); led_off()
            continue

    s.close()
    return "", ""

# ─── TOKEN MANAGEMENT ─────────────────────────────────────────────────────────
def load_token():
    global DEVICE_TOKEN
    try:
        with open("token.txt", "r") as f:
            DEVICE_TOKEN = f.read().strip()
            print("[Auth] Token loaded")
    except:
        DEVICE_TOKEN = ""

def save_token(token):
    with open("token.txt", "w") as f:
        f.write(token)

def get_device_token():
    global DEVICE_TOKEN
    ensure_wifi()
    try:
        res = urequests.post(
            SERVER_URL + "/api/device/register",
            headers={"Content-Type": "application/json"},
            data=ujson.dumps({"username": USERNAME, "password": PASSWORD}),
            timeout=10
        )
        data = ujson.loads(res.text)
        res.close()
        if "token" in data:
            DEVICE_TOKEN = data["token"]
            save_token(DEVICE_TOKEN)
            print("[Auth] Token saved!")
            return True
        return False
    except Exception as e:
        print("[Auth] Failed:", e)
        return False

# ─── POLL SERVER FOR NEW WIFI CONFIG ─────────────────────────────────────────
def check_for_new_wifi():
    """
    Poll the server every 30 seconds.
    If admin pushed new WiFi credentials from the web app,
    save them and reconnect automatically.
    """
    try:
        res = urequests.get(
            SERVER_URL + "/api/wifi/config",
            headers={"X-Device-Token": DEVICE_TOKEN},
            timeout=8
        )
        data = ujson.loads(res.text)
        res.close()

        if data.get("new_wifi"):
            new_ssid = data.get("ssid", "")
            new_pass = data.get("password", "")
            print("[WiFi] New credentials received from server: " + new_ssid)
            save_wifi(new_ssid, new_pass)
            print("[WiFi] Reconnecting to new WiFi...")
            led_blink(3, 100)
            if connect_wifi(new_ssid, new_pass):
                print("[WiFi] Switched to new WiFi successfully!")
                led_blink(5, 100)
            else:
                print("[WiFi] Failed to connect to new WiFi, keeping old one")
    except Exception as e:
        print("[WiFi Poll] Error:", e)

# ─── RECORD AUDIO ─────────────────────────────────────────────────────────────
def record_audio_with_count():
    print("[Mic] Recording...")
    led_on()
    mic = I2S(0, sck=Pin(MIC_SCK_PIN), ws=Pin(MIC_WS_PIN), sd=Pin(MIC_SD_PIN),
              mode=I2S.RX, bits=SAMPLE_BITS, format=I2S.MONO, rate=SAMPLE_RATE, ibuf=4000)
    audio_data = bytearray()
    max_bytes = SAMPLE_RATE * (SAMPLE_BITS // 8) * CHANNELS * RECORD_SECS
    buf = bytearray(CHUNK_SIZE)
    bytes_read = 0
    while bytes_read < max_bytes:
        num = mic.readinto(buf)
        audio_data.extend(buf[:num])
        bytes_read += num
        if button.value() == 1:
            break
    mic.deinit()
    led_off()
    num_samples = len(audio_data) // (SAMPLE_BITS // 8)
    print("[Mic] Done: " + str(num_samples) + " samples")
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
            data=wav, timeout=15)
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
            data=ujson.dumps({"text": text, "audio": True}), timeout=30)
        data = ujson.loads(res.text)
        res.close()
        return data.get("text", ""), data.get("audio_url", "")
    except Exception as e:
        print("[AI] Error:", e)
        return "", ""

def download_audio(audio_url):
    ensure_wifi()
    try:
        res = urequests.get(SERVER_URL + audio_url, timeout=20)
        wav = res.content
        res.close()
        return wav
    except Exception as e:
        print("[Audio] Error:", e)
        return None

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    global DEVICE_TOKEN
    print("=" * 40)
    print("  StudyBuddy ESP32 Booting...")
    print("=" * 40)

    ssid, password = load_wifi()

    if not ssid:
        print("[Boot] No WiFi saved — starting hotspot setup...")
        led_blink(10, 100)
        ip = start_hotspot()
        print("[Boot] Connect phone to: StudyBuddy-Setup")
        print("[Boot] Password: studybuddy123")
        print("[Boot] Then open: http://" + ip)
        ssid, password = run_setup_server()
        stop_hotspot()
        if not ssid:
            print("[Boot] No config received, restarting...")
            time.sleep(3)
            machine.reset()

    if not connect_wifi(ssid, password):
        print("[Boot] Wrong WiFi password? Clearing and restarting...")
        clear_wifi()
        time.sleep(3)
        machine.reset()

    load_token()
    if not DEVICE_TOKEN:
        while not get_device_token():
            time.sleep(5)

    led_blink(5, 100)
    print("[Boot] Ready! Hold button to talk.")

    wifi_check_counter = 0   # Poll server for new WiFi every 30 seconds

    while True:
        # Check for new WiFi credentials from web app every 30 seconds
        wifi_check_counter += 1
        if wifi_check_counter >= 300:   # 300 x 100ms = 30 seconds
            wifi_check_counter = 0
            check_for_new_wifi()

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

if __name__ == "__main__":
    main()
