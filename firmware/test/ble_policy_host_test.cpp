// Executes production BleCentral against hardware-boundary doubles only.
// These checks prove gating/lifecycle logic, not BLE radio/task scheduling.
#include "ble_central.h"
#include <cassert>
#include <cstdio>
#include <cstring>

static constexpr const char* A = "aa:bb:cc:dd:ee:01";
static constexpr const char* X = "ff:ee:dd:cc:bb:aa";
static roztash::ScanPolicy policy() {
  roztash::ScanPolicy p;
  p.lease_s = 5;
  p.active_count = p.health_count = 256;
  for (int i = 0; i < 256; ++i) {
    std::snprintf(p.active[i].data(), p.active[i].size(), "aa:bb:cc:dd:ee:%02x", i);
    p.health[i] = p.active[i];
  }
  return p;
}
int main() {
  BleCentral ble;
  auto& scan = NimBLEDevice::scan;
  fake_ms = 1000;
  ble.begin(160, 80, 45000);
  ble.poll();
  assert(!scan.scanning && !scan.active && scan.max_results == 0);
  NimBLEAdvertisedDevice excluded(X, -30), allowed(A, -40);
  scan.callback->onResult(&excluded);
  scan.callback->onResult(&allowed);
  assert(excluded.rssi_reads == 0 && allowed.rssi_reads == 0 && ble.advCount() == 0);
  assert(!ble.startVibrate(A));
  auto p = policy();
  ble.setScanPolicy(p, fake_ms);
  ble.poll();
  assert(scan.scanning && ble.scanEnabled());
  scan.callback->onResult(&excluded);
  assert(excluded.rssi_reads == 0);
  for (const auto& mac : p.active) {
    // No name or UUID APIs exist in this double: a permitted MAC suffices.
    NimBLEAdvertisedDevice adv(mac.data(), -50);
    scan.callback->onResult(&adv);
    assert(adv.rssi_reads == 1);
  }
  assert(ble.sightingCount() == 256 && ble.advCount() == 256);
  assert(ble.hasFreshSighting(A, fake_ms));
  assert(!ble.startVibrate(X));
  assert(ble.startHealth(A));
  fake_ms = 2000;
  ble.setScanPolicy(p, fake_ms);
  assert(!ble.jobRevoked());
  p.health_count = 0; // assignment revoked but still on duty for presence
  fake_ms = 2100;
  ble.setScanPolicy(p, fake_ms);
  assert(ble.jobRevoked());
  ble.stopScanPolicy();
  ble.poll();
  assert(!scan.scanning && ble.sightingCount() == 0);
  assert(!ble.startVibrate(A));
  const auto starts = scan.starts;
  fake_ms = 4000;
  ble.poll();
  assert(scan.starts == starts); // watchdog cannot reopen a revoked scan
  p.active_count = p.health_count = 0;
  ble.setScanPolicy(p, fake_ms); ble.poll();
  assert(ble.policyReady() && !scan.scanning);
  p = policy();
  fake_ms = UINT32_MAX - 999;
  ble.setScanPolicy(p, fake_ms); ble.poll();
  scan.callback->onResult(&allowed);
  const auto advs = ble.advCount();
  fake_ms = 4000; // exact 5s lease expiry over wraparound
  scan.callback->onResult(&allowed);
  assert(ble.advCount() == advs); // expiry gates callback before monitor runs
  ble.poll();
  assert(!ble.policyReady() && !scan.scanning && ble.sightingCount() == 0);
  std::puts("ble_policy_host_test: PASS (boot, passive filter, 256 sightings, revoke, empty, expiry, watchdog, job/command gating)");
}
