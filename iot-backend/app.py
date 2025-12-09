from flask import Flask, jsonify, request
from flask_cors import CORS
import paho.mqtt.client as mqtt
import json
import threading
import time

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return "Server IoT đang hoạt động!"
    
# ===== MQTT CONFIG =====
# NHỚ copy đúng host từ HiveMQ (Cluster URL)
MQTT_HOST = "9193406657be42b498e012fd208f4cf2.s1.eu.hivemq.cloud"  # sửa lại cho trùng với ESP
MQTT_PORT = 8883
MQTT_USER = "kahua269"
MQTT_PASS = "Haumeo2609"   # trùng với ESP
MQTT_TOPIC_PREFIX = "iot/devices"

# ===== DU LIEU THIET BI (luu trong RAM) =====
devices = [
    {
        "id": 1,
        "name": "ESP32 phong khach",
        "status": "OFF",   # den dieu khien chan 23
        "temp": None,      # nhiet do tu LM35
        "pir": 0           # 1: co nguoi, 0: khong
    }
]

# Khởi tạo MQTT client đúng chuẩn HiveMQ Cloud
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
  # nếu nó warning CallbackAPI thì sau sửa thành mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

# ================== MQTT CALLBACKS ==================
def on_mqtt_connect(client, userdata, flags, reason_code, properties=None):
    print("MQTT connected, code:", reason_code)
    topic = f"{MQTT_TOPIC_PREFIX}/+/state"
    client.subscribe(topic)
    print("Subscribed:", topic)


def on_mqtt_message(client, userdata, msg):
    print("MQTT message:", msg.topic, msg.payload)
    try:
        data = json.loads(msg.payload.decode())
    except Exception as e:
        print("JSON error:", e)
        return

    # topic: iot/devices/<id>/state
    parts = msg.topic.split("/")
    dev_id = None
    if len(parts) >= 3:
        try:
            dev_id = int(parts[2])
        except ValueError:
            pass

    if dev_id is None:
        return

    for d in devices:
        if d["id"] == dev_id:
            if "temp" in data:
                d["temp"] = data["temp"]
            if "pir" in data:
                d["pir"] = data["pir"]
            if "ctrl" in data and data["ctrl"] in ("ON", "OFF"):
                d["status"] = data["ctrl"]
            break


def mqtt_loop():
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
    mqtt_client.tls_set()  # dùng CA mặc định (ok với HiveMQ Cloud)
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message

    while True:
        try:
            print("Connecting to MQTT broker...")
            mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
            mqtt_client.loop_forever()
        except Exception as e:
            print("MQTT error:", e)
            time.sleep(5)


# ================== API ==================
@app.route("/api/devices", methods=["GET"])
def get_devices():
    return jsonify(devices)


@app.route("/api/devices/<int:device_id>/<action>", methods=["POST"])
def set_device(device_id, action):
    action = action.lower()
    if action not in ("on", "off"):
        return jsonify({"ok": False, "error": "invalid action"}), 400

    new_status = "ON" if action == "on" else "OFF"

    # update trong list
    found = False
    for d in devices:
        if d["id"] == device_id:
            d["status"] = new_status
            found = True
            break

    if not found:
        return jsonify({"ok": False, "error": "device not found"}), 404

    # gui lenh MQTT
    topic = f"{MQTT_TOPIC_PREFIX}/{device_id}/set"
    payload = new_status
    mqtt_client.publish(topic, payload, qos=1)
    print("Publish control:", topic, payload)

    return jsonify({
        "ok": True,
        "status": new_status,
        "topic": topic,
        "payload": payload
    })


print("Đang khởi động MQTT Thread...")
t = threading.Thread(target=mqtt_loop, daemon=True)
t.start()

# ================== PHẦN MAIN (ĐỂ LẠI CHO LOCAL) ==================
if __name__ == "__main__":
    import os
    # Phần này chỉ chạy khi bạn test trên máy tính cá nhân
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Flask backend on 0.0.0.0:{port} ...")
    app.run(host="0.0.0.0", port=port, debug=False)








