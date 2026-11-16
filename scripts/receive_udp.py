#!/usr/bin/env python3
# UDP Receiver for ESP32 Temperature Data
# Listens on port 9999 for broadcast messages

import socket
import json
import sys

UDP_PORT = 9999

print(f"=== UDP Receiver Started on port {UDP_PORT} ===")
print("Waiting for ESP32 data...\n")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('0.0.0.0', UDP_PORT))
sock.settimeout(10.0)

# Enable broadcast
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

try:
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            msg = data.decode('utf-8')
            
            print(f"From: {addr}")
            print(f"Raw: {msg}")
            
            # Try to parse JSON
            try:
                j = json.loads(msg)
                print(f"parsed JSON: {json.dumps(j, indent=2)}")
            except:
                print("(not valid JSON)")
                
            print("---")
            
        except socket.timeout:
            print("No data received in 10s, waiting...")
            continue
            
except KeyboardInterrupt:
    print("\nStopped.")
    sock.close()