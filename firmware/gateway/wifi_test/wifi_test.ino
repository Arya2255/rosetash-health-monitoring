// Minimal WiFi test - just connect and print IP
#include <WiFi.h>

const char* ssid = "aryaii";
const char* pass = "arya1212";

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("=== WiFi Test ===");
  Serial.printf("Connecting to %s...\n", ssid);
  
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, pass);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 60) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("");
    Serial.println("CONNECTED!");
    Serial.printf("IP: %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("Gateway: %s\n", WiFi.gatewayIP().toString().c_str());
  } else {
    Serial.println("");
    Serial.println("FAILED TO CONNECT");
    Serial.printf("Status: %d\n", WiFi.status());
  }
  
  // Print all available networks
  Serial.println("\nScanning networks...");
  int n = WiFi.scanNetworks();
  for (int i = 0; i < n; i++) {
    Serial.printf("%d: %s (RSSI: %d)\n", i, WiFi.SSID(i).c_str(), WiFi.RSSI(i));
  }
}

void loop() {
  delay(1000);
}