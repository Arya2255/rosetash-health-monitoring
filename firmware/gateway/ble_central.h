// gateway/ble_central.h — BLE central for PDMB1062 bands.
//
// Role A: continuous scan of band advertisements (presence + RSSI).
// Role B: serialized health jobs — connect to one band at a time, start a
//         heart-rate measurement via the verified protocol and collect samples.
//
// Targets NimBLE-Arduino >= 2.1. The band accepts a single connection at a
// time and stops advertising while connected — we disconnect right after each
// measurement so presence scanning keeps working.
#pragma once

#include <Arduino.h>
#include <NimBLEDevice.h>
#include <atomic>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include "scan_policy.h"

#include "protocol.h"

class BleCentral {
 public:
  static constexpr int kMaxBands = roztash::kMaxPolicyMacs;
  static constexpr int kMaxSamples = 32;
  static constexpr int kMaxClients = 3;

  struct Sighting {
    bool used = false;
    NimBLEAddress addr;
    char mac[18] = {0};
    int rssi = -127;
    uint32_t seen_ms = 0;
  };

  enum class JobState : uint8_t { Idle, Connecting, Measuring, Done, Failed };
  enum class Fail : uint8_t { None, Connect, Subscribe, Write, Timeout, Policy };

  void begin(uint16_t scan_interval_ms, uint16_t scan_window_ms,
             uint32_t measure_timeout_ms);

  void setScanPolicy(const roztash::ScanPolicy& policy, uint32_t received_ms);
  void stopScanPolicy();
  bool scanPolicyAllows(const char* mac) const;
  bool scanEnabled() const;
  bool policyReady() const;
  bool hasFreshSighting(const char* mac, uint32_t now, bool emergency = false);
  bool jobRevoked() const { return cancelled_.load(); }

  // ---- presence -------------------------------------------------------------
  int sightingCount();
  uint32_t advCount() const { return adv_count_.load(); }  // permitted packets only
  bool getSlot(int slot, Sighting& out);  // slot in [0, kMaxBands)
  int findSighting(const char* mac);      // -1 when unseen
  void pruneStale(uint32_t now, uint32_t ttl_ms);

  // ---- health jobs ----------------------------------------------------------
  bool healthBusy() const;
  bool jobFinished() const;
  // Enqueue one GATT job on the dedicated worker. MQTT/presence never wait
  // for connection/discovery. The worker owns all measurement state until done.
  bool startHealth(const char* mac, bool vitals = false);
  // Connects, sends (05,50) and disconnects: makes the band vibrate (find-device).
  bool startVibrate(const char* mac, bool emergency = false, uint8_t repeats = 1,
                    uint8_t completed_pulses = 0);
  bool wasVibrate() const { return vibrate_mode_; }
  bool wasVibrateEmergency() const { return vibrate_emergency_; }
  bool vibrated() const { return vibrate_mode_ && vibrate_acks_ == vibrate_repeats_; }
  uint8_t vibrateAcks() const { return vibrate_acks_; }
  void poll();  // policy monitor only: lease, cancel and scan watchdog

  // finished-job accessors — valid until clearJob()
  JobState state() const { return state_.load(); }
  Fail failure() const { return fail_; }
  const char* jobMac() const { return job_mac_; }
  uint8_t sampleCount() const { return sample_count_; }
  const uint8_t* samples() const { return samples_; }
  bool wearingOk() const { return wearing_ok_; }
  bool ended() const { return ended_; }

  // ---- extra device features: battery, SpO2, HRV, steps --------------------
  // Valid until clearJob(). Raw frames are forwarded as-is: the SpO2/HRV data
  // layouts are only partly decoded, so the gateway publishes what it saw.
  static constexpr int kMaxRawFrames = 6;
  static constexpr int kMaxRawLen = 10;

  struct RawFrame {
    uint8_t c1 = 0;
    uint8_t c2 = 0;
    uint8_t len = 0;
    uint8_t data[kMaxRawLen] = {0};
  };

  struct Vitals {
    bool battery_ok = false;
    uint8_t battery = 0;         // percent
    char dev_fw[16] = {0};       // device information 0x2A28 (software revision)
    char dev_hw[16] = {0};       // 0x2A27 (hardware revision)
    char dev_maker[40] = {0};    // 0x2A29 (manufacturer name)
    bool spo2_ack = false;       // band accepted the SpO2 measurement
    bool hrv_ack = false;        // band accepted the HRV measurement
    uint8_t spo2_frames = 0;
    uint8_t hrv_frames = 0;
    RawFrame spo2[kMaxRawFrames];
    RawFrame hrv[kMaxRawFrames];
    bool steps_ok = false;       // realtime-report step frame seen
    uint32_t steps = 0;
  };

  const Vitals& vitals() const { return vitals_; }
  void clearJob();

 private:
  class ScanCb;

  void onResult(const NimBLEAdvertisedDevice* dev);
  void onNotifyData(const uint8_t* data, size_t len);
  void drainNotifications();
  void enqueueNotify(uint32_t generation, const uint8_t* data, size_t len);
  bool launchJob(const char* mac, bool vitals, bool vibrate, bool emergency = false);
  bool runHealth(const char* mac, bool vitals);
  bool runVibrate(const char* mac);
  bool jobAllowed() const;
  void cancelRevokedJob();
  void pollMeasurement();
  static void workerEntry(void* self);
  static void controlEntry(void* self);
  void workerLoop();
  void finishJob(JobState st, Fail f);
  NimBLEClient* clientFor(const NimBLEAddress& addr);

  // sightings — mutated from the BLE task, guarded by mux_
  Sighting sightings_[kMaxBands]{};
  std::atomic<uint32_t> adv_count_{0};
  mutable portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;
  roztash::PolicyState policy_;

  // scan
  NimBLEScan* scan_ = nullptr;
  uint16_t scan_interval_ms_ = 160;
  uint16_t scan_window_ms_ = 80;

  // health job
  std::atomic<JobState> state_{JobState::Idle};
  std::atomic<bool> worker_active_{false};
  std::atomic<bool> cancelled_{false};
  std::atomic<bool> connecting_{false};
  TaskHandle_t worker_ = nullptr;
  std::atomic<bool> control_ready_{false};
  QueueHandle_t notifications_ = nullptr;
  SemaphoreHandle_t lifecycle_ = nullptr;
  struct Notification { uint32_t generation; size_t len; uint8_t data[64]; };
  uint32_t job_generation_ = 0;  // guarded by mux_
  uint32_t last_scan_retry_ms_ = 0;
  Fail fail_ = Fail::None;
  char job_mac_[18] = {0};
  uint8_t samples_[kMaxSamples]{};
  uint8_t sample_count_ = 0;
  bool wearing_ok_ = true;
  bool ended_ = false;
  uint32_t job_started_ms_ = 0;
  uint32_t measure_timeout_ms_ = 45000;
  uint16_t counter_ = 0;

  // multi-stage vitals job: HR → SpO2 → HRV, one connection per band
  enum class Stage : uint8_t { Hr = 0, Spo2 = 1, Hrv = 2, Done = 3 };
  Stage stage_ = Stage::Hr;
  bool vitals_enabled_ = false;
  uint32_t stage_started_ms_ = 0;
  uint32_t stage_settle_ms_ = 0;  // 0 = not settling; >0 = waiting before next stage
  uint8_t stage_end_type_ = 0;
  Vitals vitals_;

  // vibrate job (find-device): reuses the connect/subscribe path
  bool vibrate_mode_ = false;
  bool vibrate_emergency_ = false;
  uint8_t vibrate_acks_ = 0;
  uint8_t vibrate_repeats_ = 1;
  bool vibrate_write_pending_ = false;
  uint32_t vibrate_write_at_ = 0;

  bool sendMeasureStart(uint8_t type);
  bool beginJob(const char* mac);   // shared connect+subscribe preamble
  void readDeviceInfo();
  void advanceStage();
  static void addRaw(RawFrame* arr, uint8_t& count, const fundo::Parsed& p);

  // warm clients — keep NimBLE clients cached per band so reconnects skip
  // service discovery (connect(addr, false)).
  struct WarmClient {
    NimBLEClient* client = nullptr;
    char mac[18] = {0};
    bool discovered = false;
  };
  WarmClient clients_[kMaxClients];
  int warm_idx_ = -1;
  int warm_next_ = 0;

  NimBLEClient* job_client_ = nullptr;
  NimBLERemoteCharacteristic* write_char_ = nullptr;
  NimBLERemoteCharacteristic* notify_char_ = nullptr;
};
