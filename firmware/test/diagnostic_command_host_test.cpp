// Pure production diagnostic command parsing/state; no hardware or network.
#include "diagnostic_command.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>

static constexpr const char* MAC = "aa:bb:cc:dd:ee:01";
static constexpr const char* ID = "diag-0123456789abcdef0123456789abcdef";

static std::string scan_wire(const std::string& id = ID, const std::string& ttl = "20") {
  return "{\"action\":\"diagnostic_scan\",\"request_id\":\"" + id +
      "\",\"ttl_s\":" + ttl + "}";
}

static std::string probe_wire(const std::string& id = ID,
                              const std::string& mac = MAC,
                              const std::string& ttl = "20") {
  return "{\"action\":\"diagnostic_probe\",\"request_id\":\"" + id +
      "\",\"ttl_s\":" + ttl + ",\"mac\":\"" + mac + "\"}";
}

static bool parse(const std::string& text, roztash::DiagnosticCommand& command,
                  const char*& error) {
  return roztash::parseDiagnosticCommand(text.data(), text.size(), command, error);
}

static void parser_accepts_only_the_diagnostic_contract() {
  roztash::DiagnosticCommand command;
  const char* error = nullptr;
  assert(parse(scan_wire(), command, error) && !error);
  assert(command.action == roztash::DiagnosticAction::Scan);
  assert(std::strcmp(command.request_id, ID) == 0);
  assert(command.ttl_ms == 20000 && !command.mac[0]);
  assert(parse(probe_wire(), command, error) && !error);
  assert(command.action == roztash::DiagnosticAction::Probe);
  assert(std::strcmp(command.mac, MAC) == 0);
  assert(parse(scan_wire(ID, "1"), command, error) && command.ttl_ms == 1000);
  assert(parse(scan_wire(ID, "60"), command, error) && command.ttl_ms == 60000);
  assert(parse(scan_wire() + " \n\t", command, error));

  for (const std::string& bad : {
      std::string(), std::string("null"), std::string("[]"), std::string("{"),
      scan_wire() + "{}", scan_wire() + "junk",
      std::string("{\"action\":\"diagnostic_scan\",\"request_id\":\"") + ID + "\",\"ttl_s\":20,\"mac\":\"" + MAC + "\"}",
      std::string("{\"action\":\"diagnostic_probe\",\"request_id\":\"") + ID + "\",\"ttl_s\":20}",
      std::string("{\"action\":\"diagnostic_scan\",\"request_id\":\"") + ID + "\",\"ttl_s\":20,\"extra\":true}",
      std::string("{\"action\":\"measure\",\"request_id\":\"") + ID + "\",\"ttl_s\":20}",
      std::string("{\"action\":\"diagnostic_scan\",\"request_id\":\"") + ID + "\",\"ttl_s\":0}",
      std::string("{\"action\":\"diagnostic_scan\",\"request_id\":\"") + ID + "\",\"ttl_s\":61}",
      std::string("{\"action\":\"diagnostic_scan\",\"request_id\":\"") + ID + "\",\"ttl_s\":1.5}",
      std::string("{\"action\":\"diagnostic_scan\",\"request_id\":\"") + ID + "\",\"ttl_s\":true}",
      probe_wire(ID, "AA:BB:CC:DD:EE:01"), probe_wire(ID, "aa-bb-cc-dd-ee-01"),
      scan_wire("diag-0123456789abcdef0123456789abcde"),
      scan_wire("diag-0123456789abcdef0123456789abcdef0"),
      scan_wire("diag-0123456789ABCDEF0123456789abcdef"),
      scan_wire("measure-0123456789abcdef0123456789abcdef")}) {
    command = roztash::DiagnosticCommand{};
    assert(!parse(bad, command, error));
    assert(error != nullptr);
  }

  assert(roztash::isDiagnosticAction(scan_wire().data(), scan_wire().size()));
  assert(roztash::isDiagnosticAction(probe_wire().data(), probe_wire().size()));
  const std::string measure = "{\"action\":\"measure\"}";
  assert(!roztash::isDiagnosticAction(measure.data(), measure.size()));
}

static void queue_rejects_duplicates_conflicts_busy_and_expired_work() {
  roztash::DiagnosticCommand command, taken;
  const char* error = nullptr;
  assert(parse(scan_wire(), command, error));
  roztash::DiagnosticRequests requests;
  assert(requests.offer(command, 100) == roztash::DiagnosticOffer::Accepted);
  assert(requests.pending());
  assert(requests.offer(command, 101) == roztash::DiagnosticOffer::Duplicate);

  auto conflict = command;
  conflict.action = roztash::DiagnosticAction::Probe;
  std::strcpy(conflict.mac, MAC);
  assert(requests.offer(conflict, 102) == roztash::DiagnosticOffer::Conflict);
  auto other = command;
  std::strcpy(other.request_id, "diag-1123456789abcdef0123456789abcdef");
  assert(requests.offer(other, 103) == roztash::DiagnosticOffer::Busy);

  assert(requests.take(102, taken) == roztash::DiagnosticTake::Ready);
  assert(requests.active() && !requests.pending());
  assert(requests.activeCommand() &&
         std::strcmp(requests.activeCommand()->request_id, ID) == 0);
  assert(requests.offer(command, 103) == roztash::DiagnosticOffer::Duplicate);
  assert(requests.offer(conflict, 103) == roztash::DiagnosticOffer::Conflict);
  requests.finish(104);
  assert(!requests.active());
  assert(requests.offer(command, 105) == roztash::DiagnosticOffer::Duplicate);
  assert(requests.offer(conflict, 105) == roztash::DiagnosticOffer::Conflict);
  assert(requests.offer(command, 60104) == roztash::DiagnosticOffer::Accepted);
  assert(requests.cancelPending(taken));
  assert(!requests.cancelPending(taken));

  assert(requests.offer(command, 70000) == roztash::DiagnosticOffer::Accepted);
  assert(requests.take(90000, taken) == roztash::DiagnosticTake::Expired);
  assert(!requests.pending() && !requests.active());

  command.ttl_ms = 1000;
  assert(requests.offer(command, UINT32_MAX - 500) == roztash::DiagnosticOffer::Accepted);
  assert(requests.take(501, taken) == roztash::DiagnosticTake::Expired);
}

int main() {
  parser_accepts_only_the_diagnostic_contract();
  queue_rejects_duplicates_conflicts_busy_and_expired_work();
  std::puts("diagnostic_command_host_test: strict parser, dedupe, conflict, busy and TTL PASS");
}
