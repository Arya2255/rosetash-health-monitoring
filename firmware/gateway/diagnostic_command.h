// Bounded owner-initiated BLE diagnostic commands. No Arduino runtime state.
#pragma once
#include "scan_policy.h"
#include <ArduinoJson.h>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace roztash {

enum class DiagnosticAction : uint8_t { None, Scan, Probe };

struct DiagnosticCommand {
  DiagnosticAction action = DiagnosticAction::None;
  char request_id[38]{};
  char mac[18]{};
  uint32_t received_ms = 0;
  uint32_t ttl_ms = 0;
  bool expired(uint32_t now) const { return uint32_t(now - received_ms) >= ttl_ms; }
};

inline bool diagnosticRequestId(const char* value, size_t size) {
  static constexpr char prefix[] = "diag-";
  if (!value || size != 37 || std::memcmp(value, prefix, sizeof(prefix) - 1) != 0)
    return false;
  for (size_t i = sizeof(prefix) - 1; i < size; ++i)
    if (!((value[i] >= '0' && value[i] <= '9') ||
          (value[i] >= 'a' && value[i] <= 'f'))) return false;
  return true;
}

// Strict, single-object parser. Scan accepts exactly action/request_id/ttl_s;
// probe additionally requires a canonical MAC. No normalization or partial use.
inline bool parseDiagnosticCommand(const char* data, size_t size,
                                   DiagnosticCommand& out, const char*& error) {
  out = DiagnosticCommand{};
  error = "invalid_json";
  if (!data || !size || size > 1024) return false;
  auto ws = [](char c) { return c == ' ' || c == '\n' || c == '\r' || c == '\t'; };
  size_t first = 0;
  while (first < size && ws(data[first])) ++first;
  if (first == size || data[first] != '{') return false;
  size_t end = size;
  unsigned depth = 0;
  bool quoted = false, escaped = false, complete = false;
  for (size_t i = first; i < size; ++i) {
    const char c = data[i];
    if (quoted) {
      if (escaped) escaped = false;
      else if (c == '\\') escaped = true;
      else if (c == '"') quoted = false;
    } else if (c == '"') quoted = true;
    else if (c == '{' || c == '[') ++depth;
    else if (c == '}' || c == ']') {
      if (!depth) return false;
      if (--depth == 0) { end = i + 1; complete = true; break; }
    }
  }
  if (!complete) return false;
  for (size_t i = end; i < size; ++i) if (!ws(data[i])) return false;

  JsonDocument doc;
  if (deserializeJson(doc, data, size, DeserializationOption::NestingLimit(3)) ||
      !doc.is<JsonObject>()) return false;
  const JsonObjectConst obj = doc.as<JsonObjectConst>();

  error = "invalid_action";
  if (!obj["action"].is<const char*>()) return false;
  const JsonString action = obj["action"].as<JsonString>();
  static constexpr char scan[] = "diagnostic_scan";
  static constexpr char probe[] = "diagnostic_probe";
  if (action.size() == sizeof(scan) - 1 &&
      std::memcmp(action.c_str(), scan, sizeof(scan) - 1) == 0)
    out.action = DiagnosticAction::Scan;
  else if (action.size() == sizeof(probe) - 1 &&
           std::memcmp(action.c_str(), probe, sizeof(probe) - 1) == 0)
    out.action = DiagnosticAction::Probe;
  else return false;

  error = "invalid_request_id";
  if (!obj["request_id"].is<const char*>()) return false;
  const JsonString id = obj["request_id"].as<JsonString>();
  if (!diagnosticRequestId(id.c_str(), id.size())) return false;
  std::memcpy(out.request_id, id.c_str(), id.size());
  out.request_id[id.size()] = '\0';

  error = "invalid_ttl";
  if (!obj["ttl_s"].is<uint32_t>()) return false;
  const uint32_t ttl = obj["ttl_s"].as<uint32_t>();
  if (ttl < 1 || ttl > 60) return false;
  out.ttl_ms = ttl * 1000UL;

  if (out.action == DiagnosticAction::Probe) {
    error = "invalid_mac";
    if (!obj["mac"].is<const char*>()) return false;
    const JsonString mac = obj["mac"].as<JsonString>();
    if (mac.size() != 17 || !canonicalMac(mac.c_str())) return false;
    std::memcpy(out.mac, mac.c_str(), sizeof out.mac);
  }

  error = "unexpected_fields";
  const size_t expected = out.action == DiagnosticAction::Probe ? 4 : 3;
  if (obj.size() != expected) return false;
  for (JsonPairConst pair : obj) {
    const char* key = pair.key().c_str();
    if (std::strcmp(key, "action") && std::strcmp(key, "request_id") &&
        std::strcmp(key, "ttl_s") &&
        (out.action != DiagnosticAction::Probe || std::strcmp(key, "mac"))) return false;
  }
  error = nullptr;
  return true;
}

inline bool isDiagnosticAction(const char* data, size_t size) {
  if (!data || !size || size > 1024) return false;
  JsonDocument doc;
  if (deserializeJson(doc, data, size, DeserializationOption::NestingLimit(3)) ||
      !doc.is<JsonObject>() || !doc["action"].is<const char*>()) return false;
  const JsonString action = doc["action"].as<JsonString>();
  static constexpr char scan[] = "diagnostic_scan";
  static constexpr char probe[] = "diagnostic_probe";
  return (action.size() == sizeof(scan) - 1 &&
          std::memcmp(action.c_str(), scan, sizeof(scan) - 1) == 0) ||
         (action.size() == sizeof(probe) - 1 &&
          std::memcmp(action.c_str(), probe, sizeof(probe) - 1) == 0);
}

enum class DiagnosticOffer { Accepted, Duplicate, Conflict, Busy };
enum class DiagnosticTake { None, Ready, Expired };

// Main-loop only. One operation is admitted; request IDs remain bound to their
// action/target for a bounded window so retries cannot start duplicate work.
class DiagnosticRequests {
 public:
  static constexpr size_t kRecent = 8;

  DiagnosticOffer offer(const DiagnosticCommand& command, uint32_t now) {
    purge(now);
    if (pending_ && sameId(queued_, command))
      return sameTarget(queued_, command) ? DiagnosticOffer::Duplicate
                                         : DiagnosticOffer::Conflict;
    if (active_ && sameId(running_, command))
      return sameTarget(running_, command) ? DiagnosticOffer::Duplicate
                                          : DiagnosticOffer::Conflict;
    for (const Recent& item : recent_)
      if (item.used && sameId(item.command, command))
        return sameTarget(item.command, command) ? DiagnosticOffer::Duplicate
                                                : DiagnosticOffer::Conflict;
    if (pending_ || active_) return DiagnosticOffer::Busy;
    queued_ = command;
    queued_.received_ms = now;
    pending_ = true;
    return DiagnosticOffer::Accepted;
  }

  DiagnosticTake take(uint32_t now, DiagnosticCommand& out) {
    if (!pending_ || active_) return DiagnosticTake::None;
    out = queued_;
    queued_ = DiagnosticCommand{};
    pending_ = false;
    if (out.expired(now)) return DiagnosticTake::Expired;
    running_ = out;
    active_ = true;
    return DiagnosticTake::Ready;
  }

  const DiagnosticCommand* activeCommand() const { return active_ ? &running_ : nullptr; }
  bool pending() const { return pending_; }
  bool active() const { return active_; }

  bool cancelPending(DiagnosticCommand& out) {
    if (!pending_) return false;
    out = queued_;
    queued_ = DiagnosticCommand{};
    pending_ = false;
    return true;
  }

  void finish(uint32_t now) {
    if (!active_) return;
    recent_[next_recent_] = Recent{running_, now, true};
    next_recent_ = (next_recent_ + 1) % kRecent;
    running_ = DiagnosticCommand{};
    active_ = false;
  }

 private:
  struct Recent { DiagnosticCommand command{}; uint32_t at = 0; bool used = false; };
  static bool sameId(const DiagnosticCommand& a, const DiagnosticCommand& b) {
    return std::strcmp(a.request_id, b.request_id) == 0;
  }
  static bool sameTarget(const DiagnosticCommand& a, const DiagnosticCommand& b) {
    return a.action == b.action && std::strcmp(a.mac, b.mac) == 0;
  }
  void purge(uint32_t now) {
    for (Recent& item : recent_)
      if (item.used && uint32_t(now - item.at) >= 60000) item.used = false;
  }

  DiagnosticCommand queued_{}, running_{};
  Recent recent_[kRecent]{};
  size_t next_recent_ = 0;
  bool pending_ = false, active_ = false;
};

}  // namespace roztash
