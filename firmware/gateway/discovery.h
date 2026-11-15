// gateway/discovery.h — UDP-based service discovery for auto-connect
// Works on the dedicated Ethernet LAN (ESP32-S3 + W5500).
//
// After DHCP, the gateway broadcasts "WHERE_ARE_YOU" on its Ethernet subnet
// and waits for "HERE_I_AM" with the HSE MQTT broker address.

#pragma once

#include <Arduino.h>
#include <NetworkUdp.h>
#include <vector>

// Must match the Python server constants
static const uint16_t kDiscoveryPort = 19198;
static const char kDiscoveryMagic[] = "ROZTASH_DISCOVERY";
static const char kDiscoveryQuery[] = "WHERE_ARE_YOU";
static const char kDiscoveryAnswer[] = "HERE_I_AM";
// DHCP and MQTT auto-discovery are both expected to answer on the local LAN.
static const uint16_t kDiscoveryTimeoutMs = 1500;
static const uint8_t kDiscoveryRetries = 2;

class DiscoveryClient {
 public:
  // Returns true if server was found, fills host/port
  // Falls back to config values if discovery fails
  bool discover(const char* fallback_host, uint16_t fallback_port,
                char* out_host, size_t host_cap, uint16_t* out_port);
  
 private:
  NetworkUDP udp_;
  bool sendQuery();
  bool waitForAnswer(char* out_host, size_t host_cap, uint16_t* out_port);
  void loadBroadcastAddrs(std::vector<IPAddress>& addrs);
};