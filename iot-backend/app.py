from flask import Flask, jsonify, request
from flask_cors import CORS
import paho.mqtt.client as mqtt
import json
import threading
import time
from datetime import datetime

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return "Server IoT đang hoạt động!"

# ================= MQTT CONFIG =================
MQTT_HOST = "9193406657be42b498e012fd208f4cf2.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "kahua269"
MQTT_PASS = "Haumeo2609"
MQTT_TOPIC_PREFIX = "iot/devices"

# ================= DEVICE STORAGE =================
devices = [
    {
        "id": 1,
        "name": "ESP32 phong khach",
        "status": "OFF",
        "temp": None,
        "pir": 0
    }
]

# Lưu history dạng { id: [logs] }
history_logs = {}

# ================== API LỊCH SỬ ==================
@app.route('/api/devices/<int:device_id>/history')
def get_history(device_id):
    return jsonify(history_logs.get(device_id, []))

# ================= MQTT CLIENT ===================
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

def on_mqtt_connect(client, userdata, flags, reason_code, properties=None):
    print("MQTT connected:", reason_code)
    topic = f"{MQTT_TOPIC_PREFIX}/+/state"
    client.subscribe(topic)
    print("Subscribed:", topic)

def on_mqtt_message(client, userdata, msg):
    print("MQTT:", msg.topic, msg.payload)

    try:
        data = json.loads(msg.payload.decode())
    except:
        return

    parts = msg.topic.split("/")
    if len(parts) < 3: 
        return
    
    try:
        dev_id = int(parts[2])
    except:
        return

    for d in devices:
        if d["id"] == dev_id:
            d["temp"] = data.get("temp", d["temp"])
            d["pir"] = data.get("pir", d["pir"])
            if "ctrl" in data:
                d["status"] = data["ctrl"]
            break


def mqtt_loop():
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
    mqtt_client.tls_set()
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message

    while True:
        try:
            mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
            mqtt_client.loop_forever()
        except Exception as e:
            print("MQTT error:", e)
            time.sleep(5)

# ================== API ===========================
@app.route("/api/devices")
def get_devices():
    return jsonify(devices)

@app.route("/api/devices/<int:device_id>/<action>", methods=["POST"])
def set_device(device_id, action):

    action = action.lower()
    if action not in ("on", "off"):
        return jsonify({"ok": False, "error": "invalid action"}), 400

    new_status = "ON" if action == "on" else "OFF"

    # Update thiết bị
    found = False
    for d in devices:
        if d["id"] == device_id:
            d["status"] = new_status
            found = True
            break

    if not found:
        return jsonify({"ok": False, "error": "device not found"}), 404

    # Publish MQTT
    topic = f"{MQTT_TOPIC_PREFIX}/{device_id}/set"
    mqtt_client.publish(topic, new_status, qos=1)

    # ============== GHI LỊCH SỬ (Đã sửa giới hạn 6 dòng) ==============
    if device_id not in history_logs:
        history_logs[device_id] = []

    log_entry = {
        "action": new_status,
        "user": "Admin",
        "time": datetime.now().strftime("%H:%M:%S - %d/%m/%Y"),
        "timestamp": time.time()
    }

    history_logs[device_id].insert(0, log_entry)

    # --- GIỚI HẠN LỊCH SỬ CÒN 6 DÒNG ---
    if len(history_logs[device_id]) > 6:
        history_logs[device_id].pop()
    # -----------------------------------

    return jsonify({
        "ok": True,
        "status": new_status,
        "topic": topic,
        "payload": new_status
    })


@app.route('/api/devices', methods=['POST'])
def add_device():
    data = request.json
    new_id = max([d["id"] for d in devices]) + 1 if devices else 1

    new_device = {
        "id": new_id,
        "name": data.get("name", f"Thiết bị {new_id}"),
        "status": "OFF",
        "temp": None,
        "pir": 0
    }
    devices.append(new_device)
    return jsonify(new_device)

@app.route('/api/devices/<int:device_id>', methods=['DELETE'])
def delete_device(device_id):
    global devices
    devices = [d for d in devices if d["id"] != device_id]
    history_logs.pop(device_id, None)
    return jsonify({"success": True})


# ============== START MQTT THREAD ==============
print("Starting MQTT thread...")
t = threading.Thread(target=mqtt_loop, daemon=True)
t.start()

# ============== RENDER MAIN ====================
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
