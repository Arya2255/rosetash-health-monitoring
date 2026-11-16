// Simple W5500 test - based on working examples
#include <Arduino.h>
#include <ETH.h>
#include <WiFi.h>
#include <SPI.h>

// Your exact wiring
#define ETH_CS    5    // SCS → GPIO5
#define ETH_IRQ   21   // INT → GPIO21
#define ETH_RST   -1   // Not connected

// SPI pins (VSPI default)
#define ETH_SCK   18   // SCLK → GPIO18
#define ETH_MISO  19   // MISO → GPIO19
#define ETH_MOSI  23   // MOSI → GPIO23

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("\n=== W5500 TEST ===");
  Serial.printf("CS: GPIO%d, IRQ: GPIO%d\n", ETH_CS, ETH_IRQ);
  
  // Event handler
  WiFi.onEvent([](WiFiEvent_t event) {
    switch(event) {
      case ARDUINO_EVENT_ETH_START:
        Serial.println("[ETH] STARTED");
        break;
      case ARDUINO_EVENT_ETH_CONNECTED:
        Serial.println("[ETH] CABLE CONNECTED!");
        break;
      case ARDUINO_EVENT_ETH_GOT_IP:
        Serial.print("[ETH] IP: ");
        Serial.println(ETH.localIP());
        break;
      case ARDUINO_EVENT_ETH_DISCONNECTED:
        Serial.println("[ETH] DISCONNECTED");
        break;
    }
  });
  
  // Start SPI with explicit pins
  Serial.println("Starting SPI...");
  SPI.begin(ETH_SCK, ETH_MISO, ETH_MOSI, ETH_CS);
  
  // Start Ethernet
  Serial.println("Starting ETH...");
  bool ok = ETH.begin(ETH_PHY_W5500, 1, ETH_CS, ETH_IRQ, ETH_RST, SPI, 4);
  Serial.print("ETH.begin = ");
  Serial.println(ok ? "OK" : "FAILED");
}

void loop() {
  delay(3000);
  Serial.printf("[LOOP] linkUp=%d, IP=%s\n", ETH.linkUp(), ETH.localIP().toString().c_str());
}