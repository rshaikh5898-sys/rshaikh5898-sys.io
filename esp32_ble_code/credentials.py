import ujson
import uos

CREDENTIALS_FILE = "credentials.json"

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
