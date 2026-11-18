#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>

namespace roztash {
inline constexpr char kGatewayDiscoveryQuery[] = "ROZTASH_GATEWAY_DISCOVERYWHO_IS_THERE";
inline constexpr char kGatewayDiscoveryAnswer[] = "ROZTASH_GATEWAY_DISCOVERYGATEWAY_HERE";
inline constexpr uint16_t kGatewayDiscoveryPort = 19199;

struct GatewayDiscoveryInfo {
  const char* gw;
  const char* mac;
  const char* fw;
  const char* ip;
  bool mqtt_connected;
};

inline bool gatewayDiscoveryToken(const char* value, size_t size, size_t min_size = 1) {
  if (!value || size < min_size || size > 63) return false;
  for (size_t i = 0; i < size; ++i)
    if (!((value[i] >= 'a' && value[i] <= 'z') ||
          (value[i] >= 'A' && value[i] <= 'Z') ||
          (value[i] >= '0' && value[i] <= '9') || value[i] == '-' ||
          value[i] == ':' || value[i] == '.' || value[i] == '_')) return false;
  return true;
}

inline bool buildGatewayDiscoveryReply(const char* request, size_t request_len,
                                       const GatewayDiscoveryInfo& info,
                                       char* out, size_t cap, size_t& written) {
  written = 0;
  if (!request || request_len != sizeof(kGatewayDiscoveryQuery) - 1 ||
      std::memcmp(request, kGatewayDiscoveryQuery, request_len) != 0 || !out ||
      !gatewayDiscoveryToken(info.gw, info.gw ? std::strlen(info.gw) : 0) ||
      !gatewayDiscoveryToken(info.mac, info.mac ? std::strlen(info.mac) : 0, 17) ||
      !gatewayDiscoveryToken(info.fw, info.fw ? std::strlen(info.fw) : 0) ||
      !gatewayDiscoveryToken(info.ip, info.ip ? std::strlen(info.ip) : 0)) return false;
  const int n = std::snprintf(out, cap, "%s{\"v\":1,\"gw\":\"%s\",\"mac\":\"%s\","
                              "\"fw\":\"%s\",\"ip\":\"%s\",\"transport\":\"ethernet\","
                              "\"mqtt_connected\":%s}",
                              kGatewayDiscoveryAnswer, info.gw, info.mac, info.fw, info.ip,
                              info.mqtt_connected ? "true" : "false");
  if (n < 0 || static_cast<size_t>(n) >= cap) return false;
  written = static_cast<size_t>(n);
  return true;
}
}  // namespace roztash
