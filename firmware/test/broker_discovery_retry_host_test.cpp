#include "broker_discovery_retry.h"
#include <cassert>
#include <cstdio>
#include <cstring>

int main() {
  roztash::BrokerDiscoveryRetry retry;
  assert(retry.due(1000)); // First DHCP-ready discovery is immediate.
  retry.recordFailure(1000);
  assert(!retry.due(1999));
  assert(retry.due(2000));
  retry.recordFailure(2000);
  assert(!retry.due(2999));
  assert(retry.due(3000));

  retry.recordSuccess("192.168.50.7", 1884, 7000);
  assert(!retry.due(8000));
  assert(retry.due(67000)); // Revalidate even a working discovered broker.
  retry.recordFailure(67000);
  assert(retry.due(68000)); // A failed revalidation retries quickly.

  retry.recordSuccess("192.168.50.8", 1885, 68000);
  char host[48]{};
  uint16_t port = 0;
  retry.broker(host, sizeof host, port, "192.168.50.1", 1884);
  assert(std::strcmp(host, "192.168.50.8") == 0 && port == 1885);
  retry.networkLost();
  assert(retry.brokerResolved());
  retry.networkReady();
  assert(retry.due(70000));
  std::puts("broker_discovery_retry_host_test: startup retry, revalidation and reconnect PASS");
}
