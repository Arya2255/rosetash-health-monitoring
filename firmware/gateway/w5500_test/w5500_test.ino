// Minimal W5500 test with explicit VSPI - keep original wiring
#include <Arduino.h>
#include <WiFi.h>
#include <ETH.h>
#include <SPI.h>

bool eth_connected = false;

// Use VSPI with original pinout from user
// MOSI=23, MISO=19, SCK=18, CS=4
#define PIN_MISO 19
#define PIN_MOSI 23
#define PIN_SCK 18
#define PIN_CS 4

void eth_event(WiFiEvent_t event) {
  Serial.printf("[eth] event: %d\n", event);
  switch (event) {
    case ARDUINO_EVENT_ETH_START:
      Serial.println("[eth] START");
      break;
    case ARDUINO_EVENT_ETH_CONNECTED:
      Serial.println("[eth] CONNECTED - cable OK");
      break;
    case ARDUINO_EVENT_ETH_GOT_IP:
      eth_connected = true;
      Serial.print("[eth] GOT IP: ");
      Serial.println(ETH.localIP());
      break;
    case ARDUINO_EVENT_ETH_DISCONNECTED:
      eth_connected = false;
      Serial.println("[eth] DISCONNECTED");
      break;
    case ARDUINO_EVENT_ETH_STOP:
      Serial.println("[eth] STOP");
      break;
    default:
      Serial.printf("[eth] other event: %d\n", event);
      break;
  }
}

void setup() {
  Serial.begin(115200);
  delay(3000);
  Serial.println("\n[W5500] VSPI test - original pins...");
  Serial.printf("[W5500] Pins: MOSI=%d, MISO=%d, SCK=%d, CS=%d\n", PIN_MOSI, PIN_MISO, PIN_SCK, PIN_CS);
  
  Serial.println("[W5500] Registering event handler...");
  WiFi.onEvent(eth_event);
  
  Serial.println("[W5500] Calling ETH.begin() with explicit VSPI...");
  // Use VSPI (default SPI) with explicit pins - slow speed
  ETH.begin(ETH_PHY_W5500, PIN_CS, -1, -1, -1, SPI, 10);
  
  Serial.println("[W5500] ETH.begin() called, waiting for link...");
}

void loop() {
  Serial.printf("[loop] eth_connected=%d, linkUp=%d\n", eth_connected, ETH.linkUp());
  Serial.printf("[loop] IP: %s\n", eth_connected ? ETH.localIP().toString().c_str() : "N/A");
  delay(5000);
}