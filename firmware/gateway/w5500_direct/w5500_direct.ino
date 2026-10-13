// Direct manual SPI test of W5500 - no libraries
#include <Arduino.h>
#include <SPI.h>

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("\n=== Manual W5500 SPI Test ===");
  
  // Initialize SPI manually on HSPI
  // SCK=14, MISO=12, MOSI=13, CS=5
  SPI.begin(14, 12, 13, 5);
  Serial.println("SPI initialized on HSPI");
  
  // Try to read W5500 PHY register (0x002F - PHYCFGR)
  // W5500 should respond with something like 0x0C00 if working
  for (int i = 0; i < 5; i++) {
    Serial.printf("\n--- Attempt %d ---\n", i+1);
    
    // Set CS low
    digitalWrite(5, LOW);
    
    // Read PHY register 0x002F (PHY configuration)
    SPI.transfer(0x00);  // Address high
    SPI.transfer(0x2F);  // Address low
    SPI.transfer(0x01);  // Read mode
    
    uint8_t b1 = SPI.transfer(0x00);  // Data high
    uint8_t b2 = SPI.transfer(0x00);  // Data low
    
    // Set CS high
    digitalWrite(5, HIGH);
    
    Serial.printf("PHYCFGR = 0x%02X%02X\n", b1, b2);
    
    if (b1 != 0xFF && b2 != 0xFF) {
      Serial.println("*** Device responds! ***");
    } else {
      Serial.println("No response (0xFF 0xFF)");
    }
    
    delay(1000);
  }
  
  Serial.println("\n=== Test Complete ===");
}

void loop() {
  delay(1000);
}