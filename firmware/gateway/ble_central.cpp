#include "ble_central.h"

// --- verified UUIDs (docs/band-protocol.md, live-tested 2026-10-10) ---------
static const char* kBandName = "PDMB1062";
static const NimBLEUUID kSvcUuid("4cdabaa0-2cea-c0c1-b38d-a0481ae60a97");
static const NimBLEUUID kWriteUuid("4cdabaa1-2cea-c0c1-b38d-a0481ae60a97");
static const NimBLEUUID kNotifyUuid("4cdabaa2-2cea-c0c1-b38d-a0481ae60a97");

static const uint8_t kHrStart[2] = {0x01, 0x01};  // measure type 1 (HR)
static const uint32_t kConnectTimeoutMs = 10000;

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
  scan_->setScanCallbacks(new ScanCb(this), false);  // wantDuplicates=false
  scan_->setInterval(scan_interval_ms_);
  scan_->setWindow(scan_window_ms_);
  scan_->setActiveScan(false);  // passive: name+services ride in the adv data
  scan_->start(0, false, true); // forever, restart on controller reset
  Serial.printf("[ble] scanning (int=%u win=%u ms)\n",
                (unsigned)scan_interval_ms_, (unsigned)scan_window_ms_);
}

// --- presence ---------------------------------------------------------------
void BleCentral::onResult(const NimBLEAdvertisedDevice* dev) {
  bool match = dev->haveName() && dev->getName() == kBandName;
  if (!match) {
    for (uint8_t i = 0; i < dev->getServiceUUIDCount(); ++i) {
      if (dev->getServiceUUID(i).equals(kSvcUuid)) { match = true; break; }
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

bool BleCentral::startHealth(const char* mac) {
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
          false)) {
    finishJob(JobState::Failed, Fail::Subscribe);
    return false;
  }

  uint8_t frame[16];
  const size_t n = fundo::buildFrame(counter_++, fundo::CMD_MEASURE,
                                     fundo::SUB_MEASURE_START, kHrStart, 2, frame);
  if (!n || !write_char_->writeValue(frame, n, false)) {
    finishJob(JobState::Failed, Fail::Write);
    return false;
  }

  Serial.printf("[ble] health job started: %s\n", mac);
  job_started_ms_ = millis();
  state_ = JobState::Measuring;
  return true;
}

void BleCentral::poll() {
  if (state_ != JobState::Measuring) return;
  const uint32_t now = millis();
  if (ended_ || !wearing_ok_) {
    finishJob(JobState::Done, Fail::None);
  } else if ((now - job_started_ms_) > measure_timeout_ms_) {
    finishJob(sample_count_ ? JobState::Done : JobState::Failed, Fail::Timeout);
  }
  if (state_ == JobState::Done) {
    Serial.printf("[ble] job done: %s samples=%u wearing=%d\n", job_mac_,
                  (unsigned)sample_count_, (int)wearing_ok_);
  }
}

void BleCentral::clearJob() {
  state_ = JobState::Idle;
  fail_ = Fail::None;
  job_client_ = nullptr;
  write_char_ = nullptr;
  notify_char_ = nullptr;
  sample_count_ = 0;
  job_mac_[0] = 0;
}

void BleCentral::onNotifyData(const uint8_t* data, size_t len) {
  fundo::Parsed p;
  if (!fundo::parseFrame(data, len, p) || !p.valid || !p.crc_ok) return;

  if (p.cmd1 == fundo::CMD_REALTIME && p.cmd2 == fundo::SUB_REALTIME_HR &&
      p.data_len >= 1) {
    if (sample_count_ < kMaxSamples) samples_[sample_count_++] = p.data[0];
  } else if (p.cmd1 == fundo::CMD_MEASURE &&
             p.cmd2 == fundo::SUB_MEASURE_ACK && p.data_len >= 1) {
    wearing_ok_ = (p.data[0] == 1);  // 0 = wearing error
    if (!wearing_ok_) Serial.printf("[ble] wearing error: %s\n", job_mac_);
  } else if (p.cmd1 == fundo::CMD_MEASURE &&
             p.cmd2 == fundo::SUB_MEASURE_END) {
    ended_ = true;
  }
}
