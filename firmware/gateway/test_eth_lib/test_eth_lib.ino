// Test with Ethernet library (different implementation)
#include <Arduino.h>
#include <Ethernet.h>
#include <SPI.h>

//Pin CS on W5500
#define W5500_CS 5

byte mac[] = {0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED};

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("\n=== Ethernet Library Test ===");
  
  // Initialize SPI with custom CS pin
  Serial.println("Initializing SPI with CS=5...");
  Ethernet.init(W5500_CS);
  
  // Try DHCP
  Serial.println("Trying Ethernet.begin() with DHCP...");
  if (Ethernet.begin(mac) == 1) {
    Serial.print("SUCCESS! IP: ");
    Serial.println(Ethernet.localIP());
  } else {
    Serial.println("DHCP failed, trying static IP...");
    Ethernet.begin(mac, IPAddress(10,217,71,205));
    Serial.print("Static IP: ");
    Serial.println(Ethernet.localIP());
  }
}

void loop() {
  Serial.printf("Link status: %d\n", Ethernet.linkStatus());
  if (Ethernet.linkStatus() == LinkON) {
    Serial.printf("IP: %s\n", Ethernet.localIP().toString().c_str());
  }
  delay(3000);
}