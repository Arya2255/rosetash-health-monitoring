#include "ble_central.h"

// Verified GATT UUIDs. Scan identity comes ONLY from the software policy MAC,
// since passive advertisements need not contain a name or service UUID.
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
  scan_->setActiveScan(false);  // never direct scan requests to excluded bands
  scan_->setMaxResults(0);      // callback only, no NimBLE advertiser cache
  notifications_ = xQueueCreate(16, sizeof(Notification));
  lifecycle_ = xSemaphoreCreateMutex();
  // Stable client objects: cancellation can safely use the current pointer
  // while the worker is blocked in connect/discovery; only attributes rotate.
  for (auto& slot : clients_) {
    slot.client = NimBLEDevice::createClient();
    if (slot.client) {
      slot.client->setConnectTimeout(kConnectTimeoutMs);
      slot.client->setConnectRetries(0);
    }
  }
  if (!notifications_ || !lifecycle_ || xTaskCreate(workerEntry, "health-gatt", 8192, this, 1, &worker_) != pdPASS)
    Serial.println("[ble] health worker unavailable");
  if (xTaskCreate(controlEntry, "scan-policy", 4096, this, 1, nullptr) != pdPASS) {
    worker_ = nullptr;  // no policy monitor: fail closed
    control_ready_ = false;
    Serial.println("[ble] policy monitor unavailable");
  } else control_ready_ = true;
  Serial.println("[ble] ready; passive scan disabled until leased policy arrives");
}

// --- leased policy and task coordination ------------------------------------
void BleCentral::setScanPolicy(const roztash::ScanPolicy& policy, uint32_t received_ms) {
  portENTER_CRITICAL(&mux_);
  if (control_ready_.load()) policy_.apply(policy, received_ms);
  else policy_.revoke();
  for (auto& s : sightings_)
    if (s.used && !policy_.allows(s.mac, millis()) &&
        !policy_.allowsEmergency(s.mac, millis())) s = Sighting{};
  if (job_mac_[0] && !(vibrate_mode_
      ? (vibrate_emergency_ ? policy_.allowsEmergency(job_mac_, millis())
                            : policy_.allows(job_mac_, millis()))
      : policy_.allowsHealth(job_mac_, millis()))) cancelled_ = true;
  portEXIT_CRITICAL(&mux_);
}

void BleCentral::stopScanPolicy() {
  portENTER_CRITICAL(&mux_);
  policy_.revoke();
  for (auto& s : sightings_) s = Sighting{};
  if (job_mac_[0]) cancelled_ = true;
  portEXIT_CRITICAL(&mux_);
}

bool BleCentral::scanPolicyAllows(const char* mac) const {
  portENTER_CRITICAL(&mux_);
  const bool allowed = policy_.allows(mac, millis()) ||
                       policy_.allowsEmergency(mac, millis());
  portEXIT_CRITICAL(&mux_);
  return allowed;
}
bool BleCentral::scanEnabled() const {
  portENTER_CRITICAL(&mux_);
  const bool enabled = policy_.scanEnabled(millis());
  portEXIT_CRITICAL(&mux_);
  return enabled;
}
bool BleCentral::policyReady() const {
  portENTER_CRITICAL(&mux_);
  const bool ready = policy_.ready(millis());
  portEXIT_CRITICAL(&mux_);
  return ready;
}
bool BleCentral::hasFreshSighting(const char* mac, uint32_t now, bool emergency) {
  bool fresh = false;
  portENTER_CRITICAL(&mux_);
  if (emergency ? policy_.allowsEmergency(mac, now) : policy_.allows(mac, now))
    for (const auto& s : sightings_)
      if (s.used && strcmp(s.mac, mac) == 0 && uint32_t(now - s.seen_ms) <= roztash::kSightingFreshMs) {
        fresh = true;
        break;
      }
  portEXIT_CRITICAL(&mux_);
  return fresh;
}
bool BleCentral::jobAllowed() const {
  portENTER_CRITICAL(&mux_);
  const bool allowed = !cancelled_.load() &&
      (vibrate_mode_ ? (vibrate_emergency_ ? policy_.allowsEmergency(job_mac_, millis())
                                          : policy_.allows(job_mac_, millis()))
                     : policy_.allowsHealth(job_mac_, millis()));
  portEXIT_CRITICAL(&mux_);
  return allowed;
}

void BleCentral::cancelRevokedJob() {
  // Keep completion/new-job handoff from recycling a client while we cancel it.
  if (!lifecycle_) return;
  xSemaphoreTake(lifecycle_, portMAX_DELAY);
  portENTER_CRITICAL(&mux_);
  NimBLEClient* client = job_client_;
  const bool allowed = !cancelled_.load() &&
      (vibrate_mode_ ? (vibrate_emergency_ ? policy_.allowsEmergency(job_mac_, millis())
                                          : policy_.allows(job_mac_, millis()))
                     : policy_.allowsHealth(job_mac_, millis()));
  const bool busy = worker_active_.load();
  if (job_mac_[0] && !allowed) cancelled_ = true;
  portEXIT_CRITICAL(&mux_);
  if (busy && !allowed && client) {
    if (client->isConnected()) client->disconnect();
    else if (connecting_.load()) client->cancelConnect();
  }
  xSemaphoreGive(lifecycle_);
}

void BleCentral::controlEntry(void* self) {
  auto* owner = static_cast<BleCentral*>(self);
  for (;;) { owner->poll(); vTaskDelay(pdMS_TO_TICKS(25)); }
}
void BleCentral::poll() {
  portENTER_CRITICAL(&mux_);
  if (policy_.expire(millis())) {
    for (auto& s : sightings_) s = Sighting{};
    if (job_mac_[0]) cancelled_ = true;
  }
  portEXIT_CRITICAL(&mux_);
  cancelRevokedJob();
  if (!scan_) return;
  if (!scanEnabled()) {
    if (scan_->isScanning()) scan_->stop();
    return;
  }
  // NimBLE may stop scanning during initiation. Resume even while collecting
  // GATT data from one band so other permitted advertisers remain observable.
  const uint32_t now = millis();
  if (!connecting_.load() && !scan_->isScanning() && now - last_scan_retry_ms_ >= 1000) {
    last_scan_retry_ms_ = now;
    scan_->start(0, false, false);
  }
}

bool BleCentral::startHealth(const char* mac, bool vitals) {
  return launchJob(mac, vitals, false);
}
bool BleCentral::startVibrate(const char* mac, bool emergency, uint8_t repeats,
                              uint8_t completed_pulses) {
  if (repeats < 1 || repeats > 3 || completed_pulses >= repeats) return false;
  vibrate_repeats_ = repeats;
  vibrate_acks_ = completed_pulses;
  vibrate_write_pending_ = false;
  vibrated_ = false;
  const bool started = launchJob(mac, false, true, emergency);
  if (!started) {
    vibrate_repeats_ = 1;
    vibrate_acks_ = 0;
  }
  return started;
}
bool BleCentral::launchJob(const char* mac, bool vitals, bool vibrate, bool emergency) {
  if (!worker_ || worker_active_.load() || state_ != JobState::Idle ||
      !hasFreshSighting(mac, millis(), emergency)) return false;
  portENTER_CRITICAL(&mux_);
  if (!(vibrate ? (emergency ? policy_.allowsEmergency(mac, millis())
                             : policy_.allows(mac, millis()))
                : policy_.allowsHealth(mac, millis()))) {
    portEXIT_CRITICAL(&mux_);
    return false;
  }
  strlcpy(job_mac_, mac, sizeof job_mac_);
  vibrate_mode_ = vibrate;
  vibrate_emergency_ = emergency;
  vitals_enabled_ = vitals;
  cancelled_ = false;
  ++job_generation_;
  state_ = JobState::Connecting;
  worker_active_ = true;
  portEXIT_CRITICAL(&mux_);
  xTaskNotifyGive(worker_);
  return true;
}
void BleCentral::workerEntry(void* self) { static_cast<BleCentral*>(self)->workerLoop(); }
void BleCentral::workerLoop() {
  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    xQueueReset(notifications_);
    if (!jobAllowed()) finishJob(JobState::Failed, Fail::Policy);
    else if (vibrate_mode_) runVibrate(job_mac_);
    else runHealth(job_mac_, vitals_enabled_);
    while (state_ == JobState::Measuring) {
      Notification n;
      while (xQueueReceive(notifications_, &n, 0) == pdTRUE)
        if (n.generation == job_generation_ && jobAllowed()) onNotifyData(n.data, n.len);
      pollMeasurement();
      vTaskDelay(pdMS_TO_TICKS(10));
    }
    if (!jobAllowed()) {
      fail_ = Fail::Policy;
      state_ = JobState::Failed;
      sample_count_ = 0;
      vitals_ = Vitals{};
      cancelled_ = true;
    }
    // Finish disconnect before handing the result/next job back to loop().
    if (job_client_ && job_client_->isConnected()) job_client_->disconnect();
    while (job_client_ && job_client_->getConnHandle() != BLE_HS_CONN_HANDLE_NONE)
      vTaskDelay(pdMS_TO_TICKS(10));
    xSemaphoreTake(lifecycle_, portMAX_DELAY);
    portENTER_CRITICAL(&mux_);
    job_client_ = nullptr;
    worker_active_ = false;  // release/acquire handoff for result fields
    portEXIT_CRITICAL(&mux_);
    xSemaphoreGive(lifecycle_);
  }
}
void BleCentral::enqueueNotify(uint32_t generation, const uint8_t* data, size_t len) {
  if (len > sizeof(Notification::data)) return;
  portENTER_CRITICAL(&mux_);
  // Old subscriptions can deliver a late packet after cancellation/reconnection.
  if (worker_active_.load() && generation == job_generation_ && !cancelled_.load() &&
      (vibrate_mode_ ? (vibrate_emergency_ ? policy_.allowsEmergency(job_mac_, millis())
                                          : policy_.allows(job_mac_, millis()))
                     : policy_.allowsHealth(job_mac_, millis()))) {
    Notification n{};
    n.generation = generation; n.len = len;
    memcpy(n.data, data, len);
    xQueueSend(notifications_, &n, 0);
  }
  portEXIT_CRITICAL(&mux_);
}

// --- presence ---------------------------------------------------------------
void BleCentral::onResult(const NimBLEAdvertisedDevice* dev) {
  const NimBLEAddress addr = dev->getAddress();
  const std::string mac = addr.toString();
  const uint32_t now = millis();
  portENTER_CRITICAL(&mux_);
  // Gate BEFORE reading RSSI, counting, storing, or logging advertisements.
  // Physical reception still occurs; excluded devices leave no application data.
  if (!policy_.allows(mac.c_str(), now) &&
      !policy_.allowsEmergency(mac.c_str(), now)) {
    portEXIT_CRITICAL(&mux_);
    return;
  }
  adv_count_++;
  const int rssi = dev->getRSSI();
  int slot = -1, free_slot = -1;
  for (int i = 0; i < kMaxBands; ++i) {
    if (sightings_[i].used && sightings_[i].addr.equals(addr)) { slot = i; break; }
    if (!sightings_[i].used && free_slot < 0) free_slot = i;
  }
  if (slot < 0) slot = free_slot;
  if (slot >= 0) {
    Sighting& s = sightings_[slot];
    s.used = true;
    s.addr = addr;
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
    if (sightings_[i].used && (policy_.allows(sightings_[i].mac, millis()) ||
                               policy_.allowsEmergency(sightings_[i].mac, millis()))) n++;
  portEXIT_CRITICAL(&mux_);
  return n;
}

bool BleCentral::getSlot(int slot, Sighting& out) {
  if (slot < 0 || slot >= kMaxBands) return false;
  portENTER_CRITICAL(&mux_);
  out = sightings_[slot];
  if (out.used && !policy_.allows(out.mac, millis()) &&
      !policy_.allowsEmergency(out.mac, millis())) out = Sighting{};
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
    // A BLE callback can update the slot after the caller sampled `now`.
    const int32_t age = static_cast<int32_t>(now - s.seen_ms);
    if (s.used && age >= 0 && static_cast<uint32_t>(age) > ttl_ms) s = Sighting{};
  }
  portEXIT_CRITICAL(&mux_);
}

// --- health jobs ------------------------------------------------------------
bool BleCentral::healthBusy() const {
  return worker_active_.load();
}

bool BleCentral::jobFinished() const {
  return !worker_active_.load() &&
         (state_ == JobState::Done || state_ == JobState::Failed);
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
  const int slot = warm_next_;
  warm_next_ = (warm_next_ + 1) % kMaxClients;
  NimBLEClient* c = clients_[slot].client;
  if (!c) return nullptr;
  clients_[slot].discovered = false;
  strlcpy(clients_[slot].mac, mac.c_str(), sizeof clients_[slot].mac);
  warm_idx_ = slot;
  return c;
}

// Shared preamble for both job kinds: take the sighting slot, connect and
// subscribe to the notify characteristic. On any failure the job is finished
// as Failed (so the caller only returns false).
bool BleCentral::beginJob(const char* mac) {
  if (!jobAllowed()) { finishJob(JobState::Failed, Fail::Policy); return false; }
  const int slot = findSighting(mac);
  if (slot < 0) { finishJob(JobState::Failed, Fail::Connect); return false; }
  sample_count_ = 0;
  wearing_ok_ = true;
  ended_ = false;
  fail_ = Fail::None;
  state_ = JobState::Connecting;

  NimBLEAddress addr;
  portENTER_CRITICAL(&mux_);
  const bool fresh = sightings_[slot].used && strcmp(sightings_[slot].mac, mac) == 0 &&
      uint32_t(millis() - sightings_[slot].seen_ms) <= roztash::kSightingFreshMs;
  addr = sightings_[slot].addr;
  portEXIT_CRITICAL(&mux_);
  if (!fresh) { finishJob(JobState::Failed, Fail::Connect); return false; }

  NimBLEClient* c = clientFor(addr);
  if (!c) { finishJob(JobState::Failed, Fail::Connect); return false; }
  portENTER_CRITICAL(&mux_);
  job_client_ = c;
  portEXIT_CRITICAL(&mux_);
  if (!jobAllowed()) { finishJob(JobState::Failed, Fail::Policy); return false; }
  const bool warm = clients_[warm_idx_].discovered;
  connecting_ = true;
  const bool connected = c->isConnected() || c->connect(addr, !warm);
  connecting_ = false;
  if (!jobAllowed()) { finishJob(JobState::Failed, Fail::Policy); return false; }
  if (!connected) {
    Serial.printf("[ble] connect failed: %s\n", mac);
    finishJob(JobState::Failed, Fail::Connect);
    return false;
  }
  clients_[warm_idx_].discovered = true;

  NimBLERemoteService* svc = c->getService(kSvcUuid);
  if (!jobAllowed()) { finishJob(JobState::Failed, Fail::Policy); return false; }
  if (!svc) { finishJob(JobState::Failed, Fail::Subscribe); return false; }
  notify_char_ = svc->getCharacteristic(kNotifyUuid);
  if (!jobAllowed()) { finishJob(JobState::Failed, Fail::Policy); return false; }
  write_char_ = svc->getCharacteristic(kWriteUuid);
  if (!jobAllowed()) { finishJob(JobState::Failed, Fail::Policy); return false; }
  const uint32_t generation = job_generation_;
  if (!notify_char_ || !write_char_ ||
      !notify_char_->subscribe(
          true,
          [this, generation](NimBLERemoteCharacteristic*, uint8_t* data, size_t len, bool) {
            enqueueNotify(generation, data, len);
          },
          true)) {  // CCCD write WITH response — the band ignores no-response CCCD writes
    finishJob(JobState::Failed, Fail::Subscribe);
    return false;
  }
  if (!jobAllowed()) { finishJob(JobState::Failed, Fail::Policy); return false; }
  Serial.printf("[ble] subscribed; writing to %s\n", mac);
  return true;
}

bool BleCentral::runHealth(const char* mac, bool vitals) {
  (void)vitals;  // captured by launchJob before the worker is woken
  vitals_ = Vitals{};
  stage_ = Stage::Hr;
  stage_end_type_ = 0;
  stage_settle_ms_ = 0;
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
bool BleCentral::runVibrate(const char* mac) {
  vitals_ = Vitals{};
  vibrated_ = false;
  vibrate_write_pending_ = false;
  vibrate_write_at_ = millis();

  if (!beginJob(mac)) return false;
  Serial.printf("[ble] vibrate job started: %s repeat=%u resume=%u\n",
                mac, (unsigned)vibrate_repeats_, (unsigned)vibrate_acks_);
  job_started_ms_ = millis();
  stage_started_ms_ = job_started_ms_;
  state_ = JobState::Measuring;
  return true;
}

// Builds <cmd1=C+START><type> with the shared frame builder (same path as HR).
bool BleCentral::sendMeasureStart(uint8_t type) {
  if (!jobAllowed()) return false;
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
  if (!jobAllowed() || !job_client_ || !job_client_->isConnected()) return;

  if (NimBLERemoteService* svc = job_client_->getService(kBatterySvc)) {
    if (!jobAllowed()) return;
    if (NimBLERemoteCharacteristic* ch = svc->getCharacteristic(kBatteryChr)) {
      if (!jobAllowed()) return;
      const std::string v = ch->readValue();
      if (!jobAllowed()) return;
      if (!v.empty()) {
        vitals_.battery = (uint8_t)v[0];
        vitals_.battery_ok = true;
      }
    }
  }

  if (!jobAllowed()) return;
  if (NimBLERemoteService* svc = job_client_->getService(kDevInfoSvc)) {
    if (!jobAllowed()) return;
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
      if (!jobAllowed()) return;
      NimBLERemoteCharacteristic* ch = svc->getCharacteristic(*r.chr);
      if (!jobAllowed()) return;
      if (!ch) continue;
      const std::string v = ch->readValue();
      if (!jobAllowed()) return;
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

void BleCentral::pollMeasurement() {
  if (!jobAllowed()) { finishJob(JobState::Failed, Fail::Policy); return; }
  if (state_ != JobState::Measuring) return;
  if (!job_client_ || !job_client_->isConnected()) {
    finishJob(JobState::Failed, Fail::Connect);
    return;
  }
  const uint32_t now = millis();

  // Vibrate jobs end as soon as the band answers (05,50) — or after a short
  // grace window if the ack never arrives.
  if (vibrate_mode_) {
    if (vibrate_write_pending_ && vibrated_) {
      vibrate_write_pending_ = false;
      ++vibrate_acks_;
      if (vibrate_acks_ >= vibrate_repeats_) {
        finishJob(JobState::Done, Fail::None);
        Serial.printf("[ble] vibrate %s: pulses=%u\n", job_mac_, (unsigned)vibrate_acks_);
        return;
      }
      vibrated_ = false;
      vibrate_write_at_ = now + 250;
    }
    if (!vibrate_write_pending_ && vibrate_acks_ < vibrate_repeats_ &&
        static_cast<int32_t>(now - vibrate_write_at_) >= 0) {
      if (!jobAllowed()) { finishJob(JobState::Failed, Fail::Policy); return; }
      uint8_t frame[16];
      const size_t n = fundo::buildFrame(counter_++, fundo::CMD_FIND_DEVICE,
                                         fundo::SUB_FIND_DEVICE, nullptr, 0, frame);
      if (!n || !write_char_ || !write_char_->writeValue(frame, n, false)) {
        finishJob(JobState::Failed, Fail::Write);
        return;
      }
      vibrate_write_pending_ = true;
      vibrate_write_at_ = now;
    }
    if (vibrate_write_pending_ && now - vibrate_write_at_ > kStageSettleMs * 2) {
      finishJob(JobState::Failed, Fail::Timeout);
      Serial.printf("[ble] vibrate %s: ACK timeout after %u pulses\n",
                    job_mac_, (unsigned)vibrate_acks_);
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
  if (worker_active_.load()) return;
  portENTER_CRITICAL(&mux_);
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
  vibrate_emergency_ = false;
  vibrated_ = false;
  vibrate_acks_ = 0;
  vibrate_repeats_ = 1;
  vibrate_write_pending_ = false;
  vibrate_write_at_ = 0;
  vitals_ = Vitals{};
  portEXIT_CRITICAL(&mux_);
}

void BleCentral::onNotifyData(const uint8_t* data, size_t len) {
  if (!jobAllowed()) return;
  fundo::Parsed p;
  if (!fundo::parseFrame(data, len, p) || !p.valid || !p.crc_ok) {
    Serial.printf("[ble] notify unparsed (len=%u)\n", (unsigned)len);
    return;
  }
  Serial.printf("[ble] notify (%02X,%02X) dlen=%u stage=%u\n", p.cmd1, p.cmd2,
                (unsigned)p.data_len, (unsigned)stage_);

  // --- find-device (vibrate) ack (05,50) -------------------------------------
  if (p.cmd1 == fundo::CMD_FIND_DEVICE && p.cmd2 == fundo::SUB_FIND_DEVICE) {
    if (!vibrate_mode_ || !vibrate_write_pending_ || vibrated_) return;
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
