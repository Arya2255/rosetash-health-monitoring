#pragma once
#include "scan_policy.h"
namespace roztash {
// Main-loop only. A window snapshots assigned MACs, never sighting slot indices.
// Start-to-start cadence; an overlong window finishes before another can start.
// Refreshes update the next interval without moving the current window's epoch.
class HealthSchedule {
 public:
  void sync(const PolicyState& state, uint32_t now) {
    if (!state.ready(now) || state.policy().health_count == 0) {
      enabled_ = active_ = false;
      count_ = cursor_ = 0;
      return;
    }
    interval_ms_ = state.policy().health_interval_s * 1000UL;
    if (!enabled_) {
      enabled_ = true;
      started_ms_ = now;
    }
    // A removal stays removed for this snapshot even if later re-added.
    for (size_t i = cursor_; i < count_; ++i)
      if (!state.allowsHealth(snapshot_[i].data(), now)) snapshot_[i][0] = 0;
  }
  bool openIfDue(const PolicyState& state, uint32_t now) {
    sync(state, now);
    if (!enabled_ || active_ || uint32_t(now - started_ms_) < interval_ms_) return false;
    started_ms_ = now;
    ++generation_;
    count_ = state.policy().health_count;
    for (size_t i = 0; i < count_; ++i) snapshot_[i] = state.policy().health[i];
    cursor_ = 0;
    active_ = true;
    return true;
  }
  bool next(const PolicyState& state, uint32_t now, PolicyMac& out) {
    sync(state, now);
    if (!active_) return false;
    while (cursor_ < count_) {
      const PolicyMac& mac = snapshot_[cursor_++];
      if (state.allowsHealth(mac.data(), now)) { out = mac; return true; }
    }
    active_ = false;
    return false;
  }
  bool active() const { return active_; }
  uint32_t generation() const { return generation_; }
 private:
  std::array<PolicyMac, kMaxPolicyMacs> snapshot_{};
  size_t cursor_ = 0, count_ = 0;
  uint32_t started_ms_ = 0, interval_ms_ = kDefaultHealthIntervalS * 1000UL;
  uint32_t generation_ = 0;
  bool enabled_ = false, active_ = false;
};
}  // namespace roztash
