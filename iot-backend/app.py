from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import paho.mqtt.client as mqtt
import json
import threading
import time
import cv2
import os
from datetime import datetime

# ===== CẤU HÌNH =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
TEMPLATE_FOLDER = os.path.join(BASE_DIR, 'templates')

if not os.path.exists(STATIC_FOLDER): os.makedirs(STATIC_FOLDER)

app = Flask(__name__, static_folder=STATIC_FOLDER, template_folder=TEMPLATE_FOLDER)
CORS(app)

MQTT_HOST = "9193406657be42b498e012fd208f4cf2.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "kahua269"
MQTT_PASS = "Haumeo2609"
MQTT_TOPIC_CONTROL = "iot/control"

CAMERA_INDEX = 0 
SAFE_PINS_POOL = [4, 5, 13, 14, 16, 17, 18, 19, 21, 22, 25, 26, 27, 32, 33]

devices = [
    {
        "id": 1, "name": "Đèn Phòng Khách", "pin": 23, "status": "OFF", 
        "temp": None, "pir": 0, "images": [], 
        "last_on_time": None, "total_on_time": 0, "usage_logs": []
    }
]

history_log = {}
notifications = []
temp_history_5m = []
temp_history_1h = []
last_update_5m = 0
last_update_1h = 0

def get_next_free_pin():
    used_pins = [d["pin"] for d in devices]
    for pin in SAFE_PINS_POOL:
        if pin not in used_pins: return pin
    return None 

def create_notification(dev_id, dev_name, action, user):
    now_str = datetime.now().strftime("%H:%M:%S %d/%m")
    notifications.insert(0, {"id": dev_id, "name": dev_name, "action": action, "time": now_str, "user": user, "ts": time.time()})
    if len(notifications) > 20: notifications.pop()

def add_history(dev_id, action, user="System"):
    if dev_id not in history_log: history_log[dev_id] = []
    history_log[dev_id].insert(0, {"time": datetime.now().strftime("%H:%M:%S %d/%m"), "action": action, "user": user})
    if len(history_log[dev_id]) > 6: history_log[dev_id] = history_log[dev_id][:6]

# --- MQTT CLIENT ---
mqtt_client = mqtt.Client()

def on_connect(client, userdata, flags, rc, properties=None):
    print("MQTT Connected")
    client.subscribe("iot/devices/state")

def on_message(client, userdata, msg):
    global last_update_5m, last_update_1h
    try:
        data = json.loads(msg.payload.decode())
        for d in devices:
            if d["id"] == 1:
                if "pir" in data: d["pir"] = data["pir"]
                if "temp" in data: 
                    try:
                        val = float(data["temp"])
                        if val > 0: # SỬA LỖI: Chỉ cập nhật nếu nhiệt độ > 0
                            d["temp"] = data["temp"]
                            current_time = time.time()
                            if current_time - last_update_5m >= 300 or len(temp_history_5m) == 0:
                                temp_history_5m.append({"time": datetime.now().strftime("%H:%M"), "temp": val})
                                if len(temp_history_5m) > 30: temp_history_5m.pop(0)
                                last_update_5m = current_time
                            if current_time - last_update_1h >= 3600 or len(temp_history_1h) == 0:
                                temp_history_1h.append({"time": datetime.now().strftime("%Hh"), "temp": val})
                                if len(temp_history_1h) > 30: temp_history_1h.pop(0)
                                last_update_1h = current_time
                    except: pass
                break
    except: pass

def mqtt_loop():
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
    mqtt_client.tls_set()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    while True:
        try:
            mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
            mqtt_client.loop_forever()
        except: time.sleep(5)

# --- ROUTES ---
@app.route("/")
def root():
    return jsonify({"status": "ok"})

@app.route("/api/upload-capture", methods=["POST"])
def upload_capture():
    if 'file' not in request.files: return jsonify({"error": "No file"}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({"error": "No filename"}), 400
    if file:
        filename = file.filename
        filepath = os.path.join(STATIC_FOLDER, filename)
        file.save(filepath)
        ts = datetime.now().strftime("%H:%M:%S %d/%m")
        for d in devices:
            if d["id"] == 1:
                d["images"].insert(0, {"filename": filename, "time": ts})
                while len(d["images"]) > 5:
                    old = d["images"].pop()
                    try: os.remove(os.path.join(STATIC_FOLDER, old["filename"]))
                    except: pass
                break
        add_history(1, "CHỤP ẢNH", "System")
        create_notification(1, "Cảm biến", "CHỤP ẢNH", "System")
        return jsonify({"ok": True, "path": filename})

@app.route("/api/devices", methods=["GET", "POST"])
def handle_devices():
    if request.method == "GET": return jsonify(devices)
    if request.method == "POST":
        next_pin = get_next_free_pin()
        if next_pin is None: return jsonify({"error": "Hết chân GPIO"}), 400
        data = request.json
        new_dev = {"id": (max(d["id"] for d in devices) + 1) if devices else 1, "name": data.get("name"), "pin": next_pin, "status": "OFF", "temp": None, "pir": 0, "images": [], "last_on_time": None, "total_on_time": 0, "usage_logs": []}
        devices.append(new_dev)
        create_notification(new_dev["id"], new_dev["name"], "THÊM THIẾT BỊ", "User Web")
        return jsonify(new_dev)

@app.route("/api/devices/<int:did>", methods=["PUT"])
def rename_device(did):
    data = request.json
    found = next((d for d in devices if d["id"] == did), None)
    if not found: return jsonify({"error": "404"}), 404
    old_name = found["name"]
    found["name"] = data.get("name")
    create_notification(did, found["name"], f"ĐỔI TÊN TỪ '{old_name}'", "User Web")
    return jsonify({"ok": True})

@app.route("/api/devices/<int:did>/<action>", methods=["POST"])
def control(did, action):
    action = action.upper()
    found = next((d for d in devices if d["id"] == did), None)
    if not found: return jsonify({"error": "404"}), 404
    if action == "ON" and found["status"] == "OFF": found["last_on_time"] = time.time()
    elif action == "OFF" and found["status"] == "ON":
        if found["last_on_time"]:
            duration = time.time() - found["last_on_time"]
            found["usage_logs"].insert(0, {"start": datetime.fromtimestamp(found["last_on_time"]).strftime("%H:%M:%S %d/%m"), "end": datetime.now().strftime("%H:%M:%S %d/%m"), "duration": duration})
            if len(found["usage_logs"]) > 10: found["usage_logs"].pop()
            found["total_on_time"] += duration
            found["last_on_time"] = None
    found["status"] = action
    payload = json.dumps({"pin": found["pin"], "status": action})
    mqtt_client.publish(MQTT_TOPIC_CONTROL, payload, qos=1)
    add_history(did, action, "User Web")
    create_notification(did, found["name"], action, "User Web")
    return jsonify({"ok": True})

@app.route("/api/devices/<int:did>", methods=["DELETE"])
def delete_dev(did):
    global devices
    if did == 1: return jsonify({"error": "Không thể xóa thiết bị gốc"}), 400
    found = next((d for d in devices if d["id"] == did), None)
    if found:
        devices = [d for d in devices if d["id"] != did]
        create_notification(did, found["name"], "XÓA THIẾT BỊ", "User Web")
    return jsonify({"ok": True})

@app.route("/api/devices/<int:did>/history", methods=["GET"])
def get_hist(did): return jsonify(history_log.get(did, []))

@app.route("/api/notifications", methods=["GET"])
def get_notif(): return jsonify(notifications)

@app.route("/api/stats", methods=["GET"])
def get_stats(): return jsonify({"chart_5m": temp_history_5m, "chart_1h": temp_history_1h, "devices": devices})

if __name__ == "__main__":
    t = threading.Thread(target=mqtt_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000, debug=False)

