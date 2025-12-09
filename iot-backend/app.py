from flask import Flask, jsonify, request
from flask_cors import CORS
import paho.mqtt.client as mqtt
import json
import threading
import time
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ===== MQTT CONFIG =====
MQTT_HOST = "9193406657be42b498e012fd208f4cf2.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "kahua269"
MQTT_PASS = "Haumeo2609"
MQTT_TOPIC_PREFIX = "iot/devices"

# ===== DATABASE GIẢ LẬP (RAM) =====
# Lưu trữ thông tin thiết bị
devices = [
    {
        "id": 1,
        "name": "ESP32 Phong Khach",
        "status": "OFF",
        "temp": None,
        "pir": 0
    }
]

# Lưu trữ lịch sử hoạt động: { device_id: [ {time, action, user}, ... ] }
history_log = {}

# Hàm helper để ghi lịch sử
def add_history(device_id, action, user="Admin"):
    if device_id not in history_log:
        history_log[device_id] = []
    
    # Thêm vào đầu danh sách
    now = datetime.now().strftime("%H:%M:%S %d/%m")
    history_log[device_id].insert(0, {
        "time": now,
        "action": action,
        "user": user
    })
    
    # Chỉ giữ lại 6 log mới nhất (theo giao diện web của bạn)
    if len(history_log[device_id]) > 6:
        history_log[device_id] = history_log[device_id][:6]

mqtt_client = mqtt.Client()

# ================== MQTT CALLBACKS ==================
def on_mqtt_connect(client, userdata, flags, reason_code, properties=None):
    print("MQTT connected")
    client.subscribe(f"{MQTT_TOPIC_PREFIX}/+/state")

def on_mqtt_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        # Parse ID từ topic: iot/devices/1/state
        parts = msg.topic.split("/")
        if len(parts) >= 3:
            dev_id = int(parts[2])
            
            # Cập nhật data cho thiết bị tương ứng
            for d in devices:
                if d["id"] == dev_id:
                    if "temp" in data: d["temp"] = data["temp"]
                    if "pir" in data: d["pir"] = data["pir"]
                    # Cập nhật trạng thái thực tế từ thiết bị phản hồi
                    if "ctrl" in data: 
                        # Nếu trạng thái thay đổi so với lưu trữ thì ghi log (tùy chọn)
                        d["status"] = data["ctrl"]
                    break
    except Exception as e:
        print("MQTT Error:", e)

def mqtt_loop():
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
    mqtt_client.tls_set()
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message
    
    while True:
        try:
            mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
            mqtt_client.loop_forever()
        except:
            time.sleep(5)

# ================== API ENDPOINTS (ĐÃ BỔ SUNG) ==================

# 1. Lấy danh sách thiết bị
@app.route("/api/devices", methods=["GET"])
def get_devices():
    return jsonify(devices)

# 2. Thêm thiết bị mới (Frontend gọi cái này)
@app.route("/api/devices", methods=["POST"])
def add_device():
    data = request.json
    if not data or "name" not in data:
        return jsonify({"error": "Thiếu tên thiết bị"}), 400
    
    # Tạo ID mới (Max ID + 1)
    new_id = 1
    if len(devices) > 0:
        new_id = max(d["id"] for d in devices) + 1
        
    new_device = {
        "id": new_id,
        "name": data["name"],
        "status": "OFF",
        "temp": None,
        "pir": 0
    }
    devices.append(new_device)
    add_history(new_id, "CREATED", "System")
    return jsonify(new_device)

# 3. Xóa thiết bị (Frontend gọi cái này)
@app.route("/api/devices/<int:device_id>", methods=["DELETE"])
def delete_device(device_id):
    global devices
    devices = [d for d in devices if d["id"] != device_id]
    if device_id in history_log:
        del history_log[device_id]
    return jsonify({"ok": True})

# 4. Điều khiển thiết bị ON/OFF
@app.route("/api/devices/<int:device_id>/<action>", methods=["POST"])
def set_device(device_id, action):
    action = action.upper() # ON/OFF
    
    # Tìm thiết bị
    found = next((d for d in devices if d["id"] == device_id), None)
    if not found:
        return jsonify({"error": "Not found"}), 404
        
    # Cập nhật trạng thái
    found["status"] = action
    
    # Gửi lệnh MQTT xuống ESP32
    topic = f"{MQTT_TOPIC_PREFIX}/{device_id}/set"
    mqtt_client.publish(topic, action, qos=1)
    
    # Ghi log lịch sử
    add_history(device_id, action, "User Web")
    
    return jsonify({"ok": True})

# 5. Lấy lịch sử (Frontend gọi cái này khi click vào row)
@app.route("/api/devices/<int:device_id>/history", methods=["GET"])
def get_history(device_id):
    logs = history_log.get(device_id, [])
    return jsonify(logs)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    
    t = threading.Thread(target=mqtt_loop, daemon=True)
    t.start()
    
    app.run(host="0.0.0.0", port=port, debug=False)
