// Simple SPI scanner to find W5500
#include <Arduino.h>
#include <SPI.h>

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("");
  Serial.println("[SPI Scanner] Starting...");
  
  // Initialize SPI
  SPI.begin(18, 19, 23, 4);
  Serial.println("[SPI Scanner] SPI.begin() done");
  
  // Try to read W5500 Register (Common Register: 0x0000 - Mode Register)
  Serial.println("[SPI Scanner] Trying to read W5500 MODE register...");
  
  for (int cs_pin = 2; cs_pin <= 5; cs_pin++) {
    Serial.printf("\n=== CS pin = %d ===\n", cs_pin);
    
    pinMode(cs_pin, OUTPUT);
    digitalWrite(cs_pin, HIGH);
    
    // Read 2 bytes from register 0x0000
    digitalWrite(cs_pin, LOW);
    SPI.transfer(0x00);  // Address byte 1 (0x0000 = 0x0000)
    SPI.transfer(0x00);  // Address byte 2
    SPI.transfer(0x00);  // Control byte: read mode
    uint8_t b1 = SPI.transfer(0x00);  // Read high byte
    uint8_t b2 = SPI.transfer(0x00);  // Read low byte
    digitalWrite(cs_pin, HIGH);
    
    Serial.printf("Result: 0x%02X 0x%02X\n", b1, b2);
    
    // W5500 should return 0x0000 or similar if present
    if (b1 != 0xFF && b2 != 0xFF) {
      Serial.println("FOUND DEVICE!");
    } else {
      Serial.println("No response (0xFF 0xFF)");
    }
    
    delay(200);
  }
  
  Serial.println("\n=== DONE ===");
}

void loop() {
  delay(1000);
}