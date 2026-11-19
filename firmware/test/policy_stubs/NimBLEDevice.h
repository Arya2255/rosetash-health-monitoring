// Minimal hardware boundary doubles; production BleCentral logic runs unchanged.
#pragma once
#include <Arduino.h>
#include <functional>
#include <vector>
constexpr uint16_t BLE_HS_CONN_HANDLE_NONE = 0xffff;
class NimBLEAddress {
  std::string mac_;
 public:
  NimBLEAddress() = default;
  explicit NimBLEAddress(const char* mac) : mac_(mac) {}
  std::string toString() const { return mac_; }
  bool equals(const NimBLEAddress& b) const { return mac_ == b.mac_; }
};
class NimBLEUUID { public: NimBLEUUID(const char*) {} NimBLEUUID(uint16_t) {} };
class NimBLEAdvertisedDevice {
  NimBLEAddress addr_;
  int rssi_;
 public:
  mutable unsigned rssi_reads = 0;
  NimBLEAdvertisedDevice(const char* mac, int rssi) : addr_(mac), rssi_(rssi) {}
  NimBLEAddress getAddress() const { return addr_; }
  int getRSSI() const { ++rssi_reads; return rssi_; }
};
class NimBLEScanCallbacks { public: virtual ~NimBLEScanCallbacks() = default; virtual void onResult(const NimBLEAdvertisedDevice*) {} };
class NimBLEScan {
 public:
  bool scanning = false, active = true;
  unsigned starts = 0, stops = 0, max_results = 255;
  NimBLEScanCallbacks* callback = nullptr;
  void setScanCallbacks(NimBLEScanCallbacks* cb, bool) { callback = cb; }
  void setInterval(uint16_t) {} void setWindow(uint16_t) {}
  void setActiveScan(bool b) { active = b; }
  void setMaxResults(uint8_t n) { max_results = n; }
  bool start(uint32_t, bool, bool) { scanning = true; ++starts; return true; }
  bool stop() { scanning = false; ++stops; return true; }
  bool isScanning() const { return scanning; }
};
class NimBLERemoteCharacteristic {
 public:
  using Callback = std::function<void(NimBLERemoteCharacteristic*, uint8_t*, size_t, bool)>;
  inline static std::function<void(NimBLERemoteCharacteristic&, const uint8_t*, size_t)> on_write;
  inline static std::string read_value;
  inline static unsigned read_calls = 0;
  inline static unsigned subscribe_calls = 0;
  bool subscribe(bool, Callback cb, bool) {
    ++subscribe_calls;
    callback_ = cb;
    return true;
  }
  bool writeValue(const uint8_t* data, size_t size, bool) {
    if (on_write) on_write(*this, data, size);
    return true;
  }
  void notify(uint8_t* data, size_t size) { if (callback_) callback_(this, data, size, true); }
  std::string readValue() { ++read_calls; return read_value; }
 private:
  Callback callback_;
};
class NimBLERemoteService {
  NimBLERemoteCharacteristic ch_;
 public: NimBLERemoteCharacteristic* getCharacteristic(const NimBLEUUID&) { return &ch_; }
};
class NimBLEClient {
  NimBLERemoteService svc_;
 public:
  bool connected = false;
  inline static unsigned connect_calls = 0;
  inline static bool connect_ok = true;
  void setConnectTimeout(uint32_t) {} void setConnectRetries(uint8_t) {}
  bool isConnected() const { return connected; }
  uint16_t getConnHandle() const { return connected ? 1 : BLE_HS_CONN_HANDLE_NONE; }
  bool connect(const NimBLEAddress&, bool) {
    ++connect_calls;
    connected = connect_ok;
    return connected;
  }
  bool disconnect() { connected = false; return true; }
  bool cancelConnect() { return true; }
  NimBLERemoteService* getService(const NimBLEUUID&) { return &svc_; }
};
class NimBLEDevice {
 public:
  inline static NimBLEScan scan;
  inline static NimBLEClient clients[3];
  inline static size_t client_idx = 0;
  static void init(const char*) {} static void setPower(int) {}
  static NimBLEScan* getScan() { return &scan; }
  static NimBLEClient* createClient() { return &clients[(client_idx++) % 3]; }
};
