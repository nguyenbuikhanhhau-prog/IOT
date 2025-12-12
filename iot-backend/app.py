from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import paho.mqtt.client as mqtt
import json
import threading
import time
import os
import requests
from datetime import datetime
from flask_bcrypt import Bcrypt # Thêm thư viện này
from dotenv import load_dotenv # Thêm thư viện này
import smtplib # Thêm thư viện này để gửi mail
from email.mime.text import MIMEText # Thêm thư viện này
import string
import random
import time

load_dotenv() # Tải biến môi trường từ file .env
# Biến lưu mốc thời gian xóa thông báo
dropdown_last_clear = 0

# ==========================================
# 1. CẤU HÌNH HỆ THỐNG
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FOLDER = os.path.join(BASE_DIR, "static")
CAPTURE_FOLDER = os.path.join(STATIC_FOLDER, "captures")
TEMPLATE_FOLDER = os.path.join(BASE_DIR, "templates")

if not os.path.exists(STATIC_FOLDER): os.makedirs(STATIC_FOLDER)
if not os.path.exists(CAPTURE_FOLDER): os.makedirs(CAPTURE_FOLDER)

app = Flask(__name__, static_folder=STATIC_FOLDER, template_folder=TEMPLATE_FOLDER)
CORS(app)
bcrypt = Bcrypt(app) # Khởi tạo Bcrypt

# ==========================================
# CẤU HÌNH EMAIL TỪ .ENV
# ==========================================
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))

# ==========================================
# 3. QUẢN LÝ NGƯỜI DÙNG (DATABASE MOCKUP)
# ==========================================
# Dữ liệu người dùng mẫu (Dùng list để mô phỏng Database)
# Thêm người dùng mặc định: email="admin@iot.com", pass="admin"
current_user = None # Biến để lưu trạng thái đăng nhập đơn giản

# ==========================================
# LOGIC HỖ TRỢ (GỬI EMAIL)
# ==========================================    
def generate_random_password(length=8):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for i in range(length))

def send_password_email(recipient_email, new_password):
    try:
        print("📨 Start send mail to:", recipient_email)

        msg = MIMEText(
            f"Mật khẩu mới của bạn là: {new_password}\n\nVui lòng đăng nhập và đổi mật khẩu.",
            "plain",
            "utf-8"
        )
        msg["Subject"] = "Mật khẩu mới cho hệ thống IOT"
        msg["From"] = EMAIL_USER
        msg["To"] = recipient_email

        print("🔐 Connecting SMTP...")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_USER, recipient_email, msg.as_string())

        print("✅ Email sent OK")
        return True

    except Exception as e:
        print("❌ SMTP ERROR >>>", repr(e))
        return False

# =========================================
# 6. API FLASK (THÊM CÁC API ĐĂNG NHẬP/ĐĂNG KÝ)
# ==========================================

# THAY THẾ route "/" CŨ bằng route có kiểm tra đăng nhập
@app.route("/")
def index():
    if current_user:
        return render_template("index.html")
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def login():
    global current_user
    data = request.json
    email = data.get('email')
    password = data.get('password')

    user = next((u for u in users if u["email"] == email), None)
    
    if user and bcrypt.check_password_hash(user["password"], password):
        current_user = user # Thiết lập trạng thái đăng nhập
        add_notification("Hệ thống", f"Người dùng {email} đã đăng nhập", "System")
        return jsonify({"success": True, "message": "Đăng nhập thành công!"})
    
    return jsonify({"success": False, "message": "Email hoặc mật khẩu không đúng."}), 401

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    if next((u for u in users if u["email"] == email), None):
        return jsonify({"success": False, "message": "Email đã tồn tại."}), 400

    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    new_user = {"id": len(users) + 1, "email": email, "password": hashed_password}
    users.append(new_user)
    add_notification("Hệ thống", f"Tạo tài khoản mới: {email}", "System")
    return jsonify({"success": True, "message": "Đăng ký thành công! Vui lòng đăng nhập."})

@app.route("/forgot_password", methods=["POST"])
def forgot_password():
    data = request.json
    email = data.get('email')
    user = next((u for u in users if u["email"] == email), None)
    
    if user:
        new_password = generate_random_password()
        
        if send_password_email(email, new_password):
            # Cập nhật mật khẩu mới (đã mã hóa) vào Database (Mockup)
            user["password"] = bcrypt.generate_password_hash(new_password).decode('utf-8')
            add_notification("Hệ thống", f"Gửi mật khẩu mới cho {email}", "System")
            return jsonify({"success": True, "message": "Mật khẩu mới đã được gửi về email của bạn."})
        else:
            return jsonify({"success": False, "message": "Lỗi hệ thống khi gửi email."}), 500
    
    # Luôn trả về thông báo chung để tránh tiết lộ email nào tồn tại
    return jsonify({"success": True, "message": "Nếu email tồn tại, mật khẩu mới sẽ được gửi đi."})

@app.route("/logout", methods=["POST"])
def logout():
    global current_user
    if current_user:
        current_user = None
        return jsonify({"success": True, "message": "Đã đăng xuất"})
    return jsonify({"success": False}), 400

# THÊM HÀM NÀY ĐỂ KIỂM TRA ĐĂNG NHẬP CHO FRONTEND (Optional)
@app.route("/api/user_status", methods=["GET"])
def get_user_status():
    if current_user:
        return jsonify({"logged_in": True, "email": current_user['email']})
    return jsonify({"logged_in": False})

# ==========================================
# 2. CẤU HÌNH MQTT
# ==========================================
MQTT_HOST = "9193406657be42b498e012fd208f4cf2.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "kahua269"
MQTT_PASS = "Haumeo2609"

TOPIC_CONTROL = "iot/control"
TOPIC_SENSOR  = "iot/devices/state"
TOPIC_CAPTURE = "iot/devices/capture"
CAMERA_SERVICE_URL = "http://localhost:5001"

# ==========================================
# 3. QUẢN LÝ THIẾT BỊ
# ==========================================
MASTER_PIN_POOL = [16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33]

output_devices = [
    {
        "id": 1, 
        "name": "Đèn Vườn (Mặc định)", 
        "pin": 13, 
        "status": "OFF", 
        "last_on_time": None, "total_on_time": 0, "usage_logs": []
    }
]

def get_available_pins():
    used_pins = [d['pin'] for d in output_devices if d['pin'] is not None]
    available = [p for p in MASTER_PIN_POOL if p not in used_pins]
    available.sort()
    return available

def rebalance_device_ids():
    for index, device in enumerate(output_devices):
        new_id = index + 1
        if device['id'] != new_id:
            device['id'] = new_id

sensor_state = {
    "temp": "--", "hum": "--", "pir": 0, "gas": "--", 
    "temp2": "--", "hum2": "--", "images": []
}

notifications = []
temp_history_5m = []; temp_history_1h = []; last_chart_update = 0
last_trigger_time = 0 

# ==========================================
# 4. LOGIC XỬ LÝ (QUAN TRỌNG: THÊM 'ts')
# ==========================================
def add_notification(name, action, user="System"):
    ts_str = datetime.now().strftime("%H:%M:%S %d/%m")
    notifications.insert(0, {
        "id": int(time.time()*1000), 
        "name": name, 
        "action": action, 
        "time": ts_str, 
        "user": user,
        "ts": time.time()  # <--- QUAN TRỌNG: Dùng để lọc tin nhắn mới/cũ
    })
    if len(notifications) > 50: notifications.pop()

def process_camera_capture(trigger_source="AUTO"):
    try:
        res = requests.get(f"{CAMERA_SERVICE_URL}/snapshot", timeout=5)
        if res.status_code == 200:
            filename = f"capture_{int(time.time())}.jpg"
            path = os.path.join(CAPTURE_FOLDER, filename)
            with open(path, 'wb') as f: f.write(res.content)
            
            sensor_state["images"].insert(0, {"filename": f"captures/{filename}", "time": datetime.now().strftime("%H:%M:%S %d/%m")})
            if len(sensor_state["images"]) > 10:
                old = sensor_state["images"].pop()
                try: os.remove(os.path.join(STATIC_FOLDER, old["filename"]))
                except: pass
            
            noti_msg = "PHÁT HIỆN NGƯỜI (Đã chụp ảnh)" if trigger_source == "AUTO" else "CHỤP THỦ CÔNG"
            add_notification("Camera AI", noti_msg, "System" if trigger_source == "AUTO" else "User")
            print(f"📸 Đã chụp: {filename}")

        elif res.status_code == 409:
            print("⚠️ Camera đang Stream, chỉ gửi thông báo.")
            add_notification("Camera AI", "PHÁT HIỆN NGƯỜI (Đang xem Live)", "System")
    except Exception as e:
        print(f"❌ Lỗi Camera: {e}")

# ==========================================
# 5. XỬ LÝ MQTT
# ==========================================
def on_mqtt_connect(client, userdata, flags, rc):
    print(f"✅ MQTT Connected: {rc}")
    client.subscribe([(TOPIC_SENSOR, 0), (TOPIC_CAPTURE, 0)])

def on_mqtt_message(client, userdata, msg):
    global last_chart_update, last_trigger_time
    try:
        payload = msg.payload.decode()
        current_time = time.time()

        if msg.topic == TOPIC_CAPTURE:
            if current_time - last_trigger_time > 3:
                threading.Thread(target=process_camera_capture, args=("AUTO",)).start()
                last_trigger_time = current_time 
            return

        if msg.topic == TOPIC_SENSOR:
            data = json.loads(payload)
            if "temp" in data: sensor_state["temp"] = float(data["temp"])
            if "hum" in data: sensor_state["hum"] = float(data["hum"])
            if "gas" in data: sensor_state["gas"] = int(data["gas"])
            if "temp2" in data: sensor_state["temp2"] = float(data["temp2"])
            if "hum2" in data: sensor_state["hum2"] = float(data["hum2"])
            
            if "pir" in data:
                new_pir = int(data["pir"])
                if sensor_state["pir"] == 0 and new_pir == 1:
                    if current_time - last_trigger_time > 3:
                        print("🚨 CÓ NGƯỜI! Kích hoạt Camera...")
                        threading.Thread(target=process_camera_capture, args=("AUTO",)).start()
                        last_trigger_time = current_time 
                sensor_state["pir"] = new_pir

            curr = time.time()
            if isinstance(sensor_state["temp"], (int, float)):
                if curr - last_chart_update > 300:
                    t_str = datetime.now().strftime("%H:%M")
                    temp_history_5m.append({"time": t_str, "temp": sensor_state["temp"]})
                    temp_history_1h.append({"time": datetime.now().strftime("%Hh"), "temp": sensor_state["temp"]})
                    if len(temp_history_5m) > 20: temp_history_5m.pop(0)
                    if len(temp_history_1h) > 24: temp_history_1h.pop(0)
                    last_chart_update = curr
    except Exception as e: print(f"MQTT Error: {e}")

# ==========================================
# 6. API FLASK
# ==========================================
@app.route("/api/devices", methods=["GET"])
def get_devices():
    resp = json.loads(json.dumps(output_devices))
    if resp: resp[0].update(sensor_state)
    return jsonify(resp)

@app.route("/api/devices", methods=["POST"])
def add_device():
    available = get_available_pins()
    if not available: return jsonify({"success": False, "message": "Hết chân GPIO!"}), 400
    assigned_pin = available[0]
    data = request.json
    new_id = len(output_devices) + 1
    new_dev = {"id": new_id, "name": data.get("name", f"Thiết bị mới ({assigned_pin})"), "pin": assigned_pin, "status": "OFF", "last_on_time": None, "total_on_time": 0, "usage_logs": []}
    output_devices.append(new_dev)
    add_notification("Hệ thống", f"Thêm {new_dev['name']} - GPIO {assigned_pin}", "Admin")
    return jsonify({"success": True, "device": new_dev})

@app.route("/api/devices/<int:dev_id>", methods=["DELETE"])
def delete_device(dev_id):
    global output_devices
    if dev_id == 1: return jsonify({"success": False, "message": "Cấm xóa thiết bị gốc"}), 400
    dev = next((d for d in output_devices if d["id"] == dev_id), None)
    if dev:
        if dev['pin']: mqtt_client.publish(TOPIC_CONTROL, json.dumps({"pin": dev['pin'], "status": "OFF"}))
        output_devices = [d for d in output_devices if d['id'] != dev_id]
        rebalance_device_ids()
        add_notification("Hệ thống", f"Xóa {dev['name']}", "Admin")
        return jsonify({"success": True})
    return jsonify({"success": False}), 404

@app.route("/api/devices/<int:dev_id>/<action>", methods=["POST"])
def control(dev_id, action):
    action = action.upper()
    dev = next((d for d in output_devices if d["id"] == dev_id), None)
    if dev:
        dev["status"] = action
        if dev["pin"]: mqtt_client.publish(TOPIC_CONTROL, json.dumps({"pin": dev["pin"], "status": action}))
        if action == "ON": dev["last_on_time"] = time.time()
        elif action == "OFF" and dev["last_on_time"]:
            dur = time.time() - dev["last_on_time"]
            dev["total_on_time"] += dur
            dev["usage_logs"].insert(0, {"start": datetime.fromtimestamp(dev["last_on_time"]).strftime("%H:%M:%S"), "end": datetime.now().strftime("%H:%M:%S"), "duration": dur})
            dev["last_on_time"] = None
        add_notification(dev["name"], action, "User")
        return jsonify({"success": True})
    return jsonify({"success": False}), 404

@app.route("/api/capture", methods=['POST'])
def manual_cap():
    threading.Thread(target=process_camera_capture, args=("MANUAL",)).start()
    return jsonify({"success": True})

# --- CÁC API THÔNG BÁO ---
@app.route("/api/notifications", methods=["GET"])
def get_all_notif():
    return jsonify(notifications)

@app.route("/api/notifications/dropdown", methods=["GET"])
def get_dropdown_notif():
    # Lọc các thông báo có 'ts' > thời gian xóa gần nhất
    filtered = [n for n in notifications if n.get('ts', 0) > dropdown_last_clear]
    return jsonify(filtered)

@app.route("/api/notifications/clear", methods=["POST"])
def clear_dropdown():
    global dropdown_last_clear
    dropdown_last_clear = time.time()
    return jsonify({"success": True})

@app.route("/api/devices/<int:dev_id>/history", methods=["GET"])
def get_device_history(dev_id):
    dev = next((d for d in output_devices if d["id"] == dev_id), None)
    if not dev: return jsonify([])
    device_history = [n for n in notifications if n['name'] == dev['name']]
    return jsonify(device_history)

@app.route("/api/stats", methods=["GET"])
def get_stats(): return jsonify({"chart_5m": temp_history_5m, "chart_1h": temp_history_1h})

# API Đổi Mật khẩu
@app.route("/change_password", methods=["POST"])
def change_password():
    if not current_user:
        return jsonify({"success": False, "message": "Yêu cầu đăng nhập."}), 403

    data = request.json
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    user = next((u for u in users if u["id"] == current_user["id"]), None)

    if not user:
        return jsonify({"success": False, "message": "Lỗi người dùng không tồn tại."}), 404

    # Kiểm tra mật khẩu cũ
    if not bcrypt.check_password_hash(user["password"], old_password):
        return jsonify({"success": False, "message": "Mật khẩu cũ không chính xác."}), 400

    # Cập nhật mật khẩu mới
    user["password"] = bcrypt.generate_password_hash(new_password).decode('utf-8')
    add_notification("Tài khoản", f"Người dùng {user['email']} đã đổi mật khẩu", "User")
    return jsonify({"success": True, "message": "Đổi mật khẩu thành công!"})

# API Lấy thông tin người dùng đang đăng nhập
@app.route("/api/user_info", methods=["GET"])
def get_user_info():
    if not current_user:
        return jsonify({"logged_in": False}), 401
    
    # Chỉ trả về ID và Email, không bao giờ trả về mật khẩu hash
    return jsonify({
        "logged_in": True,
        "email": current_user['email'],
        "id": current_user['id']
    })
# ==========================================
# 7. RUN
# ==========================================
mqtt_client = mqtt.Client()
def run_mqtt():
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
    mqtt_client.tls_set()
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message
    while True:
        try: mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60); mqtt_client.loop_forever()
        except: time.sleep(5)

hashed_password = bcrypt.generate_password_hash("admin").decode('utf-8')
users = [
    {"id": 1, "email": "admin@iot.com", "password": hashed_password}
]
current_user = None

if __name__ == '__main__':
    threading.Thread(target=run_mqtt, daemon=True).start()
    print("🚀 App running port 5000")

    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)




