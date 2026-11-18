// gateway/discovery.cpp — UDP service discovery clients and responder.
#include "discovery.h"
#include "config.h"
#include "network_config.h"
#include <ArduinoJson.h>
#include <NetworkUdp.h>
#include <ETH.h>

bool DiscoveryClient::start() {
  if (active_) return true;
  if (!sendQuery()) return false;
  active_ = true;
  started_ms_ = millis();
  return true;
}

DiscoveryClient::PollResult DiscoveryClient::poll(char* out_host, size_t host_cap,
                                                   uint16_t* out_port) {
  if (!active_) return PollResult::Idle;
  const int packet_size = udp_.parsePacket();
  if (packet_size > 0) {
    char buffer[256];
    const int len = udp_.read(buffer, sizeof(buffer) - 1);
    if (len >= 0) buffer[len] = '\0';
    const String prefix = String(kDiscoveryMagic) + kDiscoveryAnswer;
    if (len > 0 && static_cast<size_t>(len) >= prefix.length() &&
        String(buffer).startsWith(prefix)) {
      const String payload = String(buffer).substring(prefix.length());
      JsonDocument doc;
      if (!deserializeJson(doc, payload) && doc["mqtt_host"].is<const char*>()) {
        const String host = udp_.remoteIP().toString();
        const uint32_t candidate_port = doc["mqtt_port"] | roztash::kMqttPort;
        if (out_host && host_cap > 0 && out_port && candidate_port > 0 &&
            candidate_port <= UINT16_MAX) {
          const size_t n = host.length() < host_cap - 1 ? host.length() : host_cap - 1;
          memcpy(out_host, host.c_str(), n);
          out_host[n] = '\0';
          *out_port = static_cast<uint16_t>(candidate_port);
          udp_.stop();
          active_ = false;
          return PollResult::Success;
        }
      }
    }
    udp_.clear();
  }
  if (uint32_t(millis() - started_ms_) >= kDiscoveryTimeoutMs) {
    udp_.stop();
    active_ = false;
    return PollResult::Failure;
  }
  return PollResult::Pending;
}

void DiscoveryClient::cancel() {
  if (active_) udp_.stop();
  active_ = false;
}

bool GatewayDiscoveryResponder::begin(const char* gw, const char* fw) {
  if (active_) return true;
  if (!ETH.hasIP()) return false;
  strncpy(gw_, gw ? gw : "", sizeof(gw_) - 1);
  gw_[sizeof(gw_) - 1] = '\0';
  strncpy(fw_, fw ? fw : "", sizeof(fw_) - 1);
  fw_[sizeof(fw_) - 1] = '\0';
  if (!udp_.begin(roztash::kGatewayDiscoveryPort)) return false;
  active_ = true;
  Serial.printf("[discovery] gateway responder listening on UDP %u\n",
                static_cast<unsigned>(roztash::kGatewayDiscoveryPort));
  return true;
}

void GatewayDiscoveryResponder::poll(bool mqtt_connected) {
  if (!active_ || !ETH.hasIP()) return;
  const int packet_size = udp_.parsePacket();
  if (packet_size <= 0) return;
  char request[sizeof(roztash::kGatewayDiscoveryQuery)];
  const int len = udp_.read(request, sizeof(request));
  const IPAddress peer = udp_.remoteIP();
  const uint16_t peer_port = udp_.remotePort();
  udp_.clear();
  if (packet_size != static_cast<int>(sizeof(roztash::kGatewayDiscoveryQuery) - 1) ||
      len != packet_size) return;
  const String mac = ETH.macAddress();
  const String ip = ETH.localIP().toString();
  roztash::GatewayDiscoveryInfo info{gw_, mac.c_str(), fw_, ip.c_str(), mqtt_connected};
  char response[384];
  size_t response_len = 0;
  if (!roztash::buildGatewayDiscoveryReply(request, static_cast<size_t>(len), info,
                                           response, sizeof(response), response_len)) return;
  if (udp_.beginPacket(peer, peer_port)) {
    udp_.write(reinterpret_cast<const uint8_t*>(response), response_len);
    udp_.endPacket();
  }
}

void GatewayDiscoveryResponder::stop() {
  if (active_) udp_.stop();
  active_ = false;
}

void DiscoveryClient::loadBroadcastAddrs(std::vector<IPAddress>& addrs) {
  if (!ETH.hasIP()) return;
  addrs.push_back(ETH.broadcastIP());
  addrs.push_back(IPAddress(255, 255, 255, 255));
}

bool DiscoveryClient::sendQuery() {
  if (!udp_.begin(kDiscoveryPort)) {
    Serial.println("[discovery] UDP begin failed");
    return false;
  }
  const String query = String(kDiscoveryMagic) + kDiscoveryQuery;
  const auto* packet = reinterpret_cast<const uint8_t*>(query.c_str());
  const size_t len = query.length();
  std::vector<IPAddress> broadcast_addrs;
  loadBroadcastAddrs(broadcast_addrs);
  if (broadcast_addrs.empty()) {
    udp_.stop();
    return false;
  }
  for (const auto& address : broadcast_addrs) {
    if (!udp_.beginPacket(address, kDiscoveryPort)) continue;
    udp_.write(packet, len);
    udp_.endPacket();
  }
  return true;
}
