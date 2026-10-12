// gateway/discovery.h — UDP-based service discovery for auto-connect
// Works on any network: factory LAN, home WiFi, bridged networks.
//
// On startup, the gateway broadcasts "WHERE_ARE_YOU" and waits for
// "HERE_I_AM" response containing the server's MQTT address.

#pragma once

#include <WiFi.h>
#include <WiFiUdp.h>
#include <Arduino.h>
#include <vector>

// Must match the Python server constants
static const uint16_t kDiscoveryPort = 19198;
static const char kDiscoveryMagic[] = "ROZTASH_DISCOVERY";
static const char kDiscoveryQuery[] = "WHERE_ARE_YOU";
static const char kDiscoveryAnswer[] = "HERE_I_AM";
static const uint16_t kDiscoveryTimeoutMs = 10000;  // 10 seconds
static const uint8_t kDiscoveryRetries = 3;

class DiscoveryClient {
 public:
  // Returns true if server was found, fills host/port
  // Falls back to config values if discovery fails
  bool discover(const char* fallback_host, uint16_t fallback_port,
                char* out_host, size_t host_cap, uint16_t* out_port);
  
 private:
  WiFiUDP udp_;
  bool sendQuery();
  bool waitForAnswer(char* out_host, size_t host_cap, uint16_t* out_port);
  void loadBroadcastAddrs(std::vector<IPAddress>& addrs);
};