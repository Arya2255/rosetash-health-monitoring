#include "scan_policy.h"
#include "scan_policy_json.h"
#include "health_schedule.h"
#include "mqtt_packet_guard.h"
#include <string>
#include <cassert>
#include <cstdio>
#include <cstring>

static constexpr const char* A = "aa:bb:cc:dd:ee:01";
static constexpr const char* B = "aa:bb:cc:dd:ee:02";
static roztash::ScanPolicy fixture() {
  roztash::ScanPolicy p;
  std::strcpy(p.active[0].data(), A);
  std::strcpy(p.health[0].data(), A);
  p.active_count = p.health_count = 1;
  p.lease_s = 5;
  return p;
}

static void lease_lifecycle() {
  roztash::PolicyState s;
  assert(!s.ready(0) && !s.allows(A, 0));
  auto p = fixture();
  s.apply(p, 100);
  assert(s.ready(100) && s.scanEnabled(100));
  assert(s.allows(A, 100) && s.allowsHealth(A, 100));
  assert(!s.allows(B, 100));
  assert(s.ready(5099) && !s.ready(5100));
  assert(s.expire(5100) && !s.expire(5101));
  s.apply(p, UINT32_MAX - 999);
  assert(s.allows(A, 3999) && !s.allows(A, 4000));
  s.revoke();
  assert(!s.scanEnabled(0) && s.policy().active_count == 0);
  p.active_count = p.health_count = 0;
  s.apply(p, 0);
  assert(s.ready(0) && !s.scanEnabled(0));
}

static std::string wire(const std::string& active, const std::string& health,
                        const std::string& interval = "600", const std::string& lease = "90") {
  return "{\"v\":1,\"active_macs\":" + active + ",\"health_macs\":" + health +
         ",\"health_interval_s\":" + interval + ",\"lease_s\":" + lease +
         ",\"generated_at\":1700000000}";
}
static void parser_boundaries() {
  roztash::ScanPolicy p;
  const char* error = nullptr;
  auto parse = [&](const std::string& s) {
    return roztash::parseScanPolicy(s.data(), s.size(), p, error);
  };
  assert(parse(wire("[]", "[]")) && p.active_count == 0 && !error);
  const std::string one = "[\"aa:bb:cc:dd:ee:01\"]";
  assert(parse(wire(one, one)) && p.active_count == 1 && p.health_count == 1);
  assert(!parse(wire(one, one) + "junk"));
  assert(!parse(wire(one, one) + "{}"));
  assert(parse(wire(one, one) + " \n\t"));
  std::string fractional = wire(one, one);
  fractional.replace(fractional.find("1700000000"), 10, "1700000000.125");
  assert(parse(fractional));
  for (const auto& bad : {"null", "{}", "{", "[]", "true"}) assert(!parse(bad));
  assert(!parse(wire("null", "[]")));
  assert(!parse(wire("[1]", "[]")));
  assert(!parse(wire("[\"AA:bb:cc:dd:ee:01\"]", "[]")));
  assert(!parse(wire("[\"aa-bb-cc-dd-ee-01\"]", "[]")));
  assert(!parse(wire("[\"aa:bb:cc:dd:ee:01junk\"]", "[]")));
  assert(!parse(wire("[\"aa:bb:cc:dd:ee:01\",\"aa:bb:cc:dd:ee:01\"]", "[]")));
  assert(!parse(wire("[]", one)));
  for (const auto& bad : {"0", "-1", "86401", "1.5", "true", "\"600\"", "null"})
    assert(!parse(wire(one, one, bad)));
  for (const auto& bad : {"0", "91", "-1", "1.5", "true", "\"90\"", "null"})
    assert(!parse(wire(one, one, "600", bad)));
  assert(parse(wire(one, one, "1", "1")));
  assert(parse(wire(one, one, "86400", "90")));
  std::string all = "[";
  for (int i = 0; i < 256; ++i) {
    char mac[32]; std::snprintf(mac, sizeof mac, "\"aa:bb:cc:dd:ee:%02x\"", i);
    if (i) all += ',';
    all += mac;
  }
  all += ']';
  assert(parse(wire(all, all)) && p.active_count == 256 && p.health_count == 256);
  all.pop_back(); all += ",\"bb:bb:cc:dd:ee:ff\"]";
  assert(!parse(wire(all, "[]")) && std::strcmp(error, "capacity") == 0);
  assert(!parse(wire("[]", all)) && std::strcmp(error, "capacity") == 0);
}

static void sequential_windows() {
  roztash::PolicyState state;
  roztash::HealthSchedule queue;
  roztash::PolicyMac next{};
  auto p = fixture();
  std::strcpy(p.active[1].data(), B);
  std::strcpy(p.health[1].data(), B);
  p.active_count = p.health_count = 2;
  p.health_interval_s = 10; p.lease_s = 90;
  state.apply(p, 0); queue.sync(state, 0);
  for (uint32_t t : {5000, 9999}) {
    state.apply(p, t); queue.sync(state, t);
    assert(!queue.openIfDue(state, t));
  }
  assert(queue.openIfDue(state, 10000));
  assert(queue.next(state, 10000, next) && std::strcmp(next.data(), A) == 0);
  // A connection failed: advance once, do not close or retry the whole window.
  assert(queue.next(state, 10001, next) && std::strcmp(next.data(), B) == 0);
  p.health_interval_s = 20;
  state.apply(p, 10002); queue.sync(state, 10002);
  assert(!queue.next(state, 10002, next) && !queue.active());
  assert(!queue.openIfDue(state, 29999));
  assert(queue.openIfDue(state, 30000));
  assert(queue.generation() == 2);
  assert(queue.next(state, 30000, next) && std::strcmp(next.data(), A) == 0);
  // Revoked pending B must stay removed even if a later refresh re-adds it.
  p.health_count = 1; state.apply(p, 30001); queue.sync(state, 30001);
  p.health_count = 2; state.apply(p, 30002); queue.sync(state, 30002);
  assert(!queue.next(state, 30002, next));
  assert(queue.openIfDue(state, 50000));
  state.revoke(); queue.sync(state, 50001);
  assert(!queue.active() && !queue.next(state, 50001, next));
  state.apply(p, UINT32_MAX - 9999); queue.sync(state, UINT32_MAX - 9999);
  assert(!queue.openIfDue(state, 9999) && queue.openIfDue(state, 10000));
  assert(!queue.next(state, 80000, next)); // lease expired, no late GATT work
  p.active_count = p.health_count = 0;
  state.apply(p, 90000); queue.sync(state, 90000);
  assert(!queue.openIfDue(state, 110000));
}

static void no_overlap_when_overdue() {
  auto p = fixture(); p.lease_s = 90; p.health_interval_s = 1;
  roztash::PolicyState state; roztash::HealthSchedule queue; roztash::PolicyMac mac{};
  state.apply(p, 0); queue.sync(state, 0);
  assert(queue.openIfDue(state, 1000));
  assert(queue.next(state, 1000, mac));
  state.apply(p, 30000); queue.sync(state, 30000);
  assert(!queue.openIfDue(state, 30000)); // still finishing the previous job
  assert(!queue.next(state, 30000, mac)); // close the completed snapshot
  assert(queue.openIfDue(state, 30001));
  assert(queue.generation() == 2);       // no burst of missed intervals
}
static void mqtt_packet_boundaries() {
  roztash::MqttPacketGuard guard;
  for (uint8_t b : {0x31, 0x03, 0x00, 0x01, 0x61}) guard.feed(b);
  assert(guard.retained() && !guard.takeError());
  for (uint8_t b : {0x30, 0x03, 0x00, 0x01, 0x61}) guard.feed(b);
  assert(!guard.retained() && !guard.takeError());
  // 16384-byte remaining length plus header cannot fit a 16384-byte buffer.
  for (uint8_t b : {0x30, 0x80, 0x80, 0x01}) guard.feed(b);
  assert(guard.takeError() && !guard.takeError());
  for (size_t i = 0; i < 16384; ++i) guard.feed(0);
  for (uint8_t b : {0xd0, 0x00}) guard.feed(b); // back on a valid frame boundary
  assert(!guard.takeError());
  guard.reset();
  for (uint8_t b : {0x30, 0xff, 0xff, 0xff, 0xff}) guard.feed(b);
  assert(guard.takeError());
}

int main() {
  lease_lifecycle();
  parser_boundaries();
  sequential_windows();
  no_overlap_when_overdue();
  mqtt_packet_boundaries();
  std::puts("policy_schedule_host_test: 5 suites PASS (lease, parser/capacity, queue, overrun, MQTT frame guard)");
}
