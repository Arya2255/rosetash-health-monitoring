// Roztash Gateway - HTTP Server for Factory Network
// No MQTT, no fixed IP - just HTTP!

#include <Arduino.h>
#include <WiFi.h>
#include <DHT.h>
#include <ETH.h>
#include <WebServer.h>

// === Pin Configuration ===
#define DHT_PIN       32  // GPIO32 (از Adafruit recommendation)
#define DHT_TYPE      DHT22

// === Network Configuration ===
const char* wifi_ssid = "aryaii";
const char* wifi_pass = "arya1212";

// === Globals ===
DHT dht(DHT_PIN, DHT_TYPE);
WebServer server(80);

float temperature = 0;
float humidity = 0;
bool dht_valid = false;
bool eth_connected = false;
bool wifi_connected = false;

void handleRoot() {
  if (dht_valid) {
    String html = "<html><body><h1>Roztash Gateway</h1>";
    html += "<p>Temp: " + String(temperature, 1) + "°C</p>";
    html += "<p>Humidity: " + String(humidity, 1) + "%</p>";
    html += "<p>Eth: " + String(eth_connected ? "Connected" : "Disconnected") + "</p>";
    html += "<p>WiFi: " + String(wifi_connected ? "Connected" : "Disconnected") + "</p>";
    html += "<p>Eth IP: " + ETH.localIP().toString() + "</p>";
    html += "<p>WiFi IP: " + WiFi.localIP().toString() + "</p>";
    html += "</body></html>";
    server.send(200, "text/html", html);
  } else {
    server.send(200, "text/plain", "DHT22 not ready");
  }
}

void handleJSON() {
  if (dht_valid) {
    String json = "{\"temp\":" + String(temperature, 1) +
                 ",\"humidity\":" + String(humidity, 1) +
                 ",\"eth\":" + String(eth_connected ? 1 : 0) +
                 ",\"wifi\":" + String(wifi_connected ? 1 : 0) +
                 ",\"eth_ip\":\"" + ETH.localIP().toString() + "\"" +
                 ",\"wifi_ip\":\"" + WiFi.localIP().toString() + "\"}";
    server.send(200, "application/json", json);
  } else {
    server.send(200, "application/json", "{\"error\":\"no data\"}");
  }
}

void handleStatus() {
  server.send(200, "text/plain", "OK");
}

void eth_event(WiFiEvent_t event) {
  switch (event) {
    case ARDUINO_EVENT_ETH_START:
      Serial.println("[ETH] Starting...");
      break;
    case ARDUINO_EVENT_ETH_CONNECTED:
      Serial.println("[ETH] Cable connected!");
      eth_connected = true;
      break;
    case ARDUINO_EVENT_ETH_GOT_IP:
      Serial.print("[ETH] IP: ");
      Serial.println(ETH.localIP());
      break;
    case ARDUINO_EVENT_ETH_DISCONNECTED:
      Serial.println("[ETH] Disconnected");
      eth_connected = false;
      break;
  }
}

void wifi_event(WiFiEvent_t event) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_START:
      Serial.println("[WiFi] Starting...");
      break;
    case ARDUINO_EVENT_WIFI_STA_CONNECTED:
      Serial.println("[WiFi] Connected!");
      wifi_connected = true;
      break;
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      Serial.print("[WiFi] IP: ");
      Serial.println(WiFi.localIP());
      break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      Serial.println("[WiFi] Disconnected");
      wifi_connected = false;
      break;
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  // Init DHT
  pinMode(DHT_PIN, INPUT_PULLUP);  // Pull-up داخلی
  dht.begin();
  Serial.println("[DHT] Started on GPIO32");
  
  // Events
  WiFi.onEvent(wifi_event);
  
  // Start WiFi
  Serial.println("[init] Starting WiFi...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(wifi_ssid, wifi_pass);
  
  // HTTP Server
  server.on("/", handleRoot);
  server.on("/json", handleJSON);
  server.on("/status", handleStatus);
  server.begin();
  Serial.println("[HTTP] Server started on port 80");
  
  Serial.println("[init] Done! Waiting for WiFi...");
}

void loop() {
  server.handleClient();
  
  // Read DHT every 10 seconds
  static unsigned long last_read = 0;
  if (millis() - last_read > 10000) {
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    
    if (!isnan(t) && !isnan(h)) {
      temperature = t;
      humidity = h;
      dht_valid = true;
      Serial.printf("[DHT] Temp: %.1f, Hum: %.1f\n", t, h);
    } else {
      dht_valid = false;
    }
    last_read = millis();
  }
  
  delay(10);
}