// Production BleCentral diagnostic logic against hardware-boundary doubles.
#include "ble_central.h"
#include <cassert>
#include <cstdio>
#include <cstring>

static constexpr const char* A = "aa:bb:cc:dd:ee:01";
static constexpr const char* X = "ff:ee:dd:cc:bb:aa";

static void reset_fake_scan() {
  NimBLEDevice::scan = NimBLEScan{};
  NimBLEDevice::client_idx = 0;
  NimBLEClient::connect_calls = 0;
  NimBLEClient::connect_ok = true;
  NimBLERemoteCharacteristic::read_value.clear();
  NimBLERemoteCharacteristic::read_calls = 0;
  NimBLERemoteCharacteristic::subscribe_calls = 0;
  NimBLERemoteCharacteristic::on_write = nullptr;
  fake_control_task_available = true;
  fake_ms = 1000;
}

static const BleCentral::Sighting& diagnostic_entry(const BleCentral::Sighting* entries,
                                                     int count, const char* mac) {
  for (int i = 0; i < count; ++i)
    if (entries[i].used && std::strcmp(entries[i].mac, mac) == 0) return entries[i];
  assert(false && "missing diagnostic sighting");
  return entries[0];
}

static void diagnostic_scan_is_bounded_and_policy_independent() {
  reset_fake_scan();
  BleCentral ble;
  ble.begin(160, 80, 45000);
  ble.poll();
  assert(!NimBLEDevice::scan.scanning);

  NimBLEAdvertisedDevice a(A, -40), x(X, -55);
  NimBLEDevice::scan.callback->onResult(&a);
  NimBLEDevice::scan.callback->onResult(&x);
  assert(a.rssi_reads == 0 && x.rssi_reads == 0);
  assert(ble.sightingCount() == 0 && ble.advCount() == 0);

  assert(ble.startDiagnosticScan());
  ble.poll();
  assert(ble.diagnosticScanActive() && !ble.diagnosticScanFinished());
  assert(NimBLEDevice::scan.scanning && !NimBLEDevice::scan.active);
  NimBLEDevice::scan.callback->onResult(&a);
  NimBLEDevice::scan.callback->onResult(&x);
  NimBLEAdvertisedDevice stronger(A, -35);
  NimBLEDevice::scan.callback->onResult(&stronger);
  assert(a.rssi_reads == 1 && x.rssi_reads == 1 && stronger.rssi_reads == 1);
  assert(ble.diagnosticSightingCount() == 2);
  assert(ble.sightingCount() == 0 && ble.advCount() == 0);
  assert(!ble.hasFreshSighting(X, fake_ms));
  assert(ble.hasFreshDiagnosticSighting(X, fake_ms));

  BleCentral::Sighting entries[BleCentral::kMaxDiagnosticDevices];
  for (int i = 0; i < BleCentral::kMaxDiagnosticDevices; ++i)
    assert(ble.getDiagnosticSlot(i, entries[i]));
  assert(diagnostic_entry(entries, ble.diagnosticSightingCount(), A).rssi == -35);
  assert(diagnostic_entry(entries, ble.diagnosticSightingCount(), X).rssi == -55);

  fake_ms = 8999;
  ble.poll();
  assert(ble.diagnosticScanActive() && !ble.diagnosticScanFinished());
  fake_ms = 9000;
  ble.poll();
  assert(!ble.diagnosticScanActive() && ble.diagnosticScanFinished());
  assert(!NimBLEDevice::scan.scanning);
  assert(ble.diagnosticSightingCount() == 2);
  assert(ble.hasFreshDiagnosticSighting(X, 61000));
  assert(!ble.hasFreshDiagnosticSighting(X, 61001));

  assert(ble.startDiagnosticScan());
  for (int i = 0; i < BleCentral::kMaxDiagnosticDevices + 8; ++i) {
    char mac[18];
    std::snprintf(mac, sizeof mac, "02:00:00:00:00:%02x", i);
    NimBLEAdvertisedDevice adv(mac, -60);
    NimBLEDevice::scan.callback->onResult(&adv);
  }
  assert(ble.diagnosticSightingCount() == BleCentral::kMaxDiagnosticDevices);
}

static void diagnostic_and_employee_sightings_stay_separate_on_revocation() {
  reset_fake_scan();
  BleCentral ble;
  ble.begin(160, 80, 45000);
  roztash::ScanPolicy policy;
  policy.lease_s = 90;
  policy.active_count = policy.health_count = 1;
  std::strcpy(policy.active[0].data(), A);
  policy.health[0] = policy.active[0];
  ble.setScanPolicy(policy, fake_ms);
  assert(ble.startDiagnosticScan());
  ble.poll();

  NimBLEAdvertisedDevice a(A, -40), x(X, -55);
  NimBLEDevice::scan.callback->onResult(&a);
  NimBLEDevice::scan.callback->onResult(&x);
  assert(ble.diagnosticSightingCount() == 2);
  assert(ble.sightingCount() == 1 && ble.advCount() == 1);
  assert(!ble.hasFreshSighting(X, fake_ms));

  ble.stopScanPolicy();
  ble.poll();
  assert(ble.diagnosticScanActive() && NimBLEDevice::scan.scanning);
  assert(ble.diagnosticSightingCount() == 2);
  assert(ble.sightingCount() == 0 && ble.advCount() == 1);
  fake_ms += 8000;
  ble.poll();
  assert(ble.diagnosticScanFinished() && !NimBLEDevice::scan.scanning);
}

struct WorkerFinished {};
static bool worker_started;
static void run_one_job() {
  worker_started = false;
  fake_wait = [] { if (worker_started) throw WorkerFinished{}; worker_started = true; };
  fake_delay = [](uint32_t ms) { fake_ms += ms; assert(fake_ms < 20000); };
  try { fake_worker(fake_worker_arg); }
  catch (const WorkerFinished&) {}
  fake_wait = nullptr;
  fake_delay = nullptr;
  NimBLERemoteCharacteristic::on_write = nullptr;
}

static void diagnostic_probe_connects_and_reads_only_standard_battery() {
  reset_fake_scan();
  BleCentral ble;
  ble.begin(160, 80, 45000);
  NimBLEAdvertisedDevice normal_only(A, -40);
  NimBLEDevice::scan.callback->onResult(&normal_only);
  assert(!ble.startDiagnosticProbe(A));  // employee sightings are not diagnostic grants

  assert(ble.startDiagnosticScan());
  NimBLEAdvertisedDevice target(X, -55);
  NimBLEDevice::scan.callback->onResult(&target);
  assert(!ble.startDiagnosticProbe(X));  // the discovery window must finish first
  fake_ms += 8000;
  ble.poll();
  assert(ble.diagnosticScanFinished());
  roztash::ScanPolicy policy;
  policy.lease_s = 90;
  policy.active_count = policy.health_count = 1;
  std::strcpy(policy.active[0].data(), X);
  policy.health[0] = policy.active[0];
  ble.setScanPolicy(policy, fake_ms);  // even a listed MAC is not monitoring work here

  NimBLERemoteCharacteristic::read_value = std::string(1, static_cast<char>(77));
  unsigned writes = 0;
  NimBLERemoteCharacteristic::on_write = [&](auto&, const uint8_t*, size_t) { ++writes; };
  assert(ble.startDiagnosticProbe(X));
  assert(ble.healthBusy() && !ble.monitoringJobActive());
  assert(!ble.startDiagnosticProbe(X));  // the single worker is already owned
  ble.stopScanPolicy();  // employee revocation does not cancel owner diagnostics
  run_one_job();

  assert(ble.jobFinished() && ble.state() == BleCentral::JobState::Done);
  assert(ble.wasDiagnosticProbe() && !ble.wasVibrate() && !ble.wasManualMeasure());
  assert(ble.vitals().battery_ok && ble.vitals().battery == 77);
  assert(NimBLEClient::connect_calls == 1);
  assert(NimBLERemoteCharacteristic::read_calls == 1);
  assert(NimBLERemoteCharacteristic::subscribe_calls == 0);
  assert(writes == 0 && ble.sampleCount() == 0 && ble.vibrateAcks() == 0);
  assert(!ble.jobRevoked() && ble.sightingCount() == 0 && ble.advCount() == 0);
  ble.clearJob();
  assert(!ble.wasDiagnosticProbe());
}

static void diagnostic_probe_battery_is_optional_and_validated() {
  reset_fake_scan();
  BleCentral ble;
  ble.begin(160, 80, 45000);
  assert(ble.startDiagnosticScan());
  NimBLEAdvertisedDevice target(X, -55);
  NimBLEDevice::scan.callback->onResult(&target);
  fake_ms += 8000;
  ble.poll();

  NimBLERemoteCharacteristic::read_value.clear();  // no readable battery value
  assert(ble.startDiagnosticProbe(X));
  run_one_job();
  assert(ble.state() == BleCentral::JobState::Done && !ble.vitals().battery_ok);
  assert(NimBLERemoteCharacteristic::subscribe_calls == 0);
  ble.clearJob();

  NimBLERemoteCharacteristic::read_value = std::string(1, static_cast<char>(101));
  assert(ble.startDiagnosticProbe(X));
  run_one_job();
  assert(ble.state() == BleCentral::JobState::Done && !ble.vitals().battery_ok);
  assert(NimBLERemoteCharacteristic::read_calls == 2);
  ble.clearJob();
}

static void diagnostic_probe_reports_connect_failure_and_rejects_stale_targets() {
  reset_fake_scan();
  BleCentral ble;
  ble.begin(160, 80, 45000);
  assert(ble.startDiagnosticScan());
  NimBLEAdvertisedDevice target(X, -55);
  NimBLEDevice::scan.callback->onResult(&target);
  fake_ms += 8000;
  ble.poll();

  NimBLEClient::connect_ok = false;
  assert(ble.startDiagnosticProbe(X));
  run_one_job();
  assert(ble.jobFinished() && ble.state() == BleCentral::JobState::Failed);
  assert(ble.failure() == BleCentral::Fail::Connect);
  assert(!ble.vitals().battery_ok && NimBLERemoteCharacteristic::read_calls == 0);
  assert(NimBLERemoteCharacteristic::subscribe_calls == 0);
  ble.clearJob();

  fake_ms += 60001;
  NimBLEClient::connect_ok = true;
  assert(!ble.hasFreshDiagnosticSighting(X, fake_ms));
  assert(!ble.startDiagnosticProbe(X) && !ble.healthBusy());
}

static void diagnostic_scan_needs_its_bounded_control_task() {
  reset_fake_scan();
  fake_control_task_available = false;
  BleCentral ble;
  ble.begin(160, 80, 45000);
  assert(!ble.startDiagnosticScan());
  assert(!ble.diagnosticScanActive() && !NimBLEDevice::scan.scanning);
  assert(!ble.startDiagnosticProbe(X));
}

int main() {
  diagnostic_scan_is_bounded_and_policy_independent();
  diagnostic_and_employee_sightings_stay_separate_on_revocation();
  diagnostic_probe_connects_and_reads_only_standard_battery();
  diagnostic_probe_battery_is_optional_and_validated();
  diagnostic_probe_reports_connect_failure_and_rejects_stale_targets();
  diagnostic_scan_needs_its_bounded_control_task();
  std::puts("diagnostic_ble_host_test: scan, policy separation and battery-only probe PASS");
}
