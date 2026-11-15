#include "../gateway/network_config.h"

#include <cassert>
#include <cstdint>

int main() {
  using roztash::broadcastOctet;

  // The planned HSE network is 192.168.50.0/24.
  assert(broadcastOctet(192, 255) == 192);
  assert(broadcastOctet(168, 255) == 168);
  assert(broadcastOctet(50, 255) == 50);
  assert(broadcastOctet(10, 0) == 255);

  // Also verify a non-/24 mask so discovery does not assume one prefix size.
  assert(broadcastOctet(50, 255) == 50);
  assert(broadcastOctet(64, 128) == 127);
  assert(broadcastOctet(1, 0) == 255);

  static_assert(roztash::kW5500Sck == 12);
  static_assert(roztash::kW5500Miso == 13);
  static_assert(roztash::kW5500Mosi == 11);
  static_assert(roztash::kW5500Cs == 10);
  static_assert(roztash::kW5500Rst == 9);
}
