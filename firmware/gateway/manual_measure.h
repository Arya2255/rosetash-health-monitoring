#pragma once

#include "scan_policy.h"
#include "hr_sample.h"
#include <ArduinoJson.h>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace roztash {
struct ManualMeasureCommand {
  char mac[18]{};
  char request_id[65]{};
  uint32_t received_ms = 0;
  uint32_t ttl_ms = 0;
  bool vitals = false;
  bool expired(uint32_t now) const { return uint32_t(now - received_ms) >= ttl_ms; }
};

enum class ManualMeasureOffer { Accepted, Duplicate, Conflict, Busy };
enum class ManualMeasureTake { None, Ready, Expired };

inline bool measureRequestId(const char* value, size_t size) {
  static constexpr char prefix[] = "measure-";
  if (!value || size <= sizeof(prefix) - 1 || size > 64 ||
      std::memcmp(value, prefix, sizeof(prefix) - 1) != 0) return false;
  for (size_t i = sizeof(prefix) - 1; i < size; ++i)
    if (!((value[i] >= '0' && value[i] <= '9') ||
          (value[i] >= 'a' && value[i] <= 'f'))) return false;
  return true;
}

// Strict, single-object parser for the manual HR-only protocol. Accepted keys
// are exactly action, mac, request_id, ttl_s and vitals.
inline bool parseManualMeasureCommand(const char* data, size_t size,
                                      ManualMeasureCommand& out, const char*& error) {
  out = ManualMeasureCommand{};
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
  if (obj.size() != 5) { error = "unexpected_fields"; return false; }
  for (JsonPairConst pair : obj) {
    const char* key = pair.key().c_str();
    if (std::strcmp(key, "action") && std::strcmp(key, "mac") &&
        std::strcmp(key, "request_id") && std::strcmp(key, "ttl_s") &&
        std::strcmp(key, "vitals")) {
      error = "unexpected_fields";
      return false;
    }
  }
  error = "invalid_action";
  if (!obj["action"].is<const char*>()) return false;
  const JsonString action = obj["action"].as<JsonString>();
  if (action.size() != 7 || std::memcmp(action.c_str(), "measure", 7)) return false;
  error = "invalid_mac";
  if (!obj["mac"].is<const char*>()) return false;
  const JsonString mac = obj["mac"].as<JsonString>();
  if (mac.size() != 17 || !canonicalMac(mac.c_str())) return false;
  std::memcpy(out.mac, mac.c_str(), sizeof out.mac);
  error = "invalid_request_id";
  if (!obj["request_id"].is<const char*>()) return false;
  const JsonString id = obj["request_id"].as<JsonString>();
  if (!measureRequestId(id.c_str(), id.size())) return false;
  std::memcpy(out.request_id, id.c_str(), id.size());
  out.request_id[id.size()] = '\0';
  error = "invalid_ttl";
  if (!obj["ttl_s"].is<uint32_t>()) return false;
  const uint32_t ttl = obj["ttl_s"].as<uint32_t>();
  if (ttl < 1 || ttl > 60) return false;
  out.ttl_ms = ttl * 1000UL;
  error = "invalid_vitals";
  if (!obj["vitals"].is<bool>() || obj["vitals"].as<bool>()) return false;
  out.vitals = false;
  error = nullptr;
  return true;
}

inline bool isManualMeasureAction(const char* data, size_t size) {
  if (!data || !size || size > 1024) return false;
  JsonDocument doc;
  if (deserializeJson(doc, data, size, DeserializationOption::NestingLimit(3)) ||
      !doc.is<JsonObject>() || !doc["action"].is<const char*>()) return false;
  const JsonString action = doc["action"].as<JsonString>();
  return action.size() == 7 && std::memcmp(action.c_str(), "measure", 7) == 0;
}

class ManualMeasureQueue {
 public:
  static constexpr size_t kRecent = 8;
  ManualMeasureOffer offer(const ManualMeasureCommand& command, uint32_t now) {
    purge(now);
    if (pending_ && sameId(queued_, command))
      return sameTarget(queued_, command) ? ManualMeasureOffer::Duplicate : ManualMeasureOffer::Conflict;
    if (active_ && sameId(running_, command))
      return sameTarget(running_, command) ? ManualMeasureOffer::Duplicate : ManualMeasureOffer::Conflict;
    for (const Recent& item : recent_)
      if (item.used && sameId(item.command, command))
        return sameTarget(item.command, command) ? ManualMeasureOffer::Duplicate : ManualMeasureOffer::Conflict;
    if (pending_ || active_) return ManualMeasureOffer::Busy;
    queued_ = command;
    queued_.received_ms = now;
    pending_ = true;
    return ManualMeasureOffer::Accepted;
  }
  ManualMeasureTake take(uint32_t now, ManualMeasureCommand& out) {
    if (!pending_ || active_) return ManualMeasureTake::None;
    out = queued_;
    pending_ = false;
    queued_ = ManualMeasureCommand{};
    if (out.expired(now)) return ManualMeasureTake::Expired;
    running_ = out;
    active_ = true;
    return ManualMeasureTake::Ready;
  }
  const ManualMeasureCommand* activeCommand() const { return active_ ? &running_ : nullptr; }
  const ManualMeasureCommand* pendingCommand() const { return pending_ ? &queued_ : nullptr; }
  bool pending() const { return pending_; }
  bool active() const { return active_; }
  bool cancelPending(ManualMeasureCommand& out) {
    if (!pending_) return false;
    out = queued_;
    queued_ = ManualMeasureCommand{};
    pending_ = false;
    return true;
  }
  bool cancelActive(ManualMeasureCommand& out) {
    if (!active_) return false;
    out = running_;
    running_ = ManualMeasureCommand{};
    active_ = false;
    return true;
  }
  void finish(uint32_t now) {
    if (!active_) return;
    recent_[next_recent_] = Recent{running_, now, true};
    next_recent_ = (next_recent_ + 1) % kRecent;
    running_ = ManualMeasureCommand{};
    active_ = false;
  }
 private:
  struct Recent { ManualMeasureCommand command{}; uint32_t at = 0; bool used = false; };
  static bool sameId(const ManualMeasureCommand& a, const ManualMeasureCommand& b) {
    return std::strcmp(a.request_id, b.request_id) == 0;
  }
  static bool sameTarget(const ManualMeasureCommand& a, const ManualMeasureCommand& b) {
    return std::strcmp(a.mac, b.mac) == 0 && a.vitals == b.vitals;
  }
  void purge(uint32_t now) {
    for (Recent& item : recent_)
      if (item.used && uint32_t(now - item.at) >= 60000) item.used = false;
  }
  ManualMeasureCommand queued_{}, running_{};
  Recent recent_[kRecent]{};
  size_t next_recent_ = 0;
  bool pending_ = false, active_ = false;
};

inline bool manualMeasureAllowed(const PolicyState& policy, const char* mac,
                                 uint32_t now, bool fresh_sighting) {
  return fresh_sighting && policy.allowsHealth(mac, now);
}
}  // namespace roztash
