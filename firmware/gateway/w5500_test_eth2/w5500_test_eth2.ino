// Test W5500 with Ethernet2 library
#include <Arduino.h>
#include <SPI.h>
#include <Ethernet2.h>

// Pin configuration - same as before
#define W5500_CS 4

byte mac[] = {0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED};

void setup() {
  Serial.begin(115200);
  delay(3000);
  Serial.println("\n[Ethernet2] W5500 test starting...");
  
  // Start Ethernet with W5500
  Serial.println("[Ethernet2] Calling Ethernet.begin()...");
  Ethernet.init(W5500_CS);
  
  // Wait for link
  Serial.println("[Ethernet2] Waiting for link...");
  unsigned long start = millis();
  while (Ethernet.linkStatus() == LinkOFF && millis() - start < 15000) {
    Serial.printf("[Ethernet2] linkStatus=%d, time=%lu\n", Ethernet.linkStatus(), millis()-start);
    delay(1000);
  }
  
  Serial.printf("[Ethernet2] Final linkStatus: %d\n", Ethernet.linkStatus());
  
  if (Ethernet.linkStatus() == LinkON) {
    Serial.println("[Ethernet2] Link is ON! Requesting IP via DHCP...");
    if (Ethernet.begin(mac) == 1) {
      Serial.print("[Ethernet2] DHCP IP: ");
      Serial.println(Ethernet.localIP());
    } else {
      Serial.println("[Ethernet2] DHCP failed - trying static...");
      Ethernet.begin(mac, IPAddress(10,217,71,201));
      Serial.print("[Ethernet2] Static IP: ");
      Serial.println(Ethernet.localIP());
    }
  } else {
    Serial.println("[Ethernet2] Link is OFF!");
  }
}

void loop() {
  Serial.printf("[loop] linkStatus=%d\n", Ethernet.linkStatus());
  if (Ethernet.linkStatus() == LinkON) {
    Serial.printf("[loop] IP=%s\n", Ethernet.localIP().toString().c_str());
  }
  delay(3000);
}