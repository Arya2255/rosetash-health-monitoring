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

#include "protocol.h"

class BleCentral {
 public:
  static constexpr int kMaxBands = 32;
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
  enum class Fail : uint8_t { None, Connect, Subscribe, Write, Timeout };

  void begin(uint16_t scan_interval_ms, uint16_t scan_window_ms,
             uint32_t measure_timeout_ms);

  // ---- presence -------------------------------------------------------------
  int sightingCount();
  bool getSlot(int slot, Sighting& out);  // slot in [0, kMaxBands)
  int findSighting(const char* mac);      // -1 when unseen
  void pruneStale(uint32_t now, uint32_t ttl_ms);

  // ---- health jobs ----------------------------------------------------------
  bool healthBusy() const;
  bool jobFinished() const;
  bool startHealth(const char* mac);  // blocking connect (bounded), then async collect
  void poll();                        // drives measure timeout; call from loop()

  // finished-job accessors — valid until clearJob()
  JobState state() const { return state_; }
  Fail failure() const { return fail_; }
  const char* jobMac() const { return job_mac_; }
  uint8_t sampleCount() const { return sample_count_; }
  const uint8_t* samples() const { return samples_; }
  bool wearingOk() const { return wearing_ok_; }
  bool ended() const { return ended_; }
  void clearJob();

 private:
  class ScanCb;

  void onResult(const NimBLEAdvertisedDevice* dev);
  void onNotifyData(const uint8_t* data, size_t len);
  void finishJob(JobState st, Fail f);
  NimBLEClient* clientFor(const NimBLEAddress& addr);

  // sightings — mutated from the BLE task, guarded by mux_
  Sighting sightings_[kMaxBands]{};
  portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;

  // scan
  NimBLEScan* scan_ = nullptr;
  uint16_t scan_interval_ms_ = 160;
  uint16_t scan_window_ms_ = 80;

  // health job
  volatile JobState state_ = JobState::Idle;
  Fail fail_ = Fail::None;
  char job_mac_[18] = {0};
  uint8_t samples_[kMaxSamples]{};
  volatile uint8_t sample_count_ = 0;
  bool wearing_ok_ = true;
  bool ended_ = false;
  uint32_t job_started_ms_ = 0;
  uint32_t measure_timeout_ms_ = 45000;
  uint16_t counter_ = 0;

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
