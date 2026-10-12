// gateway/discovery.cpp — UDP-based service discovery implementation

#include "discovery.h"
#include "config.h"
#include <ArduinoJson.h>

void DiscoveryClient::loadBroadcastAddrs(std::vector<IPAddress>& addrs) {
  // Common broadcast addresses for different network classes
  addrs.push_back(IPAddress(255, 255, 255, 255));  // /8 - always works
  addrs.push_back(IPAddress(192, 168, 255, 255));  // /24
  addrs.push_back(IPAddress(10, 255, 255, 255));   // /8
  addrs.push_back(IPAddress(172, 31, 255, 255));   // /16
}

bool DiscoveryClient::sendQuery() {
  if (!udp_.begin(kDiscoveryPort)) {
    Serial.println("[discovery] UDP begin failed");
    return false;
  }
  
  // Build query packet
  String query = String(kDiscoveryMagic) + kDiscoveryQuery;
  uint8_t* packet = (uint8_t*)query.c_str();
  size_t len = query.length();
  
  std::vector<IPAddress> broadcastAddrs;
  loadBroadcastAddrs(broadcastAddrs);
  
  // Send to all broadcast addresses
  for (const auto& broadcastAddr : broadcastAddrs) {
    udp_.beginPacket(broadcastAddr, kDiscoveryPort);
    udp_.write(packet, len);
    udp_.endPacket();
    Serial.printf("[discovery] Sent query to %s\n", broadcastAddr.toString().c_str());
  }
  
  return true;
}

bool DiscoveryClient::waitForAnswer(char* out_host, size_t host_cap, uint16_t* out_port) {
  uint32_t start = millis();
  
  while (millis() - start < kDiscoveryTimeoutMs) {
    int packetSize = udp_.parsePacket();
    if (packetSize > 0) {
      char buffer[256];
      int len = udp_.read(buffer, sizeof(buffer) - 1);
      if (len > 0) {
        buffer[len] = '\0';
        
        // Check magic + answer prefix
        String magic = String(kDiscoveryMagic);
        String answer = String(kDiscoveryAnswer);
        
        if (String(buffer).startsWith(magic + answer)) {
          // Extract JSON payload after the magic + answer
          String payload = String(buffer).substring(magic.length() + answer.length());
          
          // Parse JSON: {"mqtt_host": "...", "mqtt_port": 1883}
          JsonDocument doc;
          DeserializationError err = deserializeJson(doc, payload);
          
          if (!err && doc.containsKey("mqtt_host")) {
            String host = doc["mqtt_host"].as<String>();
            uint16_t port = doc["mqtt_port"] | 1883;
            
            strncpy(out_host, host.c_str(), host_cap - 1);
            out_host[host_cap - 1] = '\0';
            *out_port = port;
            
            Serial.printf("[discovery] Found server: %s:%u\n", out_host, port);
            udp_.stop();
            return true;
          }
        }
      }
    }
    delay(50);  // Small delay to avoid busy-waiting
  }
  
  udp_.stop();
  return false;
}

bool DiscoveryClient::discover(const char* fallback_host, uint16_t fallback_port,
                               char* out_host, size_t host_cap, uint16_t* out_port) {
  Serial.println("[discovery] Starting service discovery...");
  
  // Try multiple times
  for (uint8_t attempt = 0; attempt < kDiscoveryRetries; attempt++) {
    Serial.printf("[discovery] Attempt %u/%u\n", attempt + 1, kDiscoveryRetries);
    
    if (sendQuery()) {
      if (waitForAnswer(out_host, host_cap, out_port)) {
        Serial.println("[discovery] Discovery successful!");
        return true;
      }
    }
    
    delay(1000);  // Wait before retry
  }
  
  // Fallback to configured values
  Serial.println("[discovery] Discovery failed, using fallback from config");
  strncpy(out_host, fallback_host, host_cap - 1);
  out_host[host_cap - 1] = '\0';
  *out_port = fallback_port;
  
  return false;  // Return false to indicate we used fallback
}