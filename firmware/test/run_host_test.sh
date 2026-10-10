#!/usr/bin/env bash
# Build & run the host-side golden test for the frame codec.
set -euo pipefail
cd "$(dirname "$0")"
c++ -std=c++17 -O2 -Wall -Wextra protocol_host_test.cpp \
    ../gateway/protocol.cpp -I../gateway -o host_test
./host_test
