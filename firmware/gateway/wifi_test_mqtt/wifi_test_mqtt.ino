// WiFi test with MQTT status
#include <WiFi.h>
#include <PubSubClient.h>

const char* ssid = "aryaii";
const char* pass = "arya1212";
const char* mqtt_server = "10.217.71.243";
const int mqtt_port = 1884;

WiFiClient espClient;
PubSubClient mqtt(espClient);

void setup() {
  Serial.begin(115200);
  delay(500);
  
  Serial.println("=== WiFi Test with MQTT ===");
  
  // Connect WiFi
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, pass);
  
  Serial.print("Connecting to WiFi...");
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  Serial.println();
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("WiFi CONNECTED!");
    Serial.printf("IP: %s\n", WiFi.localIP().toString().c_str());
    
    // Try MQTT
    mqtt.setServer(mqtt_server, mqtt_port);
    Serial.print("Connecting to MQTT...");
    
    if (mqtt.connect("gw-test-1")) {
      Serial.println("MQTT CONNECTED!");
      mqtt.publish("roztash/gw-test-1/status", "{\"online\":true}");
      mqtt.publish("roztash/gw-test-1/debug", "WiFi connected via test firmware");
    } else {
      Serial.printf("MQTT failed, rc=%d\n", mqtt.state());
    }
  } else {
    Serial.println("WiFi FAILED!");
    Serial.printf("Status: %d\n", WiFi.status());
    
    // Print scanned networks
    Serial.println("Scanning networks...");
    int n = WiFi.scanNetworks();
    for (int i = 0; i < n; i++) {
      Serial.printf("  %s (RSSI: %d)\n", WiFi.SSID(i).c_str(), WiFi.RSSI(i));
    }
  }
}

void loop() {
  mqtt.loop();
  delay(1000);
}