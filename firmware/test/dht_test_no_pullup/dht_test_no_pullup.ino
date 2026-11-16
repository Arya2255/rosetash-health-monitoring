// تست DHT22 بدون مقاومت pull-up
#include <Arduino.h>
#include <DHT.h>

#define DHT_PIN 32
#define DHT_TYPE DHT22

DHT dht(DHT_PIN, DHT_TYPE);

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n\n==================");
  Serial.println("DHT22 Test (NO PULL-UP)");
  Serial.println("==================\n");
  
  // روش کاری: فعال‌کن pull-up داخلی ESP32
  pinMode(DHT_PIN, INPUT_PULLUP);
  
  dht.begin();
  
  Serial.println("DHT22 started!");
  Serial.println("Testing without external resistor...\n");
}

void loop() {
  delay(2000);  // DHT22 نیاز به ۲ ثانیه وقفه داره
  
  float temp = dht.readTemperature();
  float hum = dht.readHumidity();
  
  // بررسی خطا
  if (isnan(temp) || isnan(hum)) {
    Serial.println("❌ ERROR: Failed to read from DHT22!");
    Serial.println("Probable cause: Missing pull-up resistor");
    Serial.println("Suggestion: Add 10kΩ resistor between VCC and DATA\n");
    return;
  }
  
  // نمایش داده‌ها
  Serial.print("✅ Temperature: ");
  Serial.print(temp);
  Serial.println(" °C");
  
  Serial.print("✅ Humidity: ");
  Serial.print(hum);
  Serial.println(" %\n");
  
  // نمایش وضعیت
  if (temp > 100 || temp < -40 || hum > 100 || hum < 0) {
    Serial.println("⚠️ WARNING: Values out of range!");
    Serial.println("This suggests connection problem.\n");
  }
}
