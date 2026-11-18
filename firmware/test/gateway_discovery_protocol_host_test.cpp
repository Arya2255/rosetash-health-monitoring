#include "gateway_discovery_protocol.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
#include <sys/socket.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>

static constexpr const char* QUERY = "ROZTASH_GATEWAY_DISCOVERYWHO_IS_THERE";
static void reply(const char* request, size_t len, const roztash::GatewayDiscoveryInfo& info,
                  std::string& output) {
  char buffer[384]{};
  size_t written = 0;
  assert(roztash::buildGatewayDiscoveryReply(request, len, info, buffer, sizeof buffer, written));
  output.assign(buffer, written);
}

static void loopback_udp_exchange_uses_production_reply_builder() {
  const int server = socket(AF_INET, SOCK_DGRAM, 0);
  const int client = socket(AF_INET, SOCK_DGRAM, 0);
  assert(server >= 0 && client >= 0);
  timeval timeout{1, 0};
  assert(setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0);
  sockaddr_in server_addr{};
  server_addr.sin_family = AF_INET;
  server_addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  server_addr.sin_port = 0;
  assert(bind(server, reinterpret_cast<sockaddr*>(&server_addr), sizeof(server_addr)) == 0);
  socklen_t addr_len = sizeof(server_addr);
  assert(getsockname(server, reinterpret_cast<sockaddr*>(&server_addr), &addr_len) == 0);

  const char query[] = "ROZTASH_GATEWAY_DISCOVERYWHO_IS_THERE";
  assert(sendto(client, query, sizeof(query) - 1, 0,
                reinterpret_cast<sockaddr*>(&server_addr), sizeof(server_addr)) ==
         static_cast<ssize_t>(sizeof(query) - 1));
  char received[128];
  sockaddr_in client_addr{};
  socklen_t client_len = sizeof(client_addr);
  const auto got = recvfrom(server, received, sizeof(received), 0,
                            reinterpret_cast<sockaddr*>(&client_addr), &client_len);
  assert(got == static_cast<ssize_t>(sizeof(query) - 1));
  const roztash::GatewayDiscoveryInfo info{"gw-loopback", "aa:bb:cc:dd:ee:01",
                                           "0.5.3-operational", "127.0.0.1", false};
  char response[384]; size_t response_len = 0;
  assert(roztash::buildGatewayDiscoveryReply(received, static_cast<size_t>(got), info,
                                             response, sizeof(response), response_len));
  assert(sendto(server, response, response_len, 0,
                reinterpret_cast<sockaddr*>(&client_addr), client_len) ==
         static_cast<ssize_t>(response_len));
  char answer[384];
  const auto answer_len = recvfrom(client, answer, sizeof(answer), 0, nullptr, nullptr);
  const std::string payload(answer, answer_len > 0 ? static_cast<size_t>(answer_len) : 0);
  assert(payload.find("ROZTASH_GATEWAY_DISCOVERYGATEWAY_HERE") == 0);
  assert(payload.find("\"mqtt_connected\":false") != std::string::npos);
  close(client);
  close(server);
}

int main() {
  const roztash::GatewayDiscoveryInfo info{"gw-2", "aa:bb:cc:dd:ee:01", "0.5.3-operational",
                                          "192.168.50.22", true};
  std::string out;
  reply(QUERY, std::strlen(QUERY), info, out);
  const std::string prefix = "ROZTASH_GATEWAY_DISCOVERYGATEWAY_HERE";
  assert(out.compare(0, prefix.size(), prefix) == 0);
  const auto payload = out.substr(prefix.size());
  assert(payload.find("\"v\":1") != std::string::npos);
  assert(payload.find("\"gw\":\"gw-2\"") != std::string::npos);
  assert(payload.find("\"mac\":\"aa:bb:cc:dd:ee:01\"") != std::string::npos);
  assert(payload.find("\"fw\":\"0.5.3-operational\"") != std::string::npos);
  assert(payload.find("\"ip\":\"192.168.50.22\"") != std::string::npos);
  assert(payload.find("\"transport\":\"ethernet\"") != std::string::npos);
  assert(payload.find("\"mqtt_connected\":true") != std::string::npos);

  char buffer[384]; size_t written = 0;
  assert(!roztash::buildGatewayDiscoveryReply(QUERY, std::strlen(QUERY)-1, info, buffer, sizeof buffer, written));
  const char suffix[] = "junk";
  std::string malformed = std::string(QUERY) + suffix;
  assert(!roztash::buildGatewayDiscoveryReply(malformed.data(), malformed.size(), info, buffer, sizeof buffer, written));
  const roztash::GatewayDiscoveryInfo invalid{"", info.mac, info.fw, info.ip, false};
  assert(!roztash::buildGatewayDiscoveryReply(QUERY, std::strlen(QUERY), invalid, buffer, sizeof buffer, written));
  assert(!roztash::buildGatewayDiscoveryReply(QUERY, std::strlen(QUERY), info, buffer, 16, written));
  loopback_udp_exchange_uses_production_reply_builder();
  std::puts("gateway_discovery_protocol_host_test: strict query, response fields and bounds PASS");
}
