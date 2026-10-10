// Host-side golden test for the C++ port of the Fundo frame codec.
//
// Every hex string below is a REAL frame captured from a live PDMB1062
// session (2026-10-10) — see docs/band-protocol.md. The build-side cases are
// frames actually transmitted to the band during that session.
//
// Build & run (single line):
//   c++ -std=c++17 -O2 -Wall -Wextra protocol_host_test.cpp ../gateway/protocol.cpp -I../gateway -o host_test && ./host_test
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <string>
#include <vector>

#include "protocol.h"

static std::vector<uint8_t> fromHex(const std::string& s) {
  std::vector<uint8_t> v;
  for (size_t i = 0; i + 1 < s.size(); i += 2)
    v.push_back((uint8_t)strtol(s.substr(i, 2).c_str(), nullptr, 16));
  return v;
}

static std::string toHex(const uint8_t* d, size_t n) {
  std::string s;
  char b[4];
  for (size_t i = 0; i < n; ++i) {
    snprintf(b, sizeof b, "%02X", d[i]);
    s += b;
  }
  return s;
}

static int failures = 0;

static void expect(bool cond, const std::string& what) {
  printf("%s  %s\n", cond ? "PASS" : "FAIL", what.c_str());
  if (!cond) failures++;
}

int main() {
  // ---- parse-side golden frames (captured from the band) ------------------
  struct RxCase {
    const char* hex;
    uint8_t c1;
    uint8_t c2;
    uint8_t dlen;
  };
  const RxCase rx[] = {
      // measurement accepted (response to (02,70,[01,01]))
      {"BA31000692810000020071000101", 0x02, 0x71, 1},
      // realtime HR sample: bpm 0x59 = 89
      {"BA21000D5A6C03000A00AB000859001A0A0A140931", 0x0A, 0xAB, 8},
      // measurement ended, type 1 (HR)
      {"BA310006095D0100020072000101", 0x02, 0x72, 1},
      // ack of the (A6,05) command
      {"BA31000666500001A60006000101", 0xA6, 0x06, 1},
      // echo of the (A7,1F) command
      {"BA31000533EE0002A7001F0000", 0xA7, 0x1F, 0},
      // battery push: 0x47 = 71%
      {"BA310007710A470004004100024700", 0x04, 0x41, 2},
  };
  for (const auto& c : rx) {
    auto raw = fromHex(c.hex);
    fundo::Parsed p;
    const bool ok = fundo::parseFrame(raw.data(), raw.size(), p);
    char msg[192];
    snprintf(msg, sizeof msg,
             "parse %s -> (%02X,%02X) len=%u crc_ok=%d", c.hex, c.c1, c.c2,
             (unsigned)c.dlen, (int)(ok && p.crc_ok));
    expect(ok && p.valid && p.crc_ok && p.cmd1 == c.c1 && p.cmd2 == c.c2 &&
               p.data_len == c.dlen,
           msg);
  }

  // ---- build-side golden frames (transmitted during the live session) -----
  uint8_t buf[32];
  size_t n;

  const uint8_t hrStart[2] = {0x01, 0x01};
  n = fundo::buildFrame(0, 0x02, 0x70, hrStart, 2, buf);
  expect(toHex(buf, n) == "BA210007C1DB000002007000020101",
         "build (02,70,[01,01]) counter=0");

  n = fundo::buildFrame(1, 0xA6, 0x05, nullptr, 0, buf);
  expect(toHex(buf, n) == "BA2100051D1D0001A600050000",
         "build (A6,05) counter=1");

  n = fundo::buildFrame(2, 0xA7, 0x1F, nullptr, 0, buf);
  expect(toHex(buf, n) == "BA21000533EE0002A7001F0000",
         "build (A7,1F) counter=2");

  // ---- round-trip: parse our own built frame ------------------------------
  n = fundo::buildFrame(0x123, 0x02, 0x70, hrStart, 2, buf);
  fundo::Parsed p;
  const bool rt = fundo::parseFrame(buf, n, p);
  expect(rt && p.crc_ok && p.cmd1 == 0x02 && p.cmd2 == 0x70 && p.data_len == 2 &&
             p.data[0] == 0x01 && p.data[1] == 0x01,
         "round-trip build->parse with counter 0x123");

  printf(failures ? "\n%d FAILURE(S)\n" : "\nALL TESTS PASSED\n", failures);
  return failures ? 1 : 0;
}
