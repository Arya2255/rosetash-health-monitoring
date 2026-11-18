#pragma once
#include <cstdint>
namespace roztash {
// The band encodes BPM in one byte; require a physiologically usable reading.
inline bool isValidHrSample(uint8_t bpm) { return bpm >= 30 && bpm <= 240; }
}  // namespace roztash
