// Observes MQTT frame boundaries without retaining payload bytes. PubSubClient
// silently drops oversized packets and hides RETAIN from its callback; this
// guard makes both cases visible to the application's fail-closed policy path.
#pragma once
#include <cstddef>
#include <cstdint>
namespace roztash {
class MqttPacketGuard {
 public:
  static constexpr uint32_t kBufferBytes = 16384;
  void reset() { *this = MqttPacketGuard{}; }
  void feed(uint8_t byte) {
    if (phase_ == 0) {
      publish_ = (byte & 0xf0) == 0x30;
      retained_ = publish_ && (byte & 1);
      remaining_ = 0; multiplier_ = 1; header_bytes_ = 1; phase_ = 1;
    } else if (phase_ == 1) {
      ++header_bytes_;
      remaining_ += uint32_t(byte & 127) * multiplier_;
      if (byte & 128) {
        if (header_bytes_ >= 5) { error_ = true; phase_ = 0; }
        else multiplier_ *= 128;
      } else {
        if (remaining_ + header_bytes_ > kBufferBytes) error_ = true;
        phase_ = remaining_ ? 2 : 0;
      }
    } else if (--remaining_ == 0) phase_ = 0;
  }
  bool retained() const { return retained_; }
  bool takeError() { bool e = error_; error_ = false; return e; }
 private:
  uint32_t remaining_ = 0, multiplier_ = 1, header_bytes_ = 0;
  uint8_t phase_ = 0;
  bool retained_ = false, publish_ = false, error_ = false;
};
}  // namespace roztash
