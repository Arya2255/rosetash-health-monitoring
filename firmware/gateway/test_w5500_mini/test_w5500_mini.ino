// Minimal W5500 test - just Ethernet
#include <Arduino.h>
#include <ETH.h>
#include <WiFi.h>
#include <SPI.h>

#define ETH_CS    5
#define ETH_IRQ   21
#define ETH_RST   -1

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("=== MINIMAL W5500 TEST ===");
  
  // Event handler
  WiFi.onEvent([](WiFiEvent_t event) {
    switch(event) {
      case ARDUINO_EVENT_ETH_START:
        Serial.println("[ETH] STARTED");
        break;
      case ARDUINO_EVENT_ETH_CONNECTED:
        Serial.println("[ETH] CONNECTED (cable)");
        break;
      case ARDUINO_EVENT_ETH_GOT_IP:
        Serial.print("[ETH] GOT IP: ");
        Serial.println(ETH.localIP());
        break;
      case ARDUINO_EVENT_ETH_DISCONNECTED:
        Serial.println("[ETH] DISCONNECTED");
        break;
      case ARDUINO_EVENT_ETH_STOP:
        Serial.println("[ETH] STOPPED");
        break;
    }
  });
  
  // Use HSPI instead of default VSPI
  Serial.println("Initializing HSPI...");
  SPIClass ethSPI(HSPI);
  ethSPI.begin(18, 19, 23, 5);  // SCK, MISO, MOSI, CS
  
  Serial.println("Calling ETH.begin()...");
  // Use HSPI instead of default SPI
  bool ok = ETH.begin(ETH_PHY_W5500, 1, ETH_CS, ETH_IRQ, ETH_RST, ethSPI, 4);
  Serial.print("ETH.begin result: ");
  Serial.println(ok ? "OK" : "FAILED");
}

void loop() {
  delay(2000);
  Serial.printf("[LOOP] linkUp=%d, localIP=%s\n", ETH.linkUp(), ETH.localIP().toString().c_str());
}