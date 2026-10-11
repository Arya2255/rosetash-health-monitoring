#include "ble_central.h"

// --- verified UUIDs (docs/band-protocol.md, live-tested 2026-10-10) ---------
// The band's advertisement packet carries the 16-bit UUID 0xBAA0 (expanded
// to 0000baa0-0000-1000-8000-00805f9b34fb) — verified 2026-10-11 with a live
// adv scan; the 128-bit custom service below only appears in the GATT table
// after connecting. The Porodo Fit app filters scans on the same 16-bit UUID.
static const char* kBandName = "PDMB1062";
static const NimBLEUUID kAdvSvc16((uint16_t)0xBAA0);
static const NimBLEUUID kSvcUuid("4cdabaa0-2cea-c0c1-b38d-a0481ae60a97");
static const NimBLEUUID kWriteUuid("4cdabaa1-2cea-c0c1-b38d-a0481ae60a97");
static const NimBLEUUID kNotifyUuid("4cdabaa2-2cea-c0c1-b38d-a0481ae60a97");

static const uint32_t kConnectTimeoutMs = 10000;
static const uint32_t kStageSettleMs = 1500;  // wait for late result frames

// Standard GATT services the band also exposes (verified live 2026-10-11):
//   180F/2A19 battery percent (read+notify), 180A/2A27-2A29 device information.
static const NimBLEUUID kBatterySvc((uint16_t)0x180F);
static const NimBLEUUID kBatteryChr((uint16_t)0x2A19);
static const NimBLEUUID kDevInfoSvc((uint16_t)0x180A);
static const NimBLEUUID kDevFwChr((uint16_t)0x2A28);
static const NimBLEUUID kDevHwChr((uint16_t)0x2A27);
static const NimBLEUUID kDevMakerChr((uint16_t)0x2A29);

// --- callbacks --------------------------------------------------------------
class BleCentral::ScanCb : public NimBLEScanCallbacks {
 public:
  explicit ScanCb(BleCentral* owner) : owner_(owner) {}
  void onResult(const NimBLEAdvertisedDevice* dev) override {
    owner_->onResult(dev);
  }

 private:
  BleCentral* owner_;
};

// --- setup ------------------------------------------------------------------
void BleCentral::begin(uint16_t scan_interval_ms, uint16_t scan_window_ms,
                       uint32_t measure_timeout_ms) {
  scan_interval_ms_ = scan_interval_ms;
  scan_window_ms_ = scan_window_ms;
  measure_timeout_ms_ = measure_timeout_ms;

  NimBLEDevice::init("roztash-gw");
  NimBLEDevice::setPower(9);  // max TX power (verify range in the pilot)

  scan_ = NimBLEDevice::getScan();
  scan_->setScanCallbacks(new ScanCb(this), true);  // wantDuplicates: keep RSSI fresh
  scan_->setInterval(scan_interval_ms_);
  scan_->setWindow(scan_window_ms_);
  scan_->setActiveScan(true);  // active: the band's name rides in the scan response
  scan_->start(0, false, true); // forever, restart on controller reset
  Serial.printf("[ble] scanning (int=%u win=%u ms)\n",
                (unsigned)scan_interval_ms_, (unsigned)scan_window_ms_);
}

// --- presence ---------------------------------------------------------------
void BleCentral::onResult(const NimBLEAdvertisedDevice* dev) {
  adv_count_++;

  bool match = dev->haveName() && dev->getName() == kBandName;
  if (!match) {
    for (uint8_t i = 0; i < dev->getServiceUUIDCount(); ++i) {
      const NimBLEUUID u = dev->getServiceUUID(i);
      if (u.equals(kAdvSvc16) || u.equals(kSvcUuid)) { match = true; break; }
    }
  }
  if (!match) return;

  const NimBLEAddress addr = dev->getAddress();
  const int rssi = dev->getRSSI();
  const uint32_t now = millis();
  const std::string mac = addr.toString();
  NimBLEAddress copy = addr;

  portENTER_CRITICAL(&mux_);
  int slot = -1, free_slot = -1;
  for (int i = 0; i < kMaxBands; ++i) {
    if (sightings_[i].used && sightings_[i].addr.equals(addr)) { slot = i; break; }
    if (!sightings_[i].used && free_slot < 0) free_slot = i;
  }
  if (slot < 0) slot = free_slot;
  if (slot >= 0) {
    Sighting& s = sightings_[slot];
    s.used = true;
    s.addr = copy;
    strlcpy(s.mac, mac.c_str(), sizeof s.mac);
    s.rssi = rssi;
    s.seen_ms = now;
  }
  portEXIT_CRITICAL(&mux_);
}

int BleCentral::sightingCount() {
  int n = 0;
  portENTER_CRITICAL(&mux_);
  for (int i = 0; i < kMaxBands; ++i)
    if (sightings_[i].used) n++;
  portEXIT_CRITICAL(&mux_);
  return n;
}

bool BleCentral::getSlot(int slot, Sighting& out) {
  if (slot < 0 || slot >= kMaxBands) return false;
  portENTER_CRITICAL(&mux_);
  out = sightings_[slot];
  portEXIT_CRITICAL(&mux_);
  return true;
}

int BleCentral::findSighting(const char* mac) {
  int found = -1;
  portENTER_CRITICAL(&mux_);
  for (int i = 0; i < kMaxBands; ++i)
    if (sightings_[i].used && strcmp(sightings_[i].mac, mac) == 0) {
      found = i;
      break;
    }
  portEXIT_CRITICAL(&mux_);
  return found;
}

void BleCentral::pruneStale(uint32_t now, uint32_t ttl_ms) {
  portENTER_CRITICAL(&mux_);
  for (int i = 0; i < kMaxBands; ++i) {
    Sighting& s = sightings_[i];
    if (s.used && (now - s.seen_ms) > ttl_ms) s.used = false;
  }
  portEXIT_CRITICAL(&mux_);
}

// --- health jobs ------------------------------------------------------------
bool BleCentral::healthBusy() const {
  return state_ == JobState::Connecting || state_ == JobState::Measuring;
}

bool BleCentral::jobFinished() const {
  return state_ == JobState::Done || state_ == JobState::Failed;
}

void BleCentral::finishJob(JobState st, Fail f) {
  fail_ = f;
  state_ = st;
  if (job_client_ && job_client_->isConnected()) job_client_->disconnect();
}

NimBLEClient* BleCentral::clientFor(const NimBLEAddress& addr) {
  const std::string mac = addr.toString();
  warm_idx_ = -1;
  for (int i = 0; i < kMaxClients; ++i) {
    if (clients_[i].client && strcmp(clients_[i].mac, mac.c_str()) == 0) {
      warm_idx_ = i;
      return clients_[i].client;
    }
  }
  const int slot = (warm_next_++) % kMaxClients;
  if (clients_[slot].client) {
    if (clients_[slot].client->isConnected()) clients_[slot].client->disconnect();
    NimBLEDevice::deleteClient(clients_[slot].client);
    clients_[slot].client = nullptr;
  }
  NimBLEClient* c = NimBLEDevice::createClient();
  if (!c) return nullptr;
  c->setConnectTimeout(kConnectTimeoutMs);
  clients_[slot].client = c;
  clients_[slot].discovered = false;
  strlcpy(clients_[slot].mac, mac.c_str(), sizeof clients_[slot].mac);
  warm_idx_ = slot;
  return c;
}

// Shared preamble for both job kinds: take the sighting slot, connect and
// subscribe to the notify characteristic. On any failure the job is finished
// as Failed (so the caller only returns false).
bool BleCentral::beginJob(const char* mac) {
  if (healthBusy()) return false;
  const int slot = findSighting(mac);
  if (slot < 0) return false;

  job_mac_[0] = 0;
  strlcpy(job_mac_, mac, sizeof job_mac_);
  sample_count_ = 0;
  wearing_ok_ = true;
  ended_ = false;
  fail_ = Fail::None;
  state_ = JobState::Connecting;

  NimBLEAddress addr;
  portENTER_CRITICAL(&mux_);
  addr = sightings_[slot].addr;
  portEXIT_CRITICAL(&mux_);

  NimBLEClient* c = clientFor(addr);
  if (!c) { finishJob(JobState::Failed, Fail::Connect); return false; }
  job_client_ = c;

  const bool warm = clients_[warm_idx_].discovered;
  if (!c->isConnected() && !c->connect(addr, !warm)) {
    Serial.printf("[ble] connect failed: %s\n", mac);
    finishJob(JobState::Failed, Fail::Connect);
    return false;
  }
  clients_[warm_idx_].discovered = true;

  NimBLERemoteService* svc = c->getService(kSvcUuid);
  if (!svc) { finishJob(JobState::Failed, Fail::Subscribe); return false; }
  notify_char_ = svc->getCharacteristic(kNotifyUuid);
  write_char_ = svc->getCharacteristic(kWriteUuid);
  if (!notify_char_ || !write_char_ ||
      !notify_char_->subscribe(
          true,
          [this](NimBLERemoteCharacteristic*, uint8_t* data, size_t len, bool) {
            onNotifyData(data, len);
          },
          true)) {  // CCCD write WITH response — the band ignores no-response CCCD writes
    finishJob(JobState::Failed, Fail::Subscribe);
    return false;
  }
  Serial.printf("[ble] subscribed; writing to %s\n", mac);
  return true;
}

bool BleCentral::startHealth(const char* mac, bool vitals) {
  vitals_enabled_ = vitals;
  vitals_ = Vitals{};
  stage_ = Stage::Hr;
  stage_end_type_ = 0;
  stage_settle_ms_ = 0;
  vibrate_mode_ = false;
  vibrated_ = false;

  if (!beginJob(mac)) return false;

  readDeviceInfo();  // battery + device information — cheap, right after connect

  if (!sendMeasureStart(fundo::MEASURE_TYPE_HR)) {
    finishJob(JobState::Failed, Fail::Write);
    return false;
  }

  Serial.printf("[ble] health job started: %s (vitals=%d battery=%d)\n", mac,
                (int)vitals_enabled_,
                vitals_.battery_ok ? (int)vitals_.battery : -1);
  job_started_ms_ = millis();
  stage_started_ms_ = job_started_ms_;
  state_ = JobState::Measuring;
  return true;
}

// Find-device (vibration): connect, send (05,50) with an empty payload, wait a
// few seconds for the band's (05,50) ack, disconnect. Verified live 2026-10-11:
// the band acknowledges and vibrates.
bool BleCentral::startVibrate(const char* mac) {
  vitals_enabled_ = false;
  vitals_ = Vitals{};
  vibrate_mode_ = true;
  vibrated_ = false;

  if (!beginJob(mac)) return false;

  uint8_t frame[16];
  const size_t n = fundo::buildFrame(counter_++, fundo::CMD_FIND_DEVICE,
                                     fundo::SUB_FIND_DEVICE, nullptr, 0, frame);
  if (!n || !write_char_ || !write_char_->writeValue(frame, n, false)) {
    finishJob(JobState::Failed, Fail::Write);
    return false;
  }
  Serial.printf("[ble] vibrate job started: %s\n", mac);
  job_started_ms_ = millis();
  stage_started_ms_ = job_started_ms_;
  state_ = JobState::Measuring;
  return true;
}

// Builds <cmd1=C+START><type> with the shared frame builder (same path as HR).
bool BleCentral::sendMeasureStart(uint8_t type) {
  const uint8_t payload[2] = {0x01, type};
  uint8_t frame[16];
  const size_t n = fundo::buildFrame(counter_++, fundo::CMD_MEASURE,
                                     fundo::SUB_MEASURE_START, payload, 2, frame);
  if (!n || !write_char_ || !write_char_->writeValue(frame, n, false)) return false;
  Serial.printf("[ble] measure start type=%u\n", (unsigned)type);
  return true;
}

// Battery (180F/2A19) and device information (180A/*) — present on the band as
// ordinary GATT services; reading them costs one round trip each.
void BleCentral::readDeviceInfo() {
  if (!job_client_ || !job_client_->isConnected()) return;

  if (NimBLERemoteService* svc = job_client_->getService(kBatterySvc)) {
    if (NimBLERemoteCharacteristic* ch = svc->getCharacteristic(kBatteryChr)) {
      const std::string v = ch->readValue();
      if (!v.empty()) {
        vitals_.battery = (uint8_t)v[0];
        vitals_.battery_ok = true;
      }
    }
  }

  if (NimBLERemoteService* svc = job_client_->getService(kDevInfoSvc)) {
    struct Row {
      const NimBLEUUID* chr;
      char* dst;
      size_t cap;
    } rows[] = {
        {&kDevFwChr, vitals_.dev_fw, sizeof vitals_.dev_fw},
        {&kDevHwChr, vitals_.dev_hw, sizeof vitals_.dev_hw},
        {&kDevMakerChr, vitals_.dev_maker, sizeof vitals_.dev_maker},
    };
    for (const Row& r : rows) {
      NimBLERemoteCharacteristic* ch = svc->getCharacteristic(*r.chr);
      if (!ch) continue;
      const std::string v = ch->readValue();
      if (v.empty()) continue;
      strlcpy(r.dst, v.c_str(), r.cap);
      for (size_t i = 0; i < strlen(r.dst); ++i)
        if ((uint8_t)r.dst[i] < 0x20) { r.dst[i] = 0; break; }  // trim gatt noise
    }
  }
}

void BleCentral::addRaw(RawFrame* arr, uint8_t& count, const fundo::Parsed& p) {
  if (count >= (uint8_t)kMaxRawFrames) return;
  RawFrame& f = arr[count++];
  f.c1 = p.cmd1;
  f.c2 = p.cmd2;
  f.len = p.data_len > (uint8_t)kMaxRawLen ? (uint8_t)kMaxRawLen : p.data_len;
  memcpy(f.data, p.data, f.len);
}

// HR finished → optionally SpO2 → HRV, all on the same connection. The band
// answers each start with (02,71) ack and closes the window with (02,72) whose
// data[0] is the finished measure type (1=HR, 2=SpO2, 6=HRV — live-verified).
void BleCentral::advanceStage() {
  ended_ = false;
  stage_settle_ms_ = 0;
  stage_started_ms_ = millis();
  wearing_ok_ = true;
  const uint8_t next = (uint8_t)stage_ + 1;
  if (!vitals_enabled_ || next > (uint8_t)Stage::Hrv) {
    stage_ = Stage::Done;
    return;
  }
  stage_ = (Stage)next;
  const uint8_t type =
      (stage_ == Stage::Spo2) ? fundo::MEASURE_TYPE_SPO2 : fundo::MEASURE_TYPE_HRV;
  if (!sendMeasureStart(type)) {
    stage_ = Stage::Done;
    return;
  }
  Serial.printf("[ble] stage -> %s\n", stage_ == Stage::Spo2 ? "spo2" : "hrv");
}

void BleCentral::poll() {
  // Scan watchdog: NimBLE stops the scan while a connection is attempted and
  // does not resume it afterwards — restart scanning whenever we are idle so
  // presence keeps working after every health job.
  if (state_ == JobState::Idle && scan_ && !scan_->isScanning()) {
    scan_->start(0, false, true);
    Serial.println("[ble] scan restarted (watchdog)");
  }

  if (state_ != JobState::Measuring) return;
  const uint32_t now = millis();

  // Vibrate jobs end as soon as the band answers (05,50) — or after a short
  // grace window if the ack never arrives.
  if (vibrate_mode_) {
    if (vibrated_ || (now - stage_started_ms_) > (kStageSettleMs * 2)) {
      finishJob(vibrated_ ? JobState::Done : JobState::Failed,
                vibrated_ ? Fail::None : Fail::Timeout);
      Serial.printf("[ble] vibrate %s: ack=%d\n", job_mac_, (int)vibrated_);
    }
    return;
  }

  if (stage_ == Stage::Done) {
    const bool got_any = sample_count_ || vitals_.spo2_frames || vitals_.hrv_frames ||
                         vitals_.battery_ok;
    finishJob(got_any ? JobState::Done : JobState::Failed,
              got_any ? Fail::None : Fail::Timeout);
    Serial.printf(
        "[ble] job done: %s samples=%u spo2_frames=%u hrv_frames=%u battery=%d\n",
        job_mac_, (unsigned)sample_count_, (unsigned)vitals_.spo2_frames,
        (unsigned)vitals_.hrv_frames, vitals_.battery_ok ? (int)vitals_.battery : -1);
    return;
  }

  // A wearing error on the heart-rate stage means the band is off the wrist —
  // SpO2/HRV need skin contact too, so skip the remaining stages.
  if (!wearing_ok_) {
    stage_ = Stage::Done;
    return;
  }

  const bool stage_over = ended_ || ((now - stage_started_ms_) > measure_timeout_ms_);
  if (!stage_over) return;
  if (stage_settle_ms_ == 0) {
    stage_settle_ms_ = now ? now : 1;  // let late result frames land first
    return;
  }
  if ((now - stage_settle_ms_) >= kStageSettleMs) advanceStage();
}

void BleCentral::clearJob() {
  state_ = JobState::Idle;
  fail_ = Fail::None;
  job_client_ = nullptr;
  write_char_ = nullptr;
  notify_char_ = nullptr;
  sample_count_ = 0;
  job_mac_[0] = 0;
  stage_ = Stage::Hr;
  stage_settle_ms_ = 0;
  vitals_enabled_ = false;
  vibrate_mode_ = false;
  vibrated_ = false;
  vitals_ = Vitals{};
}

void BleCentral::onNotifyData(const uint8_t* data, size_t len) {
  fundo::Parsed p;
  if (!fundo::parseFrame(data, len, p) || !p.valid || !p.crc_ok) {
    Serial.printf("[ble] notify unparsed (len=%u)\n", (unsigned)len);
    return;
  }
  Serial.printf("[ble] notify (%02X,%02X) dlen=%u stage=%u\n", p.cmd1, p.cmd2,
                (unsigned)p.data_len, (unsigned)stage_);

  // --- find-device (vibrate) ack (05,50) -------------------------------------
  if (p.cmd1 == fundo::CMD_FIND_DEVICE && p.cmd2 == fundo::SUB_FIND_DEVICE) {
    vibrated_ = true;
    Serial.println("[ble] vibrate ack");
    return;
  }

  // --- measurement control ----------------------------------------------------
  if (p.cmd1 == fundo::CMD_MEASURE && p.cmd2 == fundo::SUB_MEASURE_ACK &&
      p.data_len >= 1) {
    wearing_ok_ = (p.data[0] == 1);  // 0 = wearing error
    if (stage_ == Stage::Spo2) vitals_.spo2_ack = wearing_ok_;
    if (stage_ == Stage::Hrv) vitals_.hrv_ack = wearing_ok_;
    if (!wearing_ok_) Serial.printf("[ble] wearing error: %s\n", job_mac_);
    return;
  }
  if (p.cmd1 == fundo::CMD_MEASURE && p.cmd2 == fundo::SUB_MEASURE_END) {
    if (p.data_len >= 1) stage_end_type_ = p.data[0];
    ended_ = true;
    Serial.printf("[ble] measure end type=%u\n", (unsigned)stage_end_type_);
    return;
  }

  // --- battery pushed by the band (04,41) ------------------------------------
  if (p.cmd1 == fundo::CMD_BATTERY && p.cmd2 == fundo::SUB_BATTERY &&
      p.data_len >= 1) {
    vitals_.battery = p.data[0];
    vitals_.battery_ok = true;
    return;
  }

  // --- realtime-report step counter (A6,AC): 3-byte little-endian -------------
  if (p.cmd1 == fundo::CMD_REPORT && p.cmd2 == fundo::SUB_REPORT_STEPS &&
      p.data_len >= 3) {
    vitals_.steps = (uint32_t)p.data[0] | ((uint32_t)p.data[1] << 8) |
                    ((uint32_t)p.data[2] << 16);
    vitals_.steps_ok = true;
    return;
  }

  // --- stage data -------------------------------------------------------------
  // Capture stays on the current stage during the settle window, so a result
  // frame that lands right after the end frame still lands in the right bucket.
  switch (stage_) {
    case Stage::Hr:
      if (p.cmd1 == fundo::CMD_REALTIME && p.cmd2 == fundo::SUB_REALTIME_HR &&
          p.data_len >= 1) {
        if (sample_count_ < kMaxSamples) samples_[sample_count_++] = p.data[0];
      }
      break;
    case Stage::Spo2:
      addRaw(vitals_.spo2, vitals_.spo2_frames, p);
      break;
    case Stage::Hrv:
      addRaw(vitals_.hrv, vitals_.hrv_frames, p);
      break;
    default:
      if (p.cmd1 == fundo::CMD_REALTIME && p.cmd2 == fundo::SUB_REALTIME_SPO2)
        addRaw(vitals_.spo2, vitals_.spo2_frames, p);
      break;
  }
}
