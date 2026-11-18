// gateway/discovery.h — UDP-based service discovery for auto-connect
// Works on the dedicated Ethernet LAN (ESP32-S3 + W5500).
//
// After DHCP, the gateway broadcasts "WHERE_ARE_YOU" on its Ethernet subnet
// and waits for "HERE_I_AM" with the HSE MQTT broker address.

#pragma once

#include <Arduino.h>
#include <NetworkUdp.h>
#include <vector>
#include "gateway_discovery_protocol.h"

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
  enum class PollResult : uint8_t { Idle, Pending, Success, Failure };
  bool start();
  PollResult poll(char* out_host, size_t host_cap, uint16_t* out_port);
  void cancel();
  bool active() const { return active_; }
 private:
  NetworkUDP udp_;
  bool sendQuery();
  void loadBroadcastAddrs(std::vector<IPAddress>& addrs);
  bool active_ = false;
  uint32_t started_ms_ = 0;
};

// Separate LAN discovery protocol for the Python client/API. It never shares
// port 19198, and poll() only performs nonblocking UDP work.
class GatewayDiscoveryResponder {
 public:
  bool begin(const char* gw, const char* fw);
  void poll(bool mqtt_connected);
  void stop();
  bool active() const { return active_; }
 private:
  NetworkUDP udp_;
  char gw_[24] = {0};
  char fw_[64] = {0};
  bool active_ = false;
};