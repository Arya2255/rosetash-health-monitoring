#pragma once
#include <cstddef>
#include <cstdint>
namespace roztash {
// The band encodes BPM in one byte; require a physiologically usable reading.
inline bool isValidHrSample(uint8_t bpm) { return bpm >= 30 && bpm <= 240; }

template <size_t Capacity>
inline uint8_t filterHrSamples(const uint8_t* input, uint8_t count,
                               uint8_t (&output)[Capacity], uint32_t* sum) {
  uint8_t valid = 0;
  uint32_t total = 0;
  for (uint8_t i = 0; i < count; ++i) {
    if (!isValidHrSample(input[i])) continue;
    if (valid < Capacity) output[valid++] = input[i];
    total += input[i];
  }
  if (sum) *sum = total;
  return valid;
}
}  // namespace roztash
