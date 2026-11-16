// Pure production command parsing/state; no hardware, network or Arduino runtime.
#include "vibration_command.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>

static constexpr const char* A = "aa:bb:cc:dd:ee:01";
static constexpr const char* B = "aa:bb:cc:dd:ee:02";
static std::string wire(const std::string& id = "battery-0123456789abcdef0123456789abcdef",
                        const std::string& mac = A, const std::string& reason = "battery_low",
                        const std::string& ttl = "60") {
  return "{\"action\":\"vibrate\",\"mac\":\"" + mac + "\",\"request_id\":\"" + id +
      "\",\"reason\":\"" + reason + "\",\"ttl_s\":" + ttl + "}";
}
static bool parse(const std::string& text, roztash::VibrationCommand& cmd, const char*& error) {
  return roztash::parseVibrationCommand(text.data(), text.size(), cmd, error);
}
static void parser_boundaries() {
  roztash::VibrationCommand cmd;
  const char* error = nullptr;
  assert(parse(wire(), cmd, error) && !error);
  assert(std::strcmp(cmd.mac, A) == 0 && std::strcmp(cmd.reason, "battery_low") == 0);
  assert(cmd.tracked() && cmd.ttl_ms == 60000);
  assert(parse(wire(std::string(64, 'A')), cmd, error));
  assert(parse(wire("abc.A-Z_019-"), cmd, error));
  for (const auto& id : {std::string(), std::string(65, 'a'), std::string("a b"),
                         std::string("a/b"), std::string("a\\u0000b"), std::string("é")})
    assert(!parse(wire(id), cmd, error));
  for (const char* ttl : {"0", "121", "-1", "1.5", "true", "\"60\"", "null"})
    assert(!parse(wire("id", A, "battery_low", ttl), cmd, error));
  assert(parse(wire("id", A, "battery_low", "1"), cmd, error) && cmd.ttl_ms == 1000);
  assert(parse(wire("id", A, "battery_low", "120"), cmd, error) && cmd.ttl_ms == 120000);
  for (const char* mac : {"AA:bb:cc:dd:ee:01", "aa-bb-cc-dd-ee-01", "aa:bb:cc:dd:ee:01x",
                          "aa:bb:cc:dd:ee:01\\u0000x"}) assert(!parse(wire("id", mac), cmd, error));
  for (const char* bad : {"null", "[]", "true", "{", "{}",
      "{\"action\":1,\"mac\":\"aa:bb:cc:dd:ee:01\"}",
      "{\"action\":\"vibrate\",\"mac\":123}",
      "{\"action\":\"vibrate\",\"mac\":\"aa:bb:cc:dd:ee:01\",\"request_id\":false}",
      "{\"action\":\"vibrate\",\"mac\":\"aa:bb:cc:dd:ee:01\",\"request_id\":null}",
      "{\"action\":\"vibrate\",\"mac\":\"aa:bb:cc:dd:ee:01\",\"request_id\":\"id\",\"reason\":false,\"ttl_s\":60}",
      "{\"action\":\"vibrate\",\"mac\":\"aa:bb:cc:dd:ee:01\",\"request_id\":\"id\",\"ttl_s\":60}",
      "{\"action\":\"vibrate\",\"mac\":\"aa:bb:cc:dd:ee:01\",\"request_id\":\"id\",\"reason\":\"battery_low\"}",
      "{\"action\":\"vibrate\",\"mac\":\"aa:bb:cc:dd:ee:01\",\"reason\":\"battery_low\"}",
      "{\"action\":\"vibrate\\u0000evil\",\"mac\":\"aa:bb:cc:dd:ee:01\"}"})
    assert(!parse(bad, cmd, error));
  assert(!parse(wire() + "{}", cmd, error));
  assert(!parse(wire() + "junk", cmd, error));
  assert(parse(wire() + " \n\t", cmd, error));
  assert(parse("{\"action\":\"vibrate\",\"mac\":\"aa:bb:cc:dd:ee:01\"}", cmd, error));
  assert(!cmd.tracked() && !cmd.reason[0] && cmd.ttl_ms == 120000);
}

static void command_lifetime() {
  roztash::VibrationCommands commands;
  roztash::VibrationCommand cmd, taken;
  const char* error = nullptr;
  assert(parse(wire(), cmd, error));
  assert(commands.offer(cmd, 100) == roztash::CommandOffer::Accepted);
  assert(commands.offer(cmd, 5000) == roztash::CommandOffer::Duplicate);
  assert(commands.take(60100, taken) == roztash::CommandTake::Expired);
  assert(commands.offer(cmd, 70000) == roztash::CommandOffer::Accepted);
  assert(commands.take(70001, taken) == roztash::CommandTake::Ready);
  assert(commands.offer(cmd, 70002) == roztash::CommandOffer::Duplicate);
  auto other = cmd;
  std::strcpy(other.mac, B);
  assert(commands.offer(other, 70002) == roztash::CommandOffer::Conflict);
  commands.finish(true, 70003);
  assert(commands.offer(cmd, 70004) == roztash::CommandOffer::Completed);
  assert(commands.offer(other, 70004) == roztash::CommandOffer::Conflict);
  assert(!commands.active());
  assert(parse(wire("battery-second"), cmd, error));
  assert(commands.offer(cmd, 80000) == roztash::CommandOffer::Accepted);
  assert(commands.take(80001, taken) == roztash::CommandTake::Ready);
  commands.finish(false, 80002);
  assert(commands.offer(cmd, 80003) == roztash::CommandOffer::Accepted);
  assert(commands.cancelPending(taken));
  assert(!commands.cancelPending(taken));
  assert(commands.take(80004, taken) == roztash::CommandTake::None);
  assert(commands.offer(cmd, UINT32_MAX - 999) == roztash::CommandOffer::Accepted);
  assert(commands.take(59000, taken) == roztash::CommandTake::Expired);
}

int main() {
  parser_boundaries();
  command_lifetime();
  std::puts("vibration_command_host_test: parser, TTL, dedupe, identity binding, retry and revoke PASS");
}
