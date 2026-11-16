// Debug HTTP Server with Serial output
#include <Arduino.h>
#include <WiFi.h>
#include <DHT.h>
#include <ETH.h>
#include <WebServer.h>

#define DHT_PIN 2
#define DHT_TYPE DHT22

const char* wifi_ssid = "aryaii";
const char* wifi_pass = "arya1212";

DHT dht(DHT_PIN, DHT_TYPE);
WebServer server(80);

float temperature = 0;
float humidity = 0;
bool dht_valid = false;

void handleRoot() {
  Serial.println("[HTTP] Request to /");
  if (dht_valid) {
    String html = "<html><body><h1>Roztash</h1>";
    html += "<p>Temp: " + String(temperature, 1) + "</p>";
    html += "<p>Hum: " + String(humidity, 1) + "</p>";
    html += "<p>IP: " + ETH.localIP().toString() + "</p>";
    html += "</body></html>";
    server.send(200, "text/html", html);
    Serial.println("[HTTP] Sent HTML");
  } else {
    server.send(200, "text/plain", "No data");
  }
}

void handleJSON() {
  Serial.println("[HTTP] Request to /json");
  String json = "{\"temp\":" + String(temperature,1) + ",\"humidity\":" + String(humidity,1) + "}";
  server.send(200, "application/json", json);
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("\n=== ESP32 HTTP DEBUG ===");
  
  dht.begin();
  Serial.println("[DHT] OK");
  
  WiFi.onEvent([](WiFiEvent_t e){
    switch(e) {
      case ARDUINO_EVENT_ETH_START: Serial.println("[ETH] START"); break;
      case ARDUINO_EVENT_ETH_CONNECTED: Serial.println("[ETH] CONNECTED"); break;
      case ARDUINO_EVENT_ETH_GOT_IP: Serial.println("[ETH] GOT IP: " + ETH.localIP().toString()); break;
      case ARDUINO_EVENT_ETH_DISCONNECTED: Serial.println("[ETH] DISCONNECTED"); break;
    }
  });
  
  Serial.println("[ETH] Starting...");
  SPIClass ethSPI(HSPI);
  ethSPI.begin(18, 19, 23, 5);
  
  bool ok = ETH.begin(ETH_PHY_W5500, 1, 5, 21, -1, ethSPI, 4);
  Serial.println("[ETH] begin = " + String(ok ? "OK" : "FAILED"));
  
  delay(3000);
  
  Serial.println("[WiFi] Starting...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(wifi_ssid, wifi_pass);
  
  server.on("/", handleRoot);
  server.on("/json", handleJSON);
  server.begin();
  Serial.println("[HTTP] Started on port 80");
  
  Serial.println("=== READY ===");
}

void loop() {
  server.handleClient();
  
  static unsigned long t = 0;
  if (millis() - t > 5000) {
    float tt = dht.readTemperature();
    float hh = dht.readHumidity();
    if (!isnan(tt) && !isnan(hh)) {
      temperature = tt;
      humidity = hh;
      dht_valid = true;
      Serial.printf("[DHT] T=%.1f H=%.1f\n", tt, hh);
    }
    t = millis();
  }
}