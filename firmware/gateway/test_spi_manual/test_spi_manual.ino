// Manual SPI test - read W5500 register directly
#include <Arduino.h>
#include <SPI.h>

#define W5500_CS 5

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("\n=== Manual SPI Test ===");
  
  // Manual SPI setup
  pinMode(W5500_CS, OUTPUT);
  digitalWrite(W5500_CS, HIGH);
  
  SPI.begin(18, 19, 23);  // SCK, MISO, MOSI
  // SPI.setClockDivider deprecated, use setFrequency
  SPI.setFrequency(1000000);  // 1MHz slow speed for testing
  
  // Try to read W5500 version register (0x0000)
  Serial.println("Reading W5500 version register...");
  
  digitalWrite(W5500_CS, LOW);
  SPI.transfer(0x00);  // Address high
  SPI.transfer(0x00);  // Address low  
  SPI.transfer(0x01);  // Read Mode
  uint8_t version = SPI.transfer(0x00);
  digitalWrite(W5500_CS, HIGH);
  
  Serial.print("Version Register = 0x");
  Serial.println(version, HEX);
  
  if (version == 0x04) {
    Serial.println("✅ W5500 DETECTED!");
  } else if (version == 0x00) {
    Serial.println("❌ NO RESPONSE - check wiring!");
  } else {
    Serial.print("❓ UNKNOWN CHIP: ");
    Serial.println(version, HEX);
  }
}

void loop() {
  delay(5000);
}