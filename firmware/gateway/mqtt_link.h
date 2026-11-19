// gateway/mqtt_link.h — Ethernet + MQTT publishing with an offline queue.
//
// Topics (prefix = roztash/<gw_id>):
//   /status     retained heartbeat + LWT offline marker
//   /presence   periodic batch of {mac, rssi} sightings (10 s)
//   /health     finished measurement: {mac, bpm[], n, avg, wearing, ended, state}
//   /vitals     battery percent, device info and raw SpO2/HRV frames (same job)
//   /event      errors worth surfacing: wearing_error, connect_fail, ...
//   /scan-policy SUBSCRIBED, v1 leased non-retained software MAC policy
//   /cmd        SUBSCRIBED — remote commands: {"action":"vibrate","mac":"..."}
#pragma once

#include <Arduino.h>
#include <PubSubClient.h>
#include <Network.h>

#include "ble_central.h"
#include "config.h"
#include "network_config.h"
#include "health_schedule.h"
#include "mqtt_packet_guard.h"
#include "vibration_command.h"
#include "manual_measure.h"
#include "diagnostic_command.h"

class PolicyNetworkClient : public NetworkClient {
 public:
  roztash::MqttPacketGuard guard;
  int read() override {
    uint8_t b;
    return read(&b, 1) == 1 ? b : -1;
  }
  int read(uint8_t* out, size_t size) override {
    const int n = NetworkClient::read(out, size);
    for (int i = 0; i < n; ++i) guard.feed(out[i]);
    return n;
  }
};

class MqttLink {
 public:
  void begin(const GatewayConfig& cfg, BleCentral& ble, roztash::HealthSchedule& schedule);
  const roztash::PolicyState& policy() const { return policy_; }
  bool takeStatusRequest() { bool requested = status_pending_; status_pending_ = false; return requested; }
  void setBroker(const char* host, uint16_t port);
  void poll();  // Ethernet/MQTT reconnect + queue flush; call every loop()
  bool online() { return mqtt_.connected(); }
  bool networkReady() const;

  void publishStatus(const char* fw, const char* ip,
                     int bands_seen, uint32_t adv_seen);
  void publishPresence(BleCentral& ble);
  bool publishHealth(const BleCentral& ble);
  void publishVitals(const BleCentral& ble);
  void publishEvent(const char* type, const char* mac, const char* detail);

  // Remote commands from roztash/<gw>/cmd — consume-once.
  bool takeCommand(char* action, size_t action_cap, char* mac, size_t mac_cap,
                   bool* emergency = nullptr, uint8_t* repeats = nullptr,
                   uint8_t* completed_pulses = nullptr);
  void finishVibration(bool success, uint8_t completed_pulses, const char* detail = "");
  void rejectVibration(const char* detail, uint8_t completed_pulses = 0);

  // One bounded manual HR request is admitted independently of vibration and
  // the scheduled window, but is started only when the GATT worker is idle.
  bool takeManualMeasure(char* mac, size_t mac_cap, bool* vitals,
                         char* request_id, size_t request_id_cap);
  void manualMeasureStarted();
  void finishManualMeasure(const char* type, const char* detail = "");
  void rejectPendingManualMeasure(const char* detail);
  bool manualMeasurePending() const { return manual_measurements_.pending(); }
  bool manualMeasureActive() const { return manual_measurements_.active(); }
  bool cancelActiveManualMeasure(roztash::ManualMeasureCommand& command) {
    return manual_measurements_.cancelActive(command);
  }

  // Owner diagnostics are correlated, bounded and never persisted offline.
  bool takeDiagnostic(roztash::DiagnosticCommand& command);
  const roztash::DiagnosticCommand* activeDiagnostic() const {
    return diagnostics_.activeCommand();
  }
  bool diagnosticActive() const { return diagnostics_.active(); }
  void finishDiagnosticScan(const BleCentral& ble);
  void finishDiagnosticProbe(const BleCentral& ble);
  void rejectActiveDiagnostic(const char* detail);

 private:
  bool send(const char* topic, const char* payload, bool retained,
            bool queue_if_offline);
  bool queueLine(const char* topic, const char* payload);
  void flushQueue();
  void revokePolicy();
  void receivePolicy(const uint8_t* payload, size_t len);
  void publishCommandEvent(const char* type, const roztash::VibrationCommand& cmd,
                           const char* detail);
  void cancelPendingCommand(const char* detail);
  void publishManualEvent(const char* type,
                          const roztash::ManualMeasureCommand& command,
                          const char* detail);
  void publishDiagnosticReject(const roztash::DiagnosticCommand& command,
                               const char* detail);

  BleCentral* ble_ = nullptr;
  roztash::HealthSchedule* schedule_ = nullptr;
  roztash::PolicyState policy_;
  roztash::ScanPolicy incoming_policy_;  // large parser scratch, never on loop task stack
  bool status_pending_ = true;
  bool policy_installed_ = false;
  bool buffer_ready_ = false;
  PolicyNetworkClient net_;
  PubSubClient mqtt_{net_};
  GatewayConfig cfg_{};
  char base_[40] = {0};
  uint32_t last_mqtt_attempt_ms_ = 0;
  roztash::VibrationCommands vibration_commands_;
  roztash::ManualMeasureQueue manual_measurements_;
  roztash::DiagnosticRequests diagnostics_;
};
