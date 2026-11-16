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
  bool subscribe(bool, Callback, bool) { return true; }
  bool writeValue(const uint8_t*, size_t, bool) { return true; }
  std::string readValue() { return {}; }
};
class NimBLERemoteService {
  NimBLERemoteCharacteristic ch_;
 public: NimBLERemoteCharacteristic* getCharacteristic(const NimBLEUUID&) { return &ch_; }
};
class NimBLEClient {
  NimBLERemoteService svc_;
 public:
  bool connected = false;
  void setConnectTimeout(uint32_t) {} void setConnectRetries(uint8_t) {}
  bool isConnected() const { return connected; }
  uint16_t getConnHandle() const { return connected ? 1 : BLE_HS_CONN_HANDLE_NONE; }
  bool connect(const NimBLEAddress&, bool) { connected = true; return true; }
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
