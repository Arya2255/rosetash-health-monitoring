#pragma once

#include <stdint.h>

namespace roztash {

// ESP32-S3 N16R8 + W5500 pins validated on the bench.
inline constexpr int kW5500Sck = 12;
inline constexpr int kW5500Miso = 13;
inline constexpr int kW5500Mosi = 11;
inline constexpr int kW5500Cs = 10;
inline constexpr int kW5500Rst = 9;
inline constexpr int kW5500Irq = -1;  // W5500 INT is not wired.
inline constexpr uint8_t kW5500SpiMhz = 8;

// Dedicated HSE LAN fallback. DHCP still assigns each gateway its own address.
inline constexpr uint8_t kHseIp[4] = {192, 168, 50, 10};
inline constexpr uint16_t kMqttPort = 1884;
inline constexpr uint16_t kDiscoveryPort = 19198;

// Compute one IPv4 broadcast octet from an address and subnet-mask octet.
constexpr uint8_t broadcastOctet(uint8_t address, uint8_t mask) {
  return static_cast<uint8_t>((address & mask) | static_cast<uint8_t>(~mask));
}

}  // namespace roztash
