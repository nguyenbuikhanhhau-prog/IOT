#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <esp_now.h>
#include <esp_wifi.h> 

// ===== CẤU HÌNH CẢM BIẾN TẠI CHỖ (COM3) =====
#define DHT_PIN     4
#define PIR_PIN     35
#define PIR_LED_PIN 15
#define DHT_TYPE    DHT11

// ===== CẤU HÌNH WIFI & MQTT =====
const char* WIFI_SSID = "AN BINH";
const char* WIFI_PASS = "chucvuive";

const char* MQTT_HOST = "9193406657be42b498e012fd208f4cf2.s1.eu.hivemq.cloud";
const uint16_t MQTT_PORT = 8883;
const char* MQTT_USER = "kahua269";
const char* MQTT_PASS = "Haumeo2609";

const char* TOPIC_CONTROL = "iot/control"; 
const char* TOPIC_STATE   = "iot/devices/state"; 
const char* TOPIC_CAPTURE = "iot/devices/capture";

WiFiClientSecure espClient;
PubSubClient mqttClient(espClient);
DHT dht(DHT_PIN, DHT_TYPE);

// ===== CẤU TRÚC GÓI ESP-NOW TỪ COM11 =====
typedef struct struct_message {
  int   gas;
  float temp;
  float hum;
} struct_message;

// Biến lưu dữ liệu từ COM11
volatile int   remoteGas  = -1;
volatile float remoteTemp = NAN;
volatile float remoteHum  = NAN;

// Biến toàn cục COM3
unsigned long lastPublish = 0;
int lastPir = 0;
float currentTemp = 0.0;
float currentHum  = 0.0;

// ===== CALLBACK ESP-NOW (SỬA LẠI CHO CHUẨN VERSION CŨ) =====
// Đây là kiểu khai báo chuẩn nhất cho ESP32 Core 2.x mà bạn đang dùng
void onEspNowRecv(const uint8_t * mac, const uint8_t *incomingData, int len) {
  if (len == sizeof(struct_message)) {
    struct_message data;
    memcpy(&data, incomingData, sizeof(data));

    remoteGas  = data.gas;
    remoteTemp = data.temp;
    remoteHum  = data.hum;

    // In ra ngay để debug
    Serial.printf("📶 [ESP-NOW] RX: Gas=%d, T=%.1f, H=%.1f\n", remoteGas, remoteTemp, remoteHum);
  } else {
    Serial.print("⚠️ Nhan sai kich thuoc goi tin: ");
    Serial.println(len);
  }
}

// ===== HÀM ĐỌC CẢM BIẾN & GỬI MQTT =====
void publish_local_sensors(bool is_pir_event) {
  if (!is_pir_event) {
    float h = dht.readHumidity();
    float t = dht.readTemperature();
    if (!isnan(h) && !isnan(t)) {
      currentTemp = t;
      currentHum  = h;
    }
  }

  int pirState = digitalRead(PIR_PIN);
  JsonDocument doc;

  // Dữ liệu COM3
  doc["temp"] = currentTemp;
  doc["hum"]  = currentHum;
  doc["pir"]  = pirState;

  // Dữ liệu COM11 (Chỉ gửi nếu đã nhận được ít nhất 1 lần)
  if (remoteGas >= 0)     doc["gas"]   = remoteGas;
  if (!isnan(remoteTemp)) doc["temp2"] = remoteTemp;
  if (!isnan(remoteHum))  doc["hum2"]  = remoteHum;

  String output;
  serializeJson(doc, output);
  mqttClient.publish(TOPIC_STATE, output.c_str());
  Serial.println("📤 [MQTT] Sent: " + output);
}

// ===== WIFI & MQTT =====
void connectWiFi() {
  Serial.print("Connecting WiFi");
  
  // Quan trọng: Chế độ vừa AP vừa STA giúp ESP-NOW ổn định hơn
  WiFi.mode(WIFI_AP_STA); 
  
  // Tắt chế độ tiết kiệm pin để nhận ESP-NOW mượt hơn
  esp_wifi_set_ps(WIFI_PS_NONE);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n✅ WiFi Connected!");
  
  // In ra kênh để kiểm tra (Để bạn biết đường chỉnh con Gửi nếu cần)
  Serial.print("CHANNEL: ");
  Serial.println(WiFi.channel()); 
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String msg = "";
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];
  
  JsonDocument doc;
  if (!deserializeJson(doc, msg)) {
    int pin = doc["pin"];
    const char* status = doc["status"];
    // Loại trừ các chân cảm biến để tránh xung đột
    if (pin > 0 && pin != DHT_PIN && pin != PIR_LED_PIN && pin != PIR_PIN) { 
      pinMode(pin, OUTPUT);
      digitalWrite(pin, String(status) == "ON" ? HIGH : LOW);
      Serial.printf("-> Lenh: GPIO %d %s\n", pin, status);
    }
  }
}

void connectMQTT() {
  espClient.setInsecure();
  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);

  while (!mqttClient.connected()) {
    Serial.print("Connecting MQTT...");
    if (mqttClient.connect("esp32-gateway-com3", MQTT_USER, MQTT_PASS)) {
      Serial.println("OK");
      mqttClient.subscribe(TOPIC_CONTROL);
    } else {
      Serial.print("Fail state=");
      Serial.print(mqttClient.state());
      Serial.println(" try again in 2s");
      delay(2000);
    }
  }
}

// ===== SETUP =====
void setup() {
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT);
  pinMode(PIR_LED_PIN, OUTPUT);
  dht.begin();

  // 1. Kết nối WiFi TRƯỚC để Router chỉ định kênh (Channel)
  connectWiFi();

  // 2. Sau đó mới Init ESP-NOW
  if (esp_now_init() != ESP_OK) {
    Serial.println("❌ ESP-NOW Init Failed");
    ESP.restart();
  }
  
  // Đăng ký hàm nhận (Dùng cách đơn giản, bỏ wrapper)
  esp_now_register_recv_cb(onEspNowRecv);
  
  Serial.println("✅ ESP-NOW Ready");

  // 3. Kết nối MQTT
  connectMQTT();
}

// ===== LOOP =====
void loop() {
  if (!mqttClient.connected()) connectMQTT();
  mqttClient.loop();

  int pir = digitalRead(PIR_PIN);
  if (pir != lastPir) {
    if (pir == 1) mqttClient.publish(TOPIC_CAPTURE, "capture");
    lastPir = pir;
    publish_local_sensors(true);
  }
  digitalWrite(PIR_LED_PIN, pir);

  if (millis() - lastPublish > 5000) { 
    lastPublish = millis();
    publish_local_sensors(false);
  }
}