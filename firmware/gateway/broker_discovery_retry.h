#pragma once

#include "scan_policy.h"
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace roztash {
struct BrokerDiscoveryRetry {
  static constexpr uint32_t kRetryMs = 1000;
  static constexpr uint32_t kRevalidateMs = 60000;
  bool due(uint32_t now) const {
    if (force_due_) return true;
    return !resolved_ ? uint32_t(now - last_attempt_ms_) >= next_delay_ms_
                      : uint32_t(now - last_success_ms_) >= kRevalidateMs;
  }
  void recordFailure(uint32_t now) {
    resolved_ = false;
    force_due_ = false;
    last_attempt_ms_ = now;
    next_delay_ms_ = kRetryMs;
  }
  void recordSuccess(const char* host, uint16_t port, uint32_t now) {
    const char* value = host ? host : "";
    const size_t n = std::strlen(value);
    const size_t copy = n < sizeof host_ - 1 ? n : sizeof host_ - 1;
    std::memcpy(host_, value, copy);
    host_[copy] = '\0';
    port_ = port;
    resolved_ = true;
    force_due_ = false;
    last_success_ms_ = now;
    last_attempt_ms_ = now;
    next_delay_ms_ = kRetryMs;
  }
  void networkLost() { network_ready_ = false; }
  void networkReady() { network_ready_ = true; force_due_ = true; }
  bool brokerResolved() const { return resolved_; }
  bool networkReadyState() const { return network_ready_; }
  void broker(char* host, size_t cap, uint16_t& port,
              const char* fallback_host, uint16_t fallback_port) const {
    const char* selected = resolved_ ? host_ : fallback_host;
    if (!cap) return;
    const size_t n = std::strlen(selected ? selected : "");
    const size_t copy = n < cap - 1 ? n : cap - 1;
    std::memcpy(host, selected ? selected : "", copy);
    host[copy] = '\0';
    port = resolved_ ? port_ : fallback_port;
  }
 private:
  char host_[48]{};
  uint16_t port_ = 0;
  uint32_t last_attempt_ms_ = 0;
  uint32_t last_success_ms_ = 0;
  uint32_t next_delay_ms_ = 0;
  bool resolved_ = false;
  bool network_ready_ = false;
  bool force_due_ = true;
};
}  // namespace roztash
