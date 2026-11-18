// Bounded vibration commands. No Arduino runtime dependencies; host tested.
#pragma once
#include "scan_policy.h"
#include <ArduinoJson.h>

namespace roztash {
struct VibrationCommand {
  char mac[18]{};
  char request_id[65]{};
  char reason[65]{};
  uint32_t received_ms = 0;
  uint32_t ttl_ms = 120000;  // legacy manual commands are bounded too
  bool emergency = false;
  uint8_t repeats = 1;
  uint8_t completed_pulses = 0;
  bool tracked() const { return request_id[0] != 0; }
  bool expired(uint32_t now) const { return uint32_t(now - received_ms) >= ttl_ms; }
};

inline bool commandToken(JsonVariantConst value, char* out) {
  if (!value.is<const char*>()) return false;
  const JsonString s = value.as<JsonString>();
  if (!s.size() || s.size() > 64) return false;
  for (size_t i = 0; i < s.size(); ++i) {
    const char c = s.c_str()[i];
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-')) return false;
  }
  std::memcpy(out, s.c_str(), s.size());
  out[s.size()] = 0;
  return true;
}

inline bool parseVibrationCommand(const char* data, size_t size,
                                  VibrationCommand& out, const char*& error) {
  out = VibrationCommand{};
  error = "invalid_json";
  if (!data || !size || size > 1024) return false;
  // ArduinoJson accepts a valid prefix; reject extra objects/trailing bytes.
  auto ws = [](char c) { return c == ' ' || c == '\n' || c == '\r' || c == '\t'; };
  size_t first = 0;
  while (first < size && ws(data[first])) ++first;
  if (first == size || data[first] != '{') return false;
  unsigned depth = 0;
  bool quoted = false, escaped = false, complete = false;
  size_t end = size;
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
  const bool tracked = !obj["request_id"].isUnbound();
  if (tracked) {
    error = "invalid_request_id";
    if (!commandToken(obj["request_id"], out.request_id)) return false;
    error = "invalid_reason";
    if (!commandToken(obj["reason"], out.reason)) return false;
  } else if (!obj["reason"].isUnbound()) {
    error = "request_id_required";
    return false;
  }
  error = "invalid_mac";
  if (!obj["mac"].is<const char*>()) return false;
  const JsonString mac = obj["mac"].as<JsonString>();
  if (mac.size() != 17 || !canonicalMac(mac.c_str())) return false;
  std::memcpy(out.mac, mac.c_str(), sizeof out.mac);
  error = "invalid_action";
  if (!obj["action"].is<const char*>()) return false;
  const JsonString action = obj["action"].as<JsonString>();
  if (action.size() != 7 || std::memcmp(action.c_str(), "vibrate", 7)) return false;
  error = "invalid_emergency";
  if (!obj["emergency"].isUnbound()) {
    if (!obj["emergency"].is<bool>()) return false;
    out.emergency = obj["emergency"].as<bool>();
  }
  error = "invalid_ttl";
  if (tracked || !obj["ttl_s"].isUnbound()) {
    if (!obj["ttl_s"].is<uint32_t>()) return false;
    const uint32_t ttl = obj["ttl_s"].as<uint32_t>();
    if (ttl < 1 || ttl > 120) return false;
    out.ttl_ms = ttl * 1000UL;
  }
  error = "invalid_repeats";
  if (!obj["repeats"].isUnbound()) {
    if (!tracked || !obj["repeats"].is<uint8_t>()) return false;
    const uint8_t repeats = obj["repeats"].as<uint8_t>();
    if (repeats < 1 || repeats > 3) return false;
    out.repeats = repeats;
  }
  error = "invalid_completed_pulses";
  if (!obj["completed_pulses"].isUnbound()) {
    if (!tracked || !obj["completed_pulses"].is<uint8_t>()) return false;
    const uint8_t completed = obj["completed_pulses"].as<uint8_t>();
    if (completed > out.repeats) return false;
    out.completed_pulses = completed;
  }
  error = nullptr;
  return true;
}
enum class CommandOffer { Accepted, Duplicate, Completed, Conflict, Busy };
enum class CommandTake { None, Ready, Expired };

// Main-loop only. Keep context attached until the matching GATT result completes.
class VibrationCommands {
 public:
  CommandOffer offer(const VibrationCommand& command, uint32_t now) {
    if (command.tracked()) {
      if (pending_ && sameId(queued_, command))
        return sameTarget(queued_, command) ? CommandOffer::Duplicate : CommandOffer::Conflict;
      if (active_ && sameId(running_, command))
        return sameTarget(running_, command) ? CommandOffer::Duplicate : CommandOffer::Conflict;
      for (auto& result : completed_) {
        if (result.used && uint32_t(now - result.at) >= kRememberMs) result.used = false;
        if (result.used && sameId(result.command, command)) {
          if (!sameTarget(result.command, command)) return CommandOffer::Conflict;
          if (result.command.completed_pulses >= command.repeats) return CommandOffer::Completed;
          // A retry must never replace a different command that is already
          // waiting for the single GATT slot.
          if (pending_) return CommandOffer::Busy;
          queued_ = command;
          queued_.completed_pulses = result.command.completed_pulses > command.completed_pulses
              ? result.command.completed_pulses : command.completed_pulses;
          queued_.received_ms = now;
          pending_ = true;
          return CommandOffer::Accepted;
        }
      }
    }
    if (pending_) return CommandOffer::Busy;
    queued_ = command;
    queued_.received_ms = now;
    pending_ = true;
    return CommandOffer::Accepted;
  }
  CommandTake take(uint32_t now, VibrationCommand& out) {
    if (!pending_ || active_) return CommandTake::None;
    out = queued_;
    pending_ = false;
    if (out.expired(now)) return CommandTake::Expired;
    running_ = out;
    active_ = true;
    return CommandTake::Ready;
  }
  bool cancelPending(VibrationCommand& out) {
    if (!pending_) return false;
    out = queued_;
    pending_ = false;
    return true;
  }
  const VibrationCommand* active() const { return active_ ? &running_ : nullptr; }
  const VibrationCommand* pending() const { return pending_ ? &queued_ : nullptr; }
  uint8_t completedPulses(const VibrationCommand& command, uint32_t now) {
    for (auto& result : completed_) {
      if (result.used && uint32_t(now - result.at) >= kRememberMs) result.used = false;
      if (result.used && sameId(result.command, command) && sameTarget(result.command, command))
        return result.command.completed_pulses;
    }
    return 0;
  }
  void finish(bool success, uint32_t now, uint8_t completed_pulses = 0) {
    (void)success;
    if (!active_) return;
    if (running_.tracked()) {
      if (success && completed_pulses == 0) completed_pulses = running_.repeats;
      running_.completed_pulses = completed_pulses;
      Completed* slot = nullptr;
      for (auto& result : completed_) {
        if (result.used && sameId(result.command, running_)) { slot = &result; break; }
        if (!result.used && !slot) slot = &result;
      }
      if (!slot) { slot = &completed_[next_]; next_ = (next_ + 1) % completed_.size(); }
      *slot = Completed{running_, now, true};
    }
    active_ = false;
    running_ = VibrationCommand{};
  }
 private:
  static constexpr uint32_t kRememberMs = 600000;
  struct Completed { VibrationCommand command{}; uint32_t at = 0; bool used = false; };
  static bool sameId(const VibrationCommand& a, const VibrationCommand& b) {
    return std::strcmp(a.request_id, b.request_id) == 0;
  }
  static bool sameTarget(const VibrationCommand& a, const VibrationCommand& b) {
    return std::strcmp(a.mac, b.mac) == 0 && std::strcmp(a.reason, b.reason) == 0 &&
           a.emergency == b.emergency && a.repeats == b.repeats;
  }
  std::array<Completed, 32> completed_{};
  size_t next_ = 0;
  VibrationCommand queued_{}, running_{};
  bool pending_ = false, active_ = false;
};
}  // namespace roztash
