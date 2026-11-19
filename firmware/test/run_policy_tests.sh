#!/usr/bin/env bash
# Host-only policy/schedule tests. Never opens hardware or network interfaces.
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${TMPDIR:?Set TMPDIR to a scratch directory for host executables}"
json_include="${ARDUINOJSON_INCLUDE:-$HOME/Arduino/libraries/ArduinoJson/src}"
compiler="${CXX:-c++}"
"$compiler" -std=c++17 -O2 -Wall -Wextra -Werror \
  -Ifirmware/gateway -I"$json_include" firmware/test/policy_schedule_host_test.cpp \
  -o "$TMPDIR/policy-schedule-host-test"
"$TMPDIR/policy-schedule-host-test"
"$compiler" -std=c++17 -O2 -Wall -Wextra -Werror \
  -Ifirmware/test/policy_stubs -Ifirmware/gateway \
  firmware/test/ble_policy_host_test.cpp firmware/gateway/ble_central.cpp \
  firmware/gateway/protocol.cpp -o "$TMPDIR/ble-policy-host-test"
"$TMPDIR/ble-policy-host-test"
"$compiler" -std=c++17 -O2 -Wall -Wextra -Werror \
  -Ifirmware/test/policy_stubs -Ifirmware/gateway \
  firmware/test/diagnostic_ble_host_test.cpp firmware/gateway/ble_central.cpp \
  firmware/gateway/protocol.cpp -o "$TMPDIR/diagnostic-ble-host-test"
"$TMPDIR/diagnostic-ble-host-test"
"$compiler" -std=c++17 -O2 -Wall -Wextra -Werror \
  -Ifirmware/gateway -I"$json_include" firmware/test/diagnostic_command_host_test.cpp \
  -o "$TMPDIR/diagnostic-command-host-test"
"$TMPDIR/diagnostic-command-host-test"
"$compiler" -std=c++17 -O2 -Wall -Wextra -Werror \
  -Ifirmware/gateway -I"$json_include" firmware/test/vibration_command_host_test.cpp \
  -o "$TMPDIR/vibration-command-host-test"
"$TMPDIR/vibration-command-host-test"
"$compiler" -std=c++17 -O2 -Wall -Wextra -Werror \
  -Ifirmware/gateway -I"$json_include" firmware/test/manual_measure_host_test.cpp \
  -o "$TMPDIR/manual-measure-host-test"
"$TMPDIR/manual-measure-host-test"
"$compiler" -std=c++17 -O2 -Wall -Wextra -Werror \
  -Ifirmware/gateway firmware/test/broker_discovery_retry_host_test.cpp \
  -o "$TMPDIR/broker-discovery-retry-host-test"
"$TMPDIR/broker-discovery-retry-host-test"
"$compiler" -std=c++17 -O2 -Wall -Wextra -Werror \
  -Ifirmware/gateway firmware/test/gateway_discovery_protocol_host_test.cpp \
  -o "$TMPDIR/gateway-discovery-protocol-host-test"
"$TMPDIR/gateway-discovery-protocol-host-test"
