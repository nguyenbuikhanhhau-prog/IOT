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

load_dotenv()

# ===============================
# CẤU HÌNH & KHỞI TẠO
# ===============================
MQTT_HOST = os.getenv("MQTT_HOST")
MQTT_PORT = 8883
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")
MQTT_TOPIC = "iot/devices/state"
MQTT_CONTROL_TOPIC = "iot/control"

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
EMAIL_USER = os.getenv("EMAIL_USER")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "iot-secret-key")
app.permanent_session_lifetime = timedelta(hours=2)
CORS(app)
bcrypt = Bcrypt(app)

# ===============================
# QUẢN LÝ KHO CHÂN GPIO
# ===============================
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
# DỮ LIỆU & BIẾN PHỤ TRỢ
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
    if len(notifications) > 100: notifications.pop() # Lưu 100 thông báo gần nhất

# ===============================
# MQTT HANDLERS
# ===============================
def on_connect(client, userdata, flags, rc):
    print("🔌 MQTT connected:", rc)
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    global latest_device_data
    try:
        payload = msg.payload.decode()
        data = json.loads(payload)
        latest_device_data = data
    except Exception as e:
        print("❌ MQTT parse error:", e)

# ===============================
# API ROUTES
# ===============================

@app.route("/api/devices", methods=["POST"])
def add_device():
    if "user_id" not in session: return jsonify({"error": "Unauthorized"}), 401
    
    if not SAFE_GPIO_POOL:
        return jsonify({"success": False, "message": "Hết chân GPIO khả dụng!"}), 400
        
    data = request.json
    name = data.get("name", "Thiết bị mới")
    assigned_pin = SAFE_GPIO_POOL.pop(0) 
    
    # ID tăng dần
    if output_devices:
        new_id = max(d["id"] for d in output_devices) + 1
    else:
        new_id = 1
    
    new_device = {
        "id": new_id,
        "name": name,
        "pin": assigned_pin,
        "status": "OFF",
        "last_on_time": None,
        "total_on_time": 0,
        "usage_logs": []
    }
    output_devices.append(new_device)
    add_notification(name, f"ĐÃ THÊM (PIN {assigned_pin})", session.get("email"))
    return jsonify({"success": True, "device": new_device})

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
    new_name = data.get("name")
    dev = next((d for d in output_devices if d["id"] == dev_id), None)
    if dev and new_name:
        old_name = dev["name"]
        dev["name"] = new_name
        add_notification(old_name, f"ĐỔI TÊN THÀNH: {new_name}", session.get("email"))
        return jsonify({"success": True})
    return jsonify({"success": False}), 400

@app.route("/api/devices", methods=["GET"])
def get_devices_list():
    if "user_id" not in session: return jsonify({"error": "Unauthorized"}), 401
    resp = json.loads(json.dumps(output_devices))
    if latest_device_data and len(resp) > 0:
        resp[0].update(latest_device_data)
    return jsonify(resp)

@app.route("/api/devices/<int:dev_id>/<action>", methods=["POST"])
def control_device(dev_id, action):
    if "user_id" not in session: return jsonify({"error": "Unauthorized"}), 401
    action = action.upper()
    dev = next((d for d in output_devices if d["id"] == dev_id), None)
    
    if dev:
        dev["status"] = action
        mqtt_client.publish(MQTT_CONTROL_TOPIC, json.dumps({"pin": dev["pin"], "status": action}))
        
        # Logic tính thời gian
        if action == "ON":
            dev["last_on_time"] = time.time()
        elif action == "OFF" and dev["last_on_time"]:
            dur = time.time() - dev["last_on_time"]
            dev["total_on_time"] += dur
            dev["usage_logs"].insert(0, {
                "start": datetime.fromtimestamp(dev["last_on_time"]).strftime("%H:%M:%S %d/%m"),
                "end": datetime.now().strftime("%H:%M:%S %d/%m"),
                "duration": dur
            })
            dev["last_on_time"] = None
            
        add_notification(dev["name"], action, session.get("email"))
        return jsonify({"success": True})
    return jsonify({"success": False}), 404

# --- API KHÁC ---
@app.route("/")
def index():
    if "user_id" in session: return render_template("index.html")
    return render_template("login.html")

@app.route("/api/devices/<int:dev_id>/history", methods=["GET"])
def get_device_history(dev_id):
    if "user_id" not in session: return jsonify([]), 401
    dev = next((d for d in output_devices if d["id"] == dev_id), None)
    if not dev: return jsonify([])
    # Lọc lịch sử từ danh sách notification
    device_history = [n for n in notifications if n['name'] == dev['name']]
    return jsonify(device_history)

@app.route("/api/notifications", methods=["GET"])
def api_notifications():
    if "user_id" not in session: return jsonify([]), 401
    # Trả về TOÀN BỘ thông báo (để hiển thị ở trang Nhật ký hệ thống)
    return jsonify(notifications)

@app.route("/api/notifications/dropdown", methods=["GET"])
def get_dropdown_notif():
    if "user_id" not in session: return jsonify([]), 401
    # Chỉ trả về thông báo MỚI (để hiển thị ở cái chuông)
    filtered = [n for n in notifications if n.get('ts', 0) > dropdown_last_clear]
    return jsonify(filtered)

@app.route("/api/notifications/clear", methods=["POST"])
def clear_dropdown():
    global dropdown_last_clear
    dropdown_last_clear = time.time()
    return jsonify({"success": True})

@app.route("/api/stats")
def api_stats():
    # Phần biểu đồ tạm để trống, logic này cần DB phức tạp hơn
    return jsonify({"chart_5m": [], "chart_1h": []})

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
        session["user_id"] = user["id"]
        session["email"] = user["email"]
        return jsonify({"success": True})
    return jsonify({"success": False}), 401

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route("/api/user_status")
def user_status():
    if "user_id" in session: return jsonify({"logged_in": True, "email": session["email"]})
    return jsonify({"logged_in": False})

@app.route("/api/user_info", methods=["GET"])
def get_user_info():
    if "user_id" not in session: return jsonify({"error": "Unauthorized"}), 401
    user = next((u for u in users if u["id"] == session["user_id"]), None)
    return jsonify({"id": user["id"], "email": user["email"]}) if user else (jsonify({"error": "Not found"}), 404)

@app.route("/change_password", methods=["POST"])
def change_password():
    if "user_id" not in session: return jsonify({"success": False}), 403
    data = request.json
    old_pw = data.get("old_password")
    new_pw = data.get("new_password")
    user = next((u for u in users if u["id"] == session["user_id"]), None)
    if not bcrypt.check_password_hash(user["password"], old_pw):
        return jsonify({"success": False, "message": "Sai mật khẩu cũ"}), 400
    user["password"] = bcrypt.generate_password_hash(new_pw).decode("utf-8")
    return jsonify({"success": True})

# ===============================
# RUN MQTT & APP
# ===============================
mqtt_client = mqtt.Client()

def run_mqtt():
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
    mqtt_client.tls_set()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    while True:
        try:
            print("🔄 Connecting MQTT...")
            mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
            mqtt_client.loop_forever()
        except Exception as e:
            print(f"⚠️ MQTT Error: {e}")
            time.sleep(5)

threading.Thread(target=run_mqtt, daemon=True).start()

# Tạo user mặc định
hashed_password = bcrypt.generate_password_hash("admin").decode('utf-8')
if not any(u['email'] == "admin@iot.com" for u in users):
    users.append({"id": 1, "email": "admin@iot.com", "password": hashed_password})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
