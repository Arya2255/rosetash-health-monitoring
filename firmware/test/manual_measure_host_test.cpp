#include "manual_measure.h"
#include "hr_sample.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>

static constexpr const char* MAC = "aa:bb:cc:dd:ee:01";
static const std::string valid =
    "{\"action\":\"measure\",\"mac\":\"aa:bb:cc:dd:ee:01\","
    "\"request_id\":\"measure-a1b2c3\",\"ttl_s\":60,\"vitals\":false}";

static void parser_accepts_only_the_manual_hr_contract() {
  roztash::ManualMeasureCommand cmd{};
  const char* error = nullptr;
  assert(roztash::parseManualMeasureCommand(valid.data(), valid.size(), cmd, error));
  assert(!error && std::strcmp(cmd.mac, MAC) == 0);
  assert(std::strcmp(cmd.request_id, "measure-a1b2c3") == 0);
  assert(cmd.ttl_ms == 60000 && !cmd.vitals);

  for (const std::string& bad : {
      std::string("{}"),
      std::string("[]"),
      valid + "{}",
      valid + "garbage",
      std::string("{\"action\":\"vibrate\",\"mac\":\"aa:bb:cc:dd:ee:01\",\"request_id\":\"measure-aa\",\"ttl_s\":60,\"vitals\":false}"),
      std::string("{\"action\":\"measure\",\"mac\":\"AA:BB:CC:DD:EE:01\",\"request_id\":\"measure-aa\",\"ttl_s\":60,\"vitals\":false}"),
      std::string("{\"action\":\"measure\",\"mac\":\"aa:bb:cc:dd:ee:01\",\"request_id\":\"measure-g1\",\"ttl_s\":60,\"vitals\":false}"),
      std::string("{\"action\":\"measure\",\"mac\":\"aa:bb:cc:dd:ee:01\",\"request_id\":\"measure-aa\",\"ttl_s\":0,\"vitals\":false}"),
      std::string("{\"action\":\"measure\",\"mac\":\"aa:bb:cc:dd:ee:01\",\"request_id\":\"measure-aa\",\"ttl_s\":61,\"vitals\":false}"),
      std::string("{\"action\":\"measure\",\"mac\":\"aa:bb:cc:dd:ee:01\",\"request_id\":\"measure-aa\",\"ttl_s\":60,\"vitals\":true}"),
      std::string("{\"action\":\"measure\",\"mac\":\"aa:bb:cc:dd:ee:01\",\"request_id\":\"measure-aa\",\"ttl_s\":60,\"vitals\":0}"),
      std::string("{\"action\":\"measure\",\"mac\":\"aa:bb:cc:dd:ee:01\",\"request_id\":\"measure-aa\",\"ttl_s\":60,\"vitals\":false,\"extra\":1}")}) {
    cmd = roztash::ManualMeasureCommand{};
    assert(!roztash::parseManualMeasureCommand(bad.data(), bad.size(), cmd, error));
    assert(error != nullptr);
  }
}

static void queue_is_bounded_idempotent_and_expires_without_interrupting_work() {
  roztash::ManualMeasureCommand cmd{};
  const char* error = nullptr;
  assert(roztash::parseManualMeasureCommand(valid.data(), valid.size(), cmd, error));
  roztash::ManualMeasureQueue q;
  assert(q.offer(cmd, 100) == roztash::ManualMeasureOffer::Accepted);
  assert(q.offer(cmd, 101) == roztash::ManualMeasureOffer::Duplicate);
  auto other = cmd;
  std::strcpy(other.request_id, "measure-bb");
  assert(q.offer(other, 102) == roztash::ManualMeasureOffer::Busy);
  roztash::ManualMeasureCommand taken{};
  assert(q.take(100, taken) == roztash::ManualMeasureTake::Ready);
  assert(q.active() && std::strcmp(taken.request_id, cmd.request_id) == 0);
  assert(q.offer(other, 103) == roztash::ManualMeasureOffer::Busy);
  q.finish(103);
  assert(!q.active());
  assert(q.offer(other, 104) == roztash::ManualMeasureOffer::Accepted);
  assert(q.take(60104, taken) == roztash::ManualMeasureTake::Expired);
  assert(!q.active() && !q.pending());

  assert(q.offer(cmd, UINT32_MAX - 1000) == roztash::ManualMeasureOffer::Accepted);
  assert(q.take(58998, taken) == roztash::ManualMeasureTake::Ready);
  q.finish(58998);
}

static void manual_measure_requires_health_policy_and_fresh_sighting() {
  roztash::ScanPolicy p;
  p.lease_s = 5;
  p.active_count = 1;
  std::strcpy(p.active[0].data(), MAC);
  roztash::PolicyState state;
  state.apply(p, 100);
  assert(!roztash::manualMeasureAllowed(state, MAC, 100, true));
  assert(!roztash::manualMeasureAllowed(state, MAC, 100, false));
  std::strcpy(p.health[0].data(), MAC);
  p.health_count = 1;
  state.apply(p, 100);
  assert(roztash::manualMeasureAllowed(state, MAC, 100, true));
  assert(!roztash::manualMeasureAllowed(state, MAC, 100, false));
  assert(!roztash::manualMeasureAllowed(state, MAC, 5100, true));
  assert(!roztash::manualMeasureAllowed(state, "ff:ee:dd:cc:bb:aa", 101, true));
}

static void manual_success_requires_a_valid_hr_sample() {
  assert(!roztash::isValidHrSample(0));
  assert(!roztash::isValidHrSample(1));
  assert(!roztash::isValidHrSample(29));
  assert(roztash::isValidHrSample(30));
  assert(roztash::isValidHrSample(120));
  assert(roztash::isValidHrSample(240));
  assert(!roztash::isValidHrSample(241));
}

static void mixed_hr_samples_publish_only_valid_values() {
  const uint8_t input[] = {0, 89, 241, 120, 29};
  uint8_t output[8] = {};
  uint32_t sum = 0;
  const uint8_t count = roztash::filterHrSamples(input, 5, output, &sum);
  assert(count == 2);
  assert(output[0] == 89 && output[1] == 120);
  assert(sum == 209);
}

int main() {
  parser_accepts_only_the_manual_hr_contract();
  queue_is_bounded_idempotent_and_expires_without_interrupting_work();
  manual_measure_requires_health_policy_and_fresh_sighting();
  manual_success_requires_a_valid_hr_sample();
  mixed_hr_samples_publish_only_valid_values();
  std::puts("manual_measure_host_test: parser, policy, queue, TTL, dedupe and valid-HR gate PASS");
}
