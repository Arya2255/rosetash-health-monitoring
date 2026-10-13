// Deep test of W5500 with ultra slow SPI and custom config
#include <Arduino.h>
#include <WiFi.h>
#include <ETH.h>
#include <SPI.h>

bool eth_connected = false;

void eth_event(WiFiEvent_t event) {
  Serial.printf("[ETH] Event: %d\n", event);
  switch (event) {
    case ARDUINO_EVENT_ETH_START:
      Serial.println("[ETH] START");
      break;
    case ARDUINO_EVENT_ETH_CONNECTED:
      Serial.println("[ETH] CONNECTED - cable OK!");
      break;
    case ARDUINO_EVENT_ETH_GOT_IP:
      eth_connected = true;
      Serial.print("[ETH] GOT IP: ");
      Serial.println(ETH.localIP());
      break;
    case ARDUINO_EVENT_ETH_DISCONNECTED:
      eth_connected = false;
      Serial.println("[ETH] DISCONNECTED");
      break;
    case ARDUINO_EVENT_ETH_STOP:
      Serial.println("[ETH] STOP");
      break;
    default:
      break;
  }
}

SPIClass customSPI(HSPI);

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("\n=== W5500 DEEP TEST ===");
  
  // Custom SPI on HSPI pins: SCK=14, MISO=12, MOSI=13, CS=5
  Serial.println("[Setup] Initializing HSPI on pins 14,12,13,5...");
  customSPI.begin(14, 12, 13, 5);
  
  Serial.println("[Setup] Registering ETH event handler...");
  WiFi.onEvent(eth_event);
  
  Serial.println("[Setup] Starting W5500 ETH...");
  // Try with W5500 type, CS pin 5, no_INT=-1, RST=4, power=-1, SPI instance, 1MHz
  bool result = ETH.begin(ETH_PHY_W5500, 5, -1, 4, -1, customSPI, 1);
  Serial.printf("[Setup] ETH.begin() returned: %d\n", result);
  
  // Wait up to 15 seconds for link
  Serial.println("[Setup] Waiting for link...");
  for (int i = 0; i < 15; i++) {
    delay(1000);
    Serial.printf("[Setup] linkUp=%d, try=%d/15\n", ETH.linkUp(), i+1);
    if (ETH.linkUp()) {
      Serial.println("[Setup] LINK IS UP!");
      break;
    }
  }
  
  if (ETH.linkUp()) {
    Serial.println("[Setup] Configuring static IP...");
    ETH.config(IPAddress(10,217,71,202), IPAddress(10,217,71,1), IPAddress(255,255,255,0));
    Serial.print("[Setup] Static IP: ");
    Serial.println(ETH.localIP());
  }
  
  Serial.println("[Setup] Done!");
}

void loop() {
  Serial.printf("[Loop] linkUp=%d, IP=%s\n", 
    ETH.linkUp(), 
    eth_connected ? ETH.localIP().toString().c_str() : "N/A");
  delay(3000);
}