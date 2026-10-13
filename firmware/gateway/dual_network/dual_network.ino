// Roztash Gateway — Dual Network (Ethernet + WiFi) with DHT22
// Priority: Ethernet first, then WiFi — both active for redundancy
// Board: ESP32 DevKit

#include <Arduino.h>
#include <WiFi.h>
#include <ETH.h>
#include <DHT.h>
#include <PubSubClient.h>

// === Pin Configuration ===
#define DHT_PIN       2       // DHT22 Data pin
#define DHT_TYPE      DHT22   // AM2302 = DHT22
#define ETH_CS_PIN    5       // W5500 CS pin
#define ETH_IRQ_PIN   21      // W5500 INT/IRQ pin - CRITICAL for DHCP!
#define ETH_POWER_PIN -1      // No external power control

// === Network Configuration ===
const char* wifi_ssid = "aryaii";
const char* wifi_pass = "arya1212";

// MQTT (run on laptop)
const char* mqtt_server = "10.217.71.243";  // Laptop WiFi IP
const uint16_t mqtt_port = 1883;  // یا 1884 اگه قبلاً تغییر دادی

// === Globals ===
DHT dht(DHT_PIN, DHT_TYPE);
WiFiClient ethClient;  // For MQTT over Ethernet or WiFi
PubSubClient mqtt(ethClient);

bool eth_connected = false;
bool wifi_connected = false;
unsigned long last_eth_check = 0;
unsigned long last_wifi_check = 0;
unsigned long last_dht_read = 0;
unsigned long last_mqtt_reconnect = 0;

float temperature = 0;
float humidity = 0;
bool dht_valid = false;

// === Ethernet Event Handler ===
void eth_event(WiFiEvent_t event) {
  switch (event) {
    case ARDUINO_EVENT_ETH_START:
      Serial.println("[eth] starting...");
      break;
    case ARDUINO_EVENT_ETH_CONNECTED:
      Serial.println("[eth] cable connected");
      break;
    case ARDUINO_EVENT_ETH_GOT_IP:
      eth_connected = true;
      Serial.print("[eth] got IP: ");
      Serial.println(ETH.localIP());
      reconnectMQTT();
      publishStartup("[eth] got IP");
      break;
    case ARDUINO_EVENT_ETH_DISCONNECTED:
      eth_connected = false;
      Serial.println("[eth] disconnected");
      publishStartup("[eth] disconnected");
      break;
    case ARDUINO_EVENT_ETH_STOP:
      eth_connected = false;
      Serial.println("[eth] stopped");
      publishStartup("[eth] stopped");
      break;
    default:
      break;
  }
}

// === WiFi Event Handler ===
void wifi_event(WiFiEvent_t event) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_START:
      Serial.println("[wifi] starting...");
      break;
    case ARDUINO_EVENT_WIFI_STA_CONNECTED:
      Serial.println("[wifi] connected to AP");
      break;
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      wifi_connected = true;
      Serial.print("[wifi] got IP: ");
      Serial.println(WiFi.localIP());
      reconnectMQTT();
      break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      wifi_connected = false;
      Serial.println("[wifi] disconnected");
      break;
    default:
      break;
  }
}

// === Reconnect MQTT ===
void reconnectMQTT() {
  if (mqtt.connected()) return;
  
  unsigned long now = millis();
  if (now - last_mqtt_reconnect < 5000) return;  // 5s cooldown
  last_mqtt_reconnect = now;
  
  // Try to connect with client ID
  String clientId = "RoztashGateway-";
  clientId += String(random(0xffff), HEX);
  
  // Prefer Ethernet connection (lower latency)
  if (eth_connected && ETH.localIP()) {
    Serial.print("[mqtt] connecting via Ethernet... ");
    if (mqtt.connect(clientId.c_str())) {
      Serial.println("OK");
      return;
    }
    Serial.println("FAILED");
  }
  
  // Fallback to WiFi
  if (wifi_connected && WiFi.localIP()) {
    Serial.print("[mqtt] connecting via WiFi... ");
    if (mqtt.connect(clientId.c_str())) {
      Serial.println("OK");
      return;
    }
    Serial.println("FAILED");
  }
}

// === Read DHT22 ===
void readDHT() {
  unsigned long now = millis();
  if (now - last_dht_read < 2000) return;  // Min 2s between reads
  last_dht_read = now;
  
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  
  if (isnan(t) || isnan(h)) {
    Serial.println("[dht] read failed!");
    dht_valid = false;
    return;
  }
  
  temperature = t;
  humidity = h;
  dht_valid = true;
  
  Serial.printf("[dht] temp=%.1f°C humidity=%.1f%%\n", temperature, humidity);
}

// === Publish Status ===
void publishStatus() {
  if (!mqtt.connected()) return;
  
  char payload[256];
  snprintf(payload, sizeof(payload),
    "{"
    "\"temp\":%.1f,"
    "\"humidity\":%.1f,"
    "\"dht_valid\":%d,"
    "\"eth_connected\":%d,"
    "\"wifi_connected\":%d,"
    "\"eth_ip\":\"%s\","
    "\"wifi_ip\":\"%s\","
    "\"eth_rssi\":0,"
    "\"wifi_rssi\":%d"
    "}",
    temperature, humidity, dht_valid ? 1 : 0,
    eth_connected ? 1 : 0, wifi_connected ? 1 : 0,
    eth_connected ? ETH.localIP().toString().c_str() : "0.0.0.0",
    wifi_connected ? WiFi.localIP().toString().c_str() : "0.0.0.0",
    WiFi.RSSI()
  );
  
  mqtt.publish("roztash/gateway/status", payload, true);
  Serial.printf("[mqtt] published: %s\n", payload);
}

// === Print Network Status ===
void printNetworkStatus() {
  Serial.println("=== Network Status ===");
  Serial.printf("Ethernet: %s | IP: %s\n", 
    eth_connected ? "✓" : "✗",
    eth_connected ? ETH.localIP().toString().c_str() : "N/A");
  Serial.printf("WiFi:    %s | IP: %s | RSSI: %d dBm\n", 
    wifi_connected ? "✓" : "✗",
    wifi_connected ? WiFi.localIP().toString().c_str() : "N/A",
    WiFi.RSSI());
  Serial.printf("MQTT:    %s\n", mqtt.connected() ? "✓" : "✗");
  Serial.printf("DHT22:   %s | %.1f°C / %.1f%%\n",
    dht_valid ? "✓" : "✗", temperature, humidity);
  Serial.println("========================");
}

// === Publish Startup Event ===
void publishStartup(const char* msg) {
  // Always publish via serial for debugging - even if MQTT not connected
  Serial.printf("[startup] %s\n", msg);
  
  // Try to ensure MQTT is connected
  reconnectMQTT();
  delay(100);
  
  if (mqtt.connected()) {
    char payload[128];
    snprintf(payload, sizeof(payload), "{\"msg\":\"%s\",\"uptime\":%lu}", msg, millis());
    mqtt.publish("roztash/gateway/debug", payload, false);
    Serial.printf("[mqtt] debug: %s\n", payload);
  } else {
    Serial.println("[mqtt] not connected yet, skipping publish");
  }
}

// === Setup ===
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n[gw] Roztash Dual-Network + DHT22");
  
  // Initialize DHT22
  dht.begin();
  
  // Register event handlers
  WiFi.onEvent(eth_event);
  WiFi.onEvent(wifi_event);
  
  // Configure MQTT
  mqtt.setServer(mqtt_server, mqtt_port);
  
  // Priority 1: Start Ethernet (wired) - W5500 on SPI
  Serial.println("[init] starting Ethernet...");
  
  // Initialize HSPI (not default VSPI) with custom pins BEFORE ETH.begin()
  Serial.println("[init] Initializing HSPI...");
  SPIClass ethSPI(HSPI);
  ethSPI.begin(18, 19, 23, 5);  // SCK=18, MISO=19, MOSI=23, CS=5
  
  delay(1000);  // Give W5500 time to power up
  
  Serial.println("[init] ETH.begin() with IRQ pin...");
  // Use HSPI instead of default SPI
  ETH.begin(ETH_PHY_W5500, 1, ETH_CS_PIN, ETH_IRQ_PIN, -1, ethSPI, 4);  
  Serial.println("[init] ETH.begin() called");
  
  // Wait longer for ETH to initialize
  delay(2000);
  Serial.printf("[init] ETH link up? %d\n", ETH.linkUp());
  publishStartup("[init] ETH begin called");
  
  // Priority 2: Start WiFi (wireless) - AFTER Ethernet
  Serial.println("[init] starting WiFi...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(wifi_ssid, wifi_pass);
  
  Serial.println("[init] done. Waiting for network...");
}

// === Loop ===
unsigned long last_status_print = 0;

void loop() {
  unsigned long now = millis();
  
  // MQTT keepalive
  if (mqtt.connected()) {
    mqtt.loop();
  } else {
    reconnectMQTT();
  }
  
  // Read DHT22 sensor
  readDHT();
  
  // Print status every 30 seconds
  if (now - last_status_print >= 30000) {
    last_status_print = now;
    printNetworkStatus();
    publishStatus();
  }
  
  delay(10);
}