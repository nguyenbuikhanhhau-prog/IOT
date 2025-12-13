from flask import Flask, jsonify, request, render_template, session
from datetime import timedelta, datetime
from flask_cors import CORS
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
import os, string, random, time
import threading
import sendgrid
from sendgrid.helpers.mail import Mail
import paho.mqtt.client as mqtt
import json
import requests

load_dotenv()

# ===============================
# 1. CẤU HÌNH HỆ THỐNG
# ===============================
MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = 8883
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")
MQTT_TOPIC = "iot/devices/state"
MQTT_CONTROL_TOPIC = "iot/control"
MQTT_CAPTURE_TOPIC = "iot/devices/capture"

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
EMAIL_USER = os.getenv("EMAIL_USER")
CAMERA_SERVICE_URL = "h https://flamelike-noninitially-adolfo.ngrok-free.dev"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "iot-secret-key")
app.permanent_session_lifetime = timedelta(hours=2)
CORS(app)
bcrypt = Bcrypt(app)

# ===============================
# 2. QUẢN LÝ KHO CHÂN GPIO
# ===============================
# Loại bỏ chân 4 (DHT11) và các chân Flash
SAFE_GPIO_POOL = [2, 5, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33]

output_devices = [
    {
        "id": 1,
        "name": "Đèn Onboard (Test)",
        "pin": 2, 
        "status": "OFF",
        "last_on_time": None,
        "total_on_time": 0,
        "usage_logs": []
    }
]

def init_pin_warehouse():
    used_pins = [d['pin'] for d in output_devices]
    for pin in used_pins:
        if pin in SAFE_GPIO_POOL:
            SAFE_GPIO_POOL.remove(pin)
    print(f"📦 Kho chân an toàn còn lại: {SAFE_GPIO_POOL}")

init_pin_warehouse() 

# ===============================
# 3. DỮ LIỆU & BIẾN PHỤ TRỢ
# ===============================
users = [
    {
        "id": 1,
        "email": "admin@iot.com",
        "password": bcrypt.generate_password_hash("admin").decode("utf-8")
    }
]
notifications = []
dropdown_last_clear = 0
latest_device_data = {} 
sensor_state = {"images": []} 
last_trigger_time = 0 

def add_notification(name, action, user="System"):
    ts_str = datetime.now().strftime("%H:%M:%S %d/%m")
    notifications.insert(0, {
        "id": int(time.time()*1000),
        "name": name,
        "action": action,
        "time": ts_str,
        "user": user,
        "ts": time.time()
    })
    if len(notifications) > 100: notifications.pop()

# ===============================
# 4. HÀM CHỤP ẢNH (GỌI SERVICE 5001)
# ===============================
def process_camera_capture(trigger_source="AUTO"):
    try:
        response = requests.get(f"{CAMERA_SERVICE_URL}/snapshot", timeout=3)
        if response.status_code == 200:
            filename = f"capture_{int(time.time())}.jpg"
            save_path = os.path.join("static", "captures", filename)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            with open(save_path, 'wb') as f: f.write(response.content)
            
            timestamp = datetime.now().strftime("%H:%M:%S %d/%m")
            sensor_state["images"].insert(0, {"filename": f"captures/{filename}", "time": timestamp})
            
            if len(sensor_state["images"]) > 10:
                old = sensor_state["images"].pop()
                try: os.remove(os.path.join("static", old["filename"]))
                except: pass

            msg = "PHÁT HIỆN NGƯỜI (Đã chụp ảnh)" if trigger_source == "AUTO" else "Đã chụp ảnh thủ công"
            add_notification("Camera AI", msg, "System" if trigger_source == "AUTO" else "User")
            print(f"📸 Đã lưu ảnh: {filename}")
            
    except Exception as e:
        print(f"❌ Lỗi Camera: {e}")

# ===============================
# 5. MQTT HANDLERS
# ===============================
def on_connect(client, userdata, flags, rc):
    print("🔌 MQTT connected:", rc)
    client.subscribe([(MQTT_TOPIC, 0), (MQTT_CAPTURE_TOPIC, 0)])

# Tìm hàm on_message cũ và thay bằng hàm này:
def on_message(client, userdata, msg):
    global latest_device_data, last_trigger_time
    try:
        payload = msg.payload.decode()
        print(f"📩 [DEBUG MQTT] Topic: {msg.topic} | Msg: {payload}") # <--- IN RA ĐỂ KIỂM TRA

        # 1. Xử lý lệnh chụp ảnh chủ động
        if msg.topic == MQTT_CAPTURE_TOPIC:
            print("📸 Nhận lệnh CAPTURE từ MQTT!")
            if time.time() - last_trigger_time > 5:
                threading.Thread(target=process_camera_capture, args=("AUTO",)).start()
                last_trigger_time = time.time()
            return
        # 2. Xử lý dữ liệu cảm biến (JSON)
        if msg.topic == MQTT_TOPIC:
            try:
                data = json.loads(payload)
                latest_device_data.update(data)
                
                # Check PIR
                if "pir" in data and int(data["pir"]) == 1:
                    print(f"🔥 [PIR = 1] Phát hiện người -> Gọi Camera...")
                    if time.time() - last_trigger_time > 5:
                        threading.Thread(target=process_camera_capture, args=("AUTO",)).start()
                        last_trigger_time = time.time()
                    else:
                        print("⏳ Đang chờ (Debounce 5s)...")
            except json.JSONDecodeError:
                print(f"⚠️ Lỗi: '{payload}' không phải là JSON hợp lệ!")

    except Exception as e:
        print("❌ Lỗi xử lý MQTT:", e)

# ===============================
# 6. API ROUTES
# ===============================
@app.route("/api/devices", methods=["POST"])
def add_device():
    if "user_id" not in session: return jsonify({"error": "Unauthorized"}), 401
    if not SAFE_GPIO_POOL: return jsonify({"success": False, "message": "Hết chân GPIO!"}), 400
    data = request.json
    name = data.get("name", "Thiết bị mới")
    assigned_pin = SAFE_GPIO_POOL.pop(0) 
    new_id = max(d["id"] for d in output_devices) + 1 if output_devices else 1
    new_device = {"id": new_id, "name": name, "pin": assigned_pin, "status": "OFF", "last_on_time": None, "total_on_time": 0, "usage_logs": []}
    output_devices.append(new_device)
    add_notification(name, f"ĐÃ THÊM (PIN {assigned_pin})", session.get("email"))
    return jsonify({"success": True, "device": new_device})

@app.route("/api/camera/upload", methods=["POST"])
def upload_camera():
    img = request.files.get("image")
    if not img:
        return {"success": False}, 400

    filename = f"capture_{int(time.time())}.jpg"
    path = os.path.join("static", "captures", filename)
    img.save(path)

    add_notification("Camera AI", "PHÁT HIỆN NGƯỜI")

    return {"success": True, "file": filename}

@app.route("/api/devices/<int:dev_id>", methods=["DELETE"])
def delete_device(dev_id):
    if "user_id" not in session: return jsonify({"error": "Unauthorized"}), 401
    global output_devices 
    dev = next((d for d in output_devices if d["id"] == dev_id), None)
    if dev:
        SAFE_GPIO_POOL.append(dev["pin"])
        SAFE_GPIO_POOL.sort() 
        mqtt_client.publish(MQTT_CONTROL_TOPIC, json.dumps({"pin": dev["pin"], "status": "OFF"}))
        output_devices = [d for d in output_devices if d["id"] != dev_id]
        add_notification(dev["name"], "ĐÃ XÓA", session.get("email"))
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Not found"}), 404

@app.route("/api/devices/<int:dev_id>/rename", methods=["POST"])
def rename_device(dev_id):
    if "user_id" not in session: return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    dev = next((d for d in output_devices if d["id"] == dev_id), None)
    if dev:
        old = dev["name"]
        dev["name"] = data.get("name")
        add_notification(old, f"ĐỔI TÊN -> {dev['name']}", session.get("email"))
        return jsonify({"success": True})
    return jsonify({"success": False}), 400

@app.route("/api/devices", methods=["GET"])
def get_devices_list():
    if "user_id" not in session: return jsonify({"error": "Unauthorized"}), 401
    resp = json.loads(json.dumps(output_devices))
    if len(resp) > 0:
        if latest_device_data: resp[0].update(latest_device_data)
        if sensor_state["images"]: resp[0]["images"] = sensor_state["images"]
    return jsonify(resp)

@app.route("/api/devices/<int:dev_id>/<action>", methods=["POST"])
def control_device(dev_id, action):
    if "user_id" not in session: return jsonify({"error": "Unauthorized"}), 401
    action = action.upper()
    dev = next((d for d in output_devices if d["id"] == dev_id), None)
    if dev:
        dev["status"] = action
        mqtt_client.publish(MQTT_CONTROL_TOPIC, json.dumps({"pin": dev["pin"], "status": action}))
        if action == "ON": dev["last_on_time"] = time.time()
        elif action == "OFF" and dev["last_on_time"]:
            dur = time.time() - dev["last_on_time"]
            dev["total_on_time"] += dur
            h, rem = divmod(dur, 3600)
            m, s = divmod(rem, 60)
            dev["usage_logs"].insert(0, {"start": datetime.fromtimestamp(dev["last_on_time"]).strftime("%H:%M:%S"), "end": datetime.now().strftime("%H:%M:%S"), "duration": dur, "duration_str": f"{int(h)}h {int(m)}m {int(s)}s"})
            dev["last_on_time"] = None
        add_notification(dev["name"], action, session.get("email"))
        return jsonify({"success": True})
    return jsonify({"success": False}), 404

@app.route("/api/capture", methods=['POST'])
def manual_capture():
    if "user_id" not in session: return jsonify({"error": "Unauthorized"}), 401
    threading.Thread(target=process_camera_capture, args=("MANUAL",)).start()
    return jsonify({"success": True})

# --- AUTH & SYSTEM ROUTES ---
@app.route("/")
def index():
    if "user_id" in session: return render_template("index.html")
    return render_template("login.html")

@app.route("/api/devices/<int:dev_id>/history", methods=["GET"])
def get_device_history(dev_id):
    if "user_id" not in session: return jsonify([]), 401
    dev = next((d for d in output_devices if d["id"] == dev_id), None)
    return jsonify([n for n in notifications if dev and n['name'] == dev['name']])

@app.route("/api/notifications", methods=["GET"])
def api_notifications():
    if "user_id" not in session: return jsonify([]), 401
    return jsonify(notifications)

@app.route("/api/notifications/dropdown", methods=["GET"])
def get_dropdown_notif():
    if "user_id" not in session: return jsonify([]), 401
    return jsonify([n for n in notifications if n.get('ts', 0) > dropdown_last_clear])

@app.route("/api/notifications/clear", methods=["POST"])
def clear_dropdown():
    global dropdown_last_clear
    dropdown_last_clear = time.time()
    return jsonify({"success": True})

@app.route("/api/stats")
def api_stats(): return jsonify({"chart_5m": [], "chart_1h": []})

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    users.append({"id": len(users)+1, "email": data["email"], "password": bcrypt.generate_password_hash(data["password"]).decode("utf-8")})
    return jsonify({"success": True})

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    user = next((u for u in users if u["email"] == data["email"]), None)
    if user and bcrypt.check_password_hash(user["password"], data["password"]):
        session["user_id"], session["email"] = user["id"], user["email"]
        return jsonify({"success": True})
    return jsonify({"success": False}), 401

@app.route("/logout", methods=["POST"])
def logout(): session.clear(); return jsonify({"success": True})

@app.route("/api/user_status")
def user_status(): return jsonify({"logged_in": "user_id" in session, "email": session.get("email")})

@app.route("/api/user_info", methods=["GET"])
def get_user_info():
    if "user_id" not in session: return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"id": session["user_id"], "email": session["email"]})

@app.route("/change_password", methods=["POST"])
def change_password():
    if "user_id" not in session: return jsonify({"success": False}), 403
    data = request.json
    user = next((u for u in users if u["id"] == session["user_id"]), None)
    if not bcrypt.check_password_hash(user["password"], data.get("old_password")): return jsonify({"success": False}), 400
    user["password"] = bcrypt.generate_password_hash(data.get("new_password")).decode("utf-8")
    return jsonify({"success": True})

# ===============================
# 7. RUN
# ===============================
mqtt_client = mqtt.Client()
def run_mqtt():
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS); mqtt_client.tls_set()
    mqtt_client.on_connect = on_connect; mqtt_client.on_message = on_message
    while True:
        try: mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60); mqtt_client.loop_forever()
        except: time.sleep(5)

threading.Thread(target=run_mqtt, daemon=True).start()
if not any(u['email'] == "admin@iot.com" for u in users):
    users.append({"id": 1, "email": "admin@iot.com", "password": bcrypt.generate_password_hash("admin").decode('utf-8')})

if __name__ == '__main__':
    print("🚀 Server running port 5000")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)



