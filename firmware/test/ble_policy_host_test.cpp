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
static void scan_and_job_policy() {
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
}

struct WorkerFinished {};
static bool worker_started;

static void run_one_job() {
  worker_started = false;
  fake_wait = [] { if (worker_started) throw WorkerFinished{}; worker_started = true; };
  fake_delay = [](uint32_t ms) { fake_ms += ms; assert(fake_ms < 11000); };
  try { fake_worker(fake_worker_arg); }
  catch (const WorkerFinished&) {}
  fake_wait = nullptr;
  fake_delay = nullptr;
  NimBLERemoteCharacteristic::on_write = nullptr;
}

static void prepare_vibration(BleCentral& ble, uint8_t completed = 0) {
  fake_ms = 1000;
  ble.begin(160, 80, 45000);
  auto p = policy();
  p.lease_s = 90;
  ble.setScanPolicy(p, fake_ms);
  NimBLEAdvertisedDevice allowed(A, -40);
  NimBLEDevice::scan.callback->onResult(&allowed);
  assert(ble.startVibrate(A, false, 3, completed));
}

static void verify_find_write(const uint8_t* data, size_t len) {
  fundo::Parsed request;
  assert(fundo::parseFrame(data, len, request) && request.crc_ok);
  assert(request.cmd1 == fundo::CMD_FIND_DEVICE && request.cmd2 == fundo::SUB_FIND_DEVICE);
  assert(request.data_len == 0);
}

static void notify_ack(NimBLERemoteCharacteristic& ch, uint8_t status = 0) {
  uint8_t frame[16];
  const auto len = fundo::buildFrame(0, fundo::CMD_FIND_DEVICE, fundo::SUB_FIND_DEVICE, &status, 1, frame);
  frame[1] = 0x31; // band direction; CRC covers the inner frame only
  ch.notify(frame, len);
}

static void non_ack_reply_does_not_advance_the_pulse_train() {
  BleCentral ble;
  prepare_vibration(ble);
  unsigned writes = 0;
  NimBLERemoteCharacteristic::on_write = [&](auto& ch, const uint8_t* data, size_t len) {
    verify_find_write(data, len);
    ++writes;
    notify_ack(ch, 1);
  };
  run_one_job();
  assert(writes == 1 && ble.vibrateAcks() == 0);
  assert(ble.jobFinished() && ble.failure() == BleCentral::Fail::Timeout);
}

static void queued_ack_survives_revocation_without_sending_again() {
  BleCentral ble;
  prepare_vibration(ble, 1);
  unsigned writes = 0;
  NimBLERemoteCharacteristic::on_write = [&](auto& ch, const uint8_t* data, size_t len) {
    verify_find_write(data, len);
    ++writes;
    notify_ack(ch);
    ble.stopScanPolicy();
  };
  run_one_job();
  assert(writes == 1 && ble.vibrateAcks() == 2);
  assert(ble.jobFinished() && ble.jobRevoked());
}

static void three_writes_need_three_distinct_pending_acknowledgements() {
  BleCentral ble;
  prepare_vibration(ble);
  std::vector<uint32_t> writes;
  NimBLERemoteCharacteristic::on_write = [&](auto& ch, const uint8_t* data, size_t len) {
    verify_find_write(data, len);
    writes.push_back(fake_ms);
    notify_ack(ch);
    notify_ack(ch); // duplicate in the same notification burst
  };
  run_one_job();
  assert(writes.size() == 3 && ble.vibrateAcks() == 3);
  assert(writes[1] - writes[0] >= 250 && writes[2] - writes[1] >= 250);
  assert(ble.jobFinished() && ble.state() == BleCentral::JobState::Done);
}

static void resume_two_completed_pulses_writes_only_once() {
  BleCentral ble;
  prepare_vibration(ble, 2);
  unsigned writes = 0;
  NimBLERemoteCharacteristic::on_write = [&](auto& ch, const uint8_t* data, size_t len) {
    verify_find_write(data, len);
    ++writes;
    notify_ack(ch);
  };
  run_one_job();
  assert(writes == 1 && ble.vibrateAcks() == 3 && ble.vibrated());
}

static void invalid_frames_leave_the_current_write_pending() {
  BleCentral ble;
  prepare_vibration(ble);
  unsigned writes = 0;
  NimBLERemoteCharacteristic::on_write = [&](auto& ch, const uint8_t* data, size_t len) {
    verify_find_write(data, len);
    ++writes;
    uint8_t frame[16];
    auto size = fundo::buildFrame(0, fundo::CMD_FIND_DEVICE, fundo::SUB_FIND_DEVICE, nullptr, 0, frame);
    ch.notify(frame, size);
    uint8_t status = 0;
    size = fundo::buildFrame(0, fundo::CMD_FIND_DEVICE, fundo::SUB_FIND_DEVICE, &status, 1, frame);
    frame[4] ^= 1;
    ch.notify(frame, size);
  };
  run_one_job();
  assert(writes == 1 && ble.vibrateAcks() == 0 && !ble.vibrated());
}

static void accepted_ack_counts_even_if_the_link_has_disconnected() {
  BleCentral ble;
  prepare_vibration(ble, 2);
  unsigned writes = 0;
  NimBLERemoteCharacteristic::on_write = [&](auto& ch, const uint8_t* data, size_t len) {
    verify_find_write(data, len);
    ++writes;
    notify_ack(ch);
    for (auto& client : NimBLEDevice::clients) client.disconnect();
  };
  run_one_job();
  assert(writes == 1 && ble.vibrateAcks() == 3 && ble.vibrated());
  assert(ble.jobFinished() && ble.state() == BleCentral::JobState::Done);
}

static void ack_arriving_after_revocation_is_not_admitted() {
  BleCentral ble;
  prepare_vibration(ble);
  NimBLERemoteCharacteristic::on_write = [&](auto& ch, const uint8_t*, size_t) {
    ble.stopScanPolicy();
    notify_ack(ch);
  };
  run_one_job();
  assert(ble.vibrateAcks() == 0 && ble.jobRevoked() && !ble.vibrated());
}

int main(int argc, char** argv) {
  if (argc == 1) scan_and_job_policy();
  if (argc == 1 || std::strcmp(argv[1], "invalid-ack") == 0)
    non_ack_reply_does_not_advance_the_pulse_train();
  if (argc == 1 || std::strcmp(argv[1], "revoked-ack") == 0)
    queued_ack_survives_revocation_without_sending_again();
  if (argc == 1) {
    three_writes_need_three_distinct_pending_acknowledgements();
    resume_two_completed_pulses_writes_only_once();
    invalid_frames_leave_the_current_write_pending();
    accepted_ack_counts_even_if_the_link_has_disconnected();
    ack_arriving_after_revocation_is_not_admitted();
  }
  std::puts("ble_policy_host_test: PASS (scan policy, GATT writes, valid ACKs, duplicate burst, revocation)");
}
