#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <DHT.h>

// ===== 1. CẤU HÌNH WIFI (BẮT BUỘC ĐỂ ĐỒNG BỘ KÊNH 8) =====
const char* WIFI_SSID = "AN BINH";
const char* WIFI_PASS = "chucvuive";

// ===== 2. ĐỊA CHỈ MAC CỦA COM3 (SỬA LẠI CHO ĐÚNG) =====
// Bạn phải thay dòng này bằng MAC thật của con COM3 nhé
uint8_t broadcastAddress[] = {0x80, 0xF3, 0xDA, 0x42, 0x73, 0xB8}; 
// ===== 3. CẤU HÌNH CẢM BIẾN (COM11) =====
#define DHT_PIN     4  
#define DHT_TYPE    DHT11
#define MQ2_PIN     34 

DHT dht(DHT_PIN, DHT_TYPE);

// Cấu trúc dữ liệu
typedef struct struct_message {
  int   gas;
  float temp;
  float hum;
} struct_message;

struct_message myData;
esp_now_peer_info_t peerInfo;

// Hàm báo trạng thái gửi
void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
  Serial.print("\r\nTrang thai gui: ");
  Serial.println(status == ESP_NOW_SEND_SUCCESS ? "OK (Da gui)" : "LOI (Fail)");
}

void setup() {
  Serial.begin(115200);
  dht.begin();
  
  // --- KẾT NỐI WIFI ĐỂ LẤY KÊNH 8 ---
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("COM11 dang ket noi WiFi...");
  
  // Đợi kết nối
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");
  Serial.print("COM11 dang chay kenh: ");
  Serial.println(WiFi.channel()); // Nó phải in ra số 8 (giống COM3)

  // --- KHỞI TẠO ESP-NOW ---
  if (esp_now_init() != ESP_OK) {
    Serial.println("Loi ESP-NOW");
    return;
  }

  esp_now_register_send_cb(OnDataSent);

  // Đăng ký Peer (COM3)
  memcpy(peerInfo.peer_addr, broadcastAddress, 6);
  peerInfo.channel = 0;  // 0 = dùng kênh hiện tại của WiFi
  peerInfo.encrypt = false;

  if (esp_now_add_peer(&peerInfo) != ESP_OK){
    Serial.println("Loi them Peer (Sai MAC?)");
    return;
  }
}

void loop() {
  // Đọc cảm biến thật
  float h = dht.readHumidity();
  float t = dht.readTemperature();
  int gas = analogRead(MQ2_PIN);

  // Nếu lỗi thì giả lập số để test
  if (isnan(h) || isnan(t)) {
    Serial.println("Loi doc DHT, gui so gia lap...");
    t = 25.5; h = 60.0;
  }

  myData.temp = t;
  myData.hum = h;
  myData.gas = gas;

  // Gửi đi
  esp_err_t result = esp_now_send(broadcastAddress, (uint8_t *) &myData, sizeof(myData));

  Serial.printf("Gui: Gas=%d, Temp=%.1f, Hum=%.1f\n", gas, t, h);
  delay(2000);
}