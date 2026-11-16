// Fail-closed, monotonic policy state. No Arduino dependencies: host tested.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace roztash {
constexpr size_t kMaxPolicyMacs = 256;
constexpr uint32_t kDefaultHealthIntervalS = 600;
constexpr uint32_t kMaxHealthIntervalS = 86400;
constexpr uint32_t kSightingFreshMs = 60000;
using PolicyMac = std::array<char, 18>;

struct ScanPolicy {
  std::array<PolicyMac, kMaxPolicyMacs> active{};
  std::array<PolicyMac, kMaxPolicyMacs> health{};
  size_t active_count = 0;
  size_t health_count = 0;
  uint32_t health_interval_s = kDefaultHealthIntervalS;
  uint32_t lease_s = 0;
};

inline bool canonicalMac(const char* mac) {
  if (!mac || std::strlen(mac) != 17) return false;
  for (size_t i = 0; i < 17; ++i) {
    if (i % 3 == 2) { if (mac[i] != ':') return false; }
    else if (!((mac[i] >= '0' && mac[i] <= '9') ||
               (mac[i] >= 'a' && mac[i] <= 'f'))) return false;
  }
  return true;
}
inline bool containsMac(const PolicyMac* macs, size_t count, const char* mac) {
  if (!mac) return false;
  for (size_t i = 0; i < count; ++i)
    if (std::strcmp(macs[i].data(), mac) == 0) return true;
  return false;
}

class PolicyState {
 public:
  void apply(const ScanPolicy& policy, uint32_t now) {
    policy_ = policy;
    received_ms_ = now;
    ready_ = true;
  }
  void revoke() {
    ready_ = false;
    for (auto& mac : policy_.active) mac.fill(0);
    for (auto& mac : policy_.health) mac.fill(0);
    policy_.active_count = policy_.health_count = 0;
    policy_.lease_s = 0;
  }
  bool ready(uint32_t now) const {
    return ready_ && uint32_t(now - received_ms_) < policy_.lease_s * 1000UL;
  }
  bool scanEnabled(uint32_t now) const { return ready(now) && policy_.active_count; }
  bool allows(const char* mac, uint32_t now) const {
    return ready(now) && containsMac(policy_.active.data(), policy_.active_count, mac);
  }
  bool allowsHealth(const char* mac, uint32_t now) const {
    return allows(mac, now) && containsMac(policy_.health.data(), policy_.health_count, mac);
  }
  bool expire(uint32_t now) {
    if (!ready_ || ready(now)) return false;
    revoke();
    return true;
  }
  const ScanPolicy& policy() const { return policy_; }
 private:
  ScanPolicy policy_{};
  uint32_t received_ms_ = 0;
  bool ready_ = false;
};
}  // namespace roztash
