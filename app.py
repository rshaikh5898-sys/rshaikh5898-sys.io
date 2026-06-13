"""
StudyBuddy - AI Voice Assistant for Students
Backend: Flask + OpenRouter AI + Coqui TTS
"""

from flask import Flask, request, jsonify, send_file, render_template, session, redirect, url_for
from flask_cors import CORS
from functools import wraps
import requests
import os
import uuid
import json
import time
import io
import threading
import speech_recognition as sr
from pathlib import Path
from TTS.api import TTS as CoquiTTS
import torch
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from filelock import FileLock

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.environ.get("SECRET_KEY", "studybuddy-secret-key-change-in-prod")
CORS(app, supports_credentials=True)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# ─── CONFIG ────────────────────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY:
    print("WARNING: OPENROUTER_API_KEY not set. Using fallback for local testing ONLY.")
    OPENROUTER_API_KEY = "YOUR_OPENROUTER_API_KEY_HERE"

OPENROUTER_MODEL   = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")
AUDIO_DIR          = Path("static/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
USERS_FILE         = Path("users.json")
ESP32_DEVICES_FILE = Path("esp32_devices.json")

# ─── TTS SETUP ────────────────────────────────────────────────────────────────
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"[TTS] Loading model on {device}...")
try:
    tts_model = CoquiTTS("tts_models/en/ljspeech/tacotron2-DDC").to(device)
    print("[TTS] Model loaded successfully!")
except Exception as e:
    print(f"[TTS] Warning: Could not load TTS model: {e}")
    tts_model = None

# ─── AUDIO CLEANUP THREAD ─────────────────────────────────────────────────────
def background_cleanup():
    while True:
        try:
            now = time.time()
            for f in AUDIO_DIR.glob("*.wav"):
                if now - f.stat().st_mtime > 300:
                    f.unlink()
        except:
            pass
        time.sleep(60)

cleanup_thread = threading.Thread(target=background_cleanup, daemon=True)
cleanup_thread.start()

# ─── SYSTEM PROMPT ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are StudyBuddy, a friendly and knowledgeable AI assistant designed specifically for students. 

Your personality:
- Warm, encouraging, and patient
- You explain things clearly using simple language
- You use examples and analogies to explain difficult concepts
- You celebrate student effort and curiosity
- You are concise — keep answers under 100 words unless explaining a complex topic
- You can do casual chat, answer homework questions, explain textbook concepts, and give study tips

Rules:
- Never be discouraging
- If you don't know something, say so honestly
- Always speak in a way that can be understood when read aloud (no bullet points, markdown, or special characters)
- Use natural spoken language
"""

# ─── USER MANAGEMENT ──────────────────────────────────────────────────────────
USERS_LOCK = FileLock("users.json.lock")

def load_users():
    with USERS_LOCK:
        if USERS_FILE.exists():
            return json.loads(USERS_FILE.read_text())
        default = {
            "admin": {
                "password": generate_password_hash("admin123"),
                "name": "Admin",
                "role": "admin"
            },
            "student1": {
                "password": generate_password_hash("student123"),
                "name": "Rehan",
                "role": "student"
            }
        }
        USERS_FILE.write_text(json.dumps(default, indent=2))
        return default

def save_users(users):
    with USERS_LOCK:
        USERS_FILE.write_text(json.dumps(users, indent=2))

ESP32_LOCK = FileLock("esp32_devices.json.lock")

def load_esp32_devices():
    with ESP32_LOCK:
        if ESP32_DEVICES_FILE.exists():
            return json.loads(ESP32_DEVICES_FILE.read_text())
        return {}

def save_esp32_devices(devices):
    with ESP32_LOCK:
        ESP32_DEVICES_FILE.write_text(json.dumps(devices, indent=2))

# ─── CONVERSATION HISTORY & DEVICE STATUS ──────────────────────────────────────
conversation_store = {}
device_last_seen = {}

def get_history(session_id):
    return conversation_store.get(session_id, [])

def add_to_history(session_id, role, content):
    if session_id not in conversation_store:
        conversation_store[session_id] = []
    conversation_store[session_id].append({"role": role, "content": content})
    # Keep last 20 messages to avoid token overflow
    if len(conversation_store[session_id]) > 20:
        conversation_store[session_id] = conversation_store[session_id][-20:]

# ─── DECORATORS ───────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            return jsonify({"error": "Not authenticated"}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("role") != "admin":
            return jsonify({"error": "Unauthorized"}), 403
        return f(*args, **kwargs)
    return decorated_function

# ─── ROUTES: AUTH ─────────────────────────────────────────────────────────────
@app.route("/")
def index():
    if "username" not in session:
        return redirect(url_for("login"))
    return render_template("index.html", username=session["username"], name=session["name"])

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if request.method == "GET":
        return render_template("login.html")
    
    try:
        data = request.get_json() or request.form
        username = data.get("username", "").strip()
        password = data.get("password", "")
        
        users = load_users()
        user = users.get(username)
        
        if user and check_password_hash(user["password"], password):
            session["username"] = username
            session["name"] = user["name"]
            session["role"] = user["role"]
            session["session_id"] = str(uuid.uuid4())
            return jsonify({"success": True, "name": user["name"]})
        
        return jsonify({"success": False, "error": "Invalid username or password"}), 401
    except Exception as e:
        return jsonify({"success": False, "error": "Internal server error"}), 500

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/api/me")
@login_required
def me():
    return jsonify({"username": session["username"], "name": session["name"], "role": session.get("role")})

# ─── ROUTES: ADMIN ────────────────────────────────────────────────────────────
@app.route("/api/admin/users", methods=["GET"])
@admin_required
def get_users():
    try:
        users = load_users()
        return jsonify([{"username": k, "name": v["name"], "role": v["role"]} for k, v in users.items()])
    except Exception:
        return jsonify({"error": "Failed to load users"}), 500

@app.route("/api/admin/users", methods=["POST"])
@admin_required
def create_user():
    try:
        data = request.get_json()
        users = load_users()
        username = data["username"].strip()
        if username in users:
            return jsonify({"error": "User already exists"}), 400
        users[username] = {
            "password": generate_password_hash(data["password"]),
            "name": data["name"],
            "role": data.get("role", "student")
        }
        save_users(users)
        return jsonify({"success": True})
    except Exception:
        return jsonify({"error": "Internal error"}), 500

@app.route("/api/admin/users/<username>", methods=["DELETE"])
@admin_required
def delete_user(username):
    try:
        users = load_users()
        if username not in users:
            return jsonify({"error": "User not found"}), 404
        del users[username]
        save_users(users)
        return jsonify({"success": True})
    except Exception:
        return jsonify({"error": "Internal error"}), 500

@app.route("/api/admin/devices", methods=["GET"])
@admin_required
def get_devices():
    try:
        users = load_users()
        devices = []
        now = time.time()
        for uname, udata in users.items():
            if "device_token" in udata:
                last_seen = device_last_seen.get(uname, 0)
                status = "online" if (now - last_seen) < 90 else "offline"
                devices.append({
                    "username": uname,
                    "name": udata["name"],
                    "status": status,
                    "last_seen_ago": int(now - last_seen) if last_seen else -1
                })
        return jsonify(devices)
    except Exception:
        return jsonify({"error": "Internal error"}), 500

# ─── ROUTES: CHAT ─────────────────────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
@limiter.limit("20 per minute")
def chat():
    # Accept both session-based (web) and token-based (ESP32) auth
    username = session.get("username")
    session_id = session.get("session_id", "esp32-default")

    # ESP32 auth via header
    esp_token = request.headers.get("X-Device-Token")
    if not username and esp_token:
        users = load_users()
        for uname, udata in users.items():
            if udata.get("device_token") == esp_token:
                username = uname
                session_id = f"esp32-{uname}"
                break

    if not username:
        return jsonify({"error": "Not authenticated"}), 401

    device_last_seen[username] = time.time()

    data = request.get_json()
    user_text = data.get("text", "").strip()
    want_audio = data.get("audio", False)

    if not user_text:
        return jsonify({"error": "No text provided"}), 400

    # ── Call OpenRouter ──
    history = get_history(session_id)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [{"role": "user", "content": user_text}]

    ai_text = None
    # Retry logic for OpenRouter
    for attempt in range(3):
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://studybuddy.local",
                    "X-Title": "StudyBuddy"
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": messages,
                    "max_tokens": 300,
                    "temperature": 0.7
                },
                timeout=15
            )
            resp.raise_for_status()
            ai_text = resp.json()["choices"][0]["message"]["content"].strip()
            break
        except requests.exceptions.Timeout:
            if attempt == 2:
                return jsonify({"error": "AI service timeout. Please try again later."}), 504
            time.sleep(2 ** attempt)
        except Exception as e:
            if attempt == 2:
                return jsonify({"error": "AI service unavailable. Please try again later."}), 502
            time.sleep(2 ** attempt)

    if not ai_text:
        return jsonify({"error": "Failed to generate AI response."}), 500

    # Save to history
    add_to_history(session_id, "user", user_text)
    add_to_history(session_id, "assistant", ai_text)

    result = {"text": ai_text}

    # ── Generate TTS audio if requested ──
    if want_audio and tts_model:
        try:
            audio_filename = f"{uuid.uuid4().hex}.wav"
            audio_path = AUDIO_DIR / audio_filename
            tts_model.tts_to_file(text=ai_text, file_path=str(audio_path))
            result["audio_url"] = f"/static/audio/{audio_filename}"
        except Exception as e:
            result["audio_error"] = "Failed to generate audio. Returning text only."

    return jsonify(result)

# ─── ROUTES: ESP32 AUDIO DOWNLOAD ─────────────────────────────────────────────
@app.route("/api/tts", methods=["POST"])
def tts_only():
    """Standalone TTS endpoint — ESP32 can call this to convert any text to audio"""
    try:
        data = request.get_json()
        text = data.get("text", "").strip()
        if not text:
            return jsonify({"error": "No text"}), 400
        if not tts_model:
            return jsonify({"error": "TTS not available"}), 503
        audio_filename = f"{uuid.uuid4().hex}.wav"
        audio_path = AUDIO_DIR / audio_filename
        tts_model.tts_to_file(text=text, file_path=str(audio_path))
        return send_file(str(audio_path), mimetype="audio/wav")
    except Exception as e:
        return jsonify({"error": "TTS conversion failed"}), 500

# ─── ROUTES: ESP32 DEVICE TOKEN ──────────────────────────────────────────────
@app.route("/api/device/register", methods=["POST"])
@limiter.limit("5 per minute")
def register_device():
    """Generate a persistent device token for an ESP32"""
    try:
        data = request.get_json()
        username = data.get("username")
        password = data.get("password")
        users = load_users()
        user = users.get(username)
        if not user or not check_password_hash(user["password"], password):
            return jsonify({"error": "Invalid credentials"}), 401
        token = uuid.uuid4().hex
        users[username]["device_token"] = token
        save_users(users)
        return jsonify({"token": token, "name": user["name"]})
    except Exception as e:
        return jsonify({"error": "Internal error"}), 500

# ─── ROUTES: WIFI CONFIG ─────────────────────────────────────────────────────
WIFI_CONFIG_FILE = Path("wifi_config.json")
WIFI_LOCK = FileLock("wifi_config.json.lock")

def load_wifi_config():
    with WIFI_LOCK:
        if WIFI_CONFIG_FILE.exists():
            return json.loads(WIFI_CONFIG_FILE.read_text())
        return {"ssid": "", "password": "", "pending": False}

def save_wifi_config(ssid, password):
    with WIFI_LOCK:
        WIFI_CONFIG_FILE.write_text(json.dumps({
            "ssid": ssid,
            "password": password,
            "pending": True
        }))

@app.route("/wifi")
@login_required
def wifi_page():
    return render_template("wifi.html",
        username=session["username"],
        name=session["name"]
    )

@app.route("/api/wifi/config", methods=["GET"])
def get_wifi_config():
    try:
        esp_token = request.headers.get("X-Device-Token")
        username  = session.get("username")
        if not username and esp_token:
            users = load_users()
            for uname, udata in users.items():
                if udata.get("device_token") == esp_token:
                    username = uname
                    break
        if not username:
            return jsonify({"error": "Not authenticated"}), 401

        device_last_seen[username] = time.time()

        config = load_wifi_config()
        if config.get("pending"):
            config["pending"] = False
            with WIFI_LOCK:
                WIFI_CONFIG_FILE.write_text(json.dumps(config))
            return jsonify({"new_wifi": True, "ssid": config["ssid"], "password": config["password"]})
        return jsonify({"new_wifi": False})
    except Exception:
        return jsonify({"error": "Internal error"}), 500

@app.route("/api/wifi/config", methods=["POST"])
@login_required
def set_wifi_config():
    try:
        data = request.get_json()
        ssid     = data.get("ssid", "").strip()
        password = data.get("password", "")
        if not ssid:
            return jsonify({"error": "SSID cannot be empty"}), 400
        save_wifi_config(ssid, password)
        return jsonify({"success": True, "message": f"WiFi '{ssid}' saved. ESP32 will connect on next check."})
    except Exception:
        return jsonify({"error": "Internal error"}), 500

@app.route("/api/wifi/status", methods=["GET"])
@login_required
def wifi_status():
    try:
        config = load_wifi_config()
        return jsonify({"ssid": config.get("ssid", ""), "pending": config.get("pending", False)})
    except Exception:
        return jsonify({"error": "Internal error"}), 500

# ─── ROUTES: ESP32 BLE PROVISIONING & HEARTBEAT ─────────────────────────────
@app.route("/api/esp32/heartbeat", methods=["POST"])
def esp32_heartbeat():
    try:
        data = request.get_json()
        device_id = data.get("device_id")
        if not device_id:
            return jsonify({"error": "No device_id"}), 400
        
        devices = load_esp32_devices()
        if device_id not in devices:
            devices[device_id] = {}
            
        devices[device_id].update({
            "ip": data.get("ip", ""),
            "ssid": data.get("ssid", ""),
            "status": data.get("status", "online"),
            "signal": data.get("signal", 0),
            "last_seen": time.time(),
            "connected": True
        })
        
        # Check for pending commands
        cmd = devices[device_id].get("pending_command", "none")
        if cmd != "none":
            devices[device_id]["pending_command"] = "none" # Clear it
            
        save_esp32_devices(devices)
        return jsonify({"command": cmd})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/esp32/devices", methods=["GET"])
@admin_required
def esp32_devices_list():
    try:
        devices = load_esp32_devices()
        now = time.time()
        for d_id, d_data in devices.items():
            if now - d_data.get("last_seen", 0) > 60:
                d_data["status"] = "offline"
                d_data["connected"] = False
        return jsonify(devices)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/esp32/disconnect/<device_id>", methods=["POST"])
@admin_required
def esp32_disconnect(device_id):
    try:
        devices = load_esp32_devices()
        if device_id in devices:
            devices[device_id]["pending_command"] = "disconnect"
            save_esp32_devices(devices)
            return jsonify({"success": True})
        return jsonify({"error": "Device not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/esp32/commands", methods=["GET"])
def esp32_commands():
    try:
        device_id = request.args.get("device_id")
        if not device_id:
            return jsonify({"error": "No device_id"}), 400
            
        devices = load_esp32_devices()
        if device_id in devices:
            cmd = devices[device_id].get("pending_command", "none")
            if cmd != "none":
                devices[device_id]["pending_command"] = "none"
                save_esp32_devices(devices)
            return jsonify({"command": cmd})
        return jsonify({"command": "none"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── ROUTES: ESP32 SPEECH TO TEXT ────────────────────────────────────────────
@app.route("/api/stt", methods=["POST"])
def speech_to_text():
    try:
        esp_token = request.headers.get("X-Device-Token")
        username  = session.get("username")

        if not username and esp_token:
            users = load_users()
            for uname, udata in users.items():
                if udata.get("device_token") == esp_token:
                    username = uname
                    break

        if not username:
            return jsonify({"error": "Not authenticated"}), 401

        device_last_seen[username] = time.time()

        wav_data = request.data
        if not wav_data or len(wav_data) < 44:
            return jsonify({"error": "No audio received"}), 400

        recognizer = sr.Recognizer()
        audio_file = io.BytesIO(wav_data)
        with sr.AudioFile(audio_file) as source:
            audio = recognizer.record(source)
            
        text = recognizer.recognize_google(audio)
        print(f"[STT] Transcribed: '{text}'")
        return jsonify({"text": text})
    except sr.UnknownValueError:
        return jsonify({"text": "", "error": "Unclear audio. Please try again."})
    except sr.RequestError as e:
        return jsonify({"text": "", "error": "Speech service unavailable."}), 503
    except Exception as e:
        return jsonify({"error": "STT processing failed"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
