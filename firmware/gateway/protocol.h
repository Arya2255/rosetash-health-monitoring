// Fundo/KCT band protocol — frame building & parsing.
// Reverse-engineered from the Porodo Fit app and verified live against a
// PDMB1062 band. Host-testable: no Arduino dependencies in this unit.
//
// References:
//   docs/band-protocol.md          (repo)
//   tools/band/fundo_send.py       (python reference implementation)
//   vault: پروتکل-BLE-مچبند
#pragma once

#include <stddef.h>
#include <stdint.h>

namespace fundo {

// ---- command pairs (cmd1, cmd2) -------------------------------------------
constexpr uint8_t CMD_MEASURE       = 0x02;  // measurement control
constexpr uint8_t SUB_MEASURE_START = 0x70;  // request start, payload [1, type]
constexpr uint8_t SUB_MEASURE_ACK   = 0x71;  // reply: data[0] 1 = accepted, 0 = wearing error
constexpr uint8_t SUB_MEASURE_END   = 0x72;  // reply: data[0] = measure type
constexpr uint8_t MEASURE_TYPE_HR   = 1;

constexpr uint8_t CMD_REALTIME      = 0x0A;  // realtime sample stream during measurement
constexpr uint8_t SUB_REALTIME_HR   = 0xAB;  // data[0] = bpm

constexpr uint8_t CMD_BATTERY       = 0x04;
constexpr uint8_t SUB_BATTERY       = 0x41;  // data = [percent, state]

// ---- crc ------------------------------------------------------------------
// CRC16 as used by the app SDK (init 0xFFFF) — validated against live frames.
uint16_t crc16(const uint8_t* data, size_t len);

// ---- frame build ----------------------------------------------------------
// Builds an outer frame:
//   BA | 21 | inner_len(2, BE) | crc16(2, BE) | counter(2) | inner
//   inner = [cmd1, 0x00, cmd2, payload_len(2, BE), payload...]
// `out` must hold at least 8 + 5 + payload_len bytes.
// Returns total frame length, or 0 on bad arguments.
size_t buildFrame(uint16_t counter, uint8_t cmd1, uint8_t cmd2,
                  const uint8_t* payload, size_t payload_len, uint8_t* out);

// ---- frame parse ----------------------------------------------------------
struct Parsed {
  uint8_t cmd1 = 0;
  uint8_t cmd2 = 0;
  const uint8_t* data = nullptr;  // points into the raw buffer
  uint8_t data_len = 0;
  bool crc_ok = false;
  bool valid = false;
};

// Parses a full outer frame (must start with 0xBA).
// Returns false when too short / bad magic / bad inner length.
bool parseFrame(const uint8_t* raw, size_t len, Parsed& out);

}  // namespace fundo
