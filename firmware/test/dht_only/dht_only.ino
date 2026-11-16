// تست DHT22 بدون Ethernet
// فقط دما و رطوبت رو خروجی میده

#include <Arduino.h>
#include <DHT.h>

#define DHT_PIN 32
#define DHT_TYPE DHT22

DHT dht(DHT_PIN, DHT_TYPE);

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n\n==================");
  Serial.println("DHT22 Test Program");
  Serial.println("==================\n");
  
  // فعال کردن pull-up داخلی ESP32
  pinMode(DHT_PIN, INPUT_PULLUP);
  
  dht.begin();
  
  Serial.println("✅ DHT22 initialized!");
  Serial.println("Reading temperature and humidity every 2 seconds...\n");
}

void loop() {
  delay(2000);  // DHT22 نیاز به ۲ ثانیه وقفه داره
  
  // خواندن دما و رطوبت
  float temp = dht.readTemperature();
  float hum = dht.readHumidity();
  
  // بررسی خطا
  if (isnan(temp) || isnan(hum)) {
    Serial.println("❌ ERROR: Failed to read from DHT sensor!");
    Serial.println("Check connections:");
    Serial.println("  - VCC → 3.3V");
    Serial.println("  - DATA → GPIO32");
    Serial.println("  - GND → GND");
    Serial.println("  - Pull-up 10kΩ between VCC and DATA\n");
    return;
  }
  
  // نمایش داده‌ها
  Serial.print("🌡️ Temperature: ");
  Serial.print(temp, 1);
  Serial.print(" °C  |  ");
  
  Serial.print("💧 Humidity: ");
  Serial.print(hum, 1);
  Serial.println(" %");
  
  // بررسی محدوده منطقی
  if (temp < -40 || temp > 80) {
    Serial.println("⚠️ WARNING: Temperature out of range!");
  }
  
  if (hum < 0 || hum > 100) {
    Serial.println("⚠️ WARNING: Humidity out of range!");
  }
}
