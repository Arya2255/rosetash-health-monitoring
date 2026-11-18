#pragma once
#include "scan_policy.h"
#include <ArduinoJson.h>
#include <cmath>

namespace roztash {
// Strict input validation: never normalize, truncate, or partially apply a list.
// `out` is scratch space and MUST NOT be installed when this returns false.
inline bool parseScanPolicy(const char* data, size_t size, ScanPolicy& out,
                            const char*& error) {
  error = "json";
  // ArduinoJson intentionally accepts trailing bytes. Require exactly one
  // top-level object so a valid prefix cannot hide malformed trailing input.
  size_t first = 0;
  auto ws = [](char c) { return c == ' ' || c == '\n' || c == '\r' || c == '\t'; };
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
  if (deserializeJson(doc, data, size, DeserializationOption::NestingLimit(4))) return false;
  if (!doc.is<JsonObject>()) return false;
  error = "version";
  if (!doc["v"].is<uint32_t>() || doc["v"].as<uint32_t>() != 1) return false;
  error = "lease_s";
  if (!doc["lease_s"].is<uint32_t>()) return false;
  const uint32_t lease = doc["lease_s"].as<uint32_t>();
  if (lease < 1 || lease > 90) return false;
  error = "health_interval_s";
  if (!doc["health_interval_s"].is<uint32_t>()) return false;
  const uint32_t interval = doc["health_interval_s"].as<uint32_t>();
  if (interval < 1 || interval > kMaxHealthIntervalS) return false;
  error = "generated_at";
  // Metadata only: lease lifetime is measured from local monotonic receipt.
  if (!doc["generated_at"].is<double>()) return false;
  const double generated = doc["generated_at"].as<double>();
  if (!std::isfinite(generated) || generated <= 0) return false;
  error = "mac_arrays";
  if (!doc["active_macs"].is<JsonArray>() || !doc["health_macs"].is<JsonArray>()) return false;
  JsonArrayConst active = doc["active_macs"].as<JsonArrayConst>();
  JsonArrayConst health = doc["health_macs"].as<JsonArrayConst>();
  JsonArrayConst emergency = doc["emergency_macs"].is<JsonArray>()
      ? doc["emergency_macs"].as<JsonArrayConst>() : JsonArrayConst();
  error = "capacity";
  if (active.size() > kMaxPolicyMacs || health.size() > kMaxPolicyMacs ||
      emergency.size() > kMaxPolicyMacs) return false;
  out.active_count = out.health_count = out.emergency_count = 0;
  auto load = [&](JsonArrayConst src, PolicyMac* dst, size_t& count) {
    for (JsonVariantConst item : src) {
      error = "mac_format";
      if (!item.is<const char*>()) return false;
      const JsonString text = item.as<JsonString>();
      const char* mac = text.c_str();
      if (text.size() != 17 || !canonicalMac(mac)) return false;
      error = "duplicate_mac";
      if (containsMac(dst, count, mac)) return false;
      std::memcpy(dst[count++].data(), mac, 18);
    }
    return true;
  };
  if (!load(active, out.active.data(), out.active_count) ||
      !load(health, out.health.data(), out.health_count) ||
      !load(emergency, out.emergency.data(), out.emergency_count)) return false;
  error = "health_not_active";
  for (size_t i = 0; i < out.health_count; ++i)
    if (!containsMac(out.active.data(), out.active_count, out.health[i].data())) return false;
  out.lease_s = lease;
  out.health_interval_s = interval;
  error = nullptr;
  return true;
}
}  // namespace roztash
