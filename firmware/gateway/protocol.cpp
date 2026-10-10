#include "protocol.h"

#include <stdio.h>
#include <string.h>

namespace fundo {

uint16_t crc16(const uint8_t* data, size_t len) {
  uint16_t i = 0xFFFF;
  for (size_t n = 0; n < len; ++n) {
    uint16_t x = (uint16_t)((((i << 8) & 0xFFFF) | ((i >> 8) & 0x00FF)) ^ data[n]);
    x ^= (uint16_t)((x & 0x00FF) >> 4);
    x ^= (uint16_t)((x << 12) & 0xFFFF);
    i = (uint16_t)(x ^ ((x & 0x00FF) << 5));
  }
  return (uint16_t)(i & 0xFFFF);
}

size_t buildFrame(uint16_t counter, uint8_t cmd1, uint8_t cmd2,
                  const uint8_t* payload, size_t payload_len, uint8_t* out) {
  if (!out || payload_len > 0xFFFA) return 0;

  const size_t inner_len = 5 + payload_len;
  uint8_t* inner = out + 8;

  inner[0] = cmd1;
  inner[1] = 0x00;
  inner[2] = cmd2;
  inner[3] = (uint8_t)((payload_len >> 8) & 0xFF);
  inner[4] = (uint8_t)(payload_len & 0xFF);
  if (payload_len && payload) memcpy(inner + 5, payload, payload_len);

  const uint16_t crc = crc16(inner, inner_len);

  out[0] = 0xBA;
  out[1] = 0x21;  // app -> band
  out[2] = (uint8_t)((inner_len >> 8) & 0xFF);
  out[3] = (uint8_t)(inner_len & 0xFF);
  out[4] = (uint8_t)((crc >> 8) & 0xFF);
  out[5] = (uint8_t)(crc & 0xFF);

  // Sequence counter encoding mirrors the app SDK: counter rendered as a hex
  // string, padded to an even nibble count; 1 byte -> (00, b); 2 bytes -> swapped.
  char h[8];
  int hl = snprintf(h, sizeof h, "%x", (unsigned)counter);
  if (hl % 2) {
    memmove(h + 1, h, (size_t)hl + 1);
    h[0] = '0';
    hl++;
  }
  uint8_t sb[4];
  const int sn = hl / 2;
  for (int k = 0; k < sn; ++k) {
    auto hv = [](char c) -> uint8_t {
      return (uint8_t)((c <= '9') ? (c - '0') : ((c | 0x20) - 'a' + 10));
    };
    sb[k] = (uint8_t)((hv(h[2 * k]) << 4) | hv(h[2 * k + 1]));
  }
  if (sn <= 1) {
    out[6] = 0x00;
    out[7] = sn ? sb[0] : 0x00;
  } else {
    out[6] = sb[1];
    out[7] = sb[0];
  }
  return 8 + inner_len;
}

bool parseFrame(const uint8_t* raw, size_t len, Parsed& out) {
  out = Parsed{};
  if (!raw || len < 13 || raw[0] != 0xBA) return false;

  const size_t inner_len = (size_t)((raw[2] << 8) | raw[3]);
  if (inner_len < 5 || len < 8 + inner_len) return false;

  const uint8_t* inner = raw + 8;
  const uint16_t crc = (uint16_t)((raw[4] << 8) | raw[5]);
  out.crc_ok = (crc16(inner, inner_len) == crc);

  out.cmd1 = inner[0];
  out.cmd2 = inner[2];
  const uint16_t dlen = (uint16_t)((inner[3] << 8) | inner[4]);
  if ((size_t)5 + dlen > inner_len) return false;

  out.data = inner + 5;
  out.data_len = (uint8_t)(dlen > 255 ? 255 : dlen);
  out.valid = true;
  return true;
}

}  // namespace fundo
