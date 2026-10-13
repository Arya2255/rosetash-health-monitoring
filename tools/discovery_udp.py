#!/usr/bin/env python3
"""
Simple UDP-based Service Discovery for Roztash
Works on ANY network - factory LAN, home WiFi, bridged networks.
No mDNS, no complex setup required.
"""

import socket
import struct
import threading
import time
import json
import argparse
import sys
from typing import Callable, Optional

DISCOVERY_PORT = 19198
DISCOVERY_GROUP = "255.255.255.255"  # Broadcast to all devices
MAGIC = b"ROZTASH_DISCOVERY"

class DiscoveryServer:
    """Server that listens for gateway discovery requests."""
    
    def __init__(self, mqtt_host: Optional[str] = None, mqtt_port: int = 1883):
        self.mqtt_host = mqtt_host or self._get_local_ip()
        self.mqtt_port = mqtt_port
        self.sock: Optional[socket.socket] = None
        self.running = False
        self.gateways_seen = []
        
    def _get_local_ip(self) -> str:
        try:
            # Get actual network interface IP - prefer 192.168.x.x over 10.x.x.x
            import subprocess
            result = subprocess.run(
                ["ip", "-4", "addr", "show"],
                capture_output=True, text=True
            )
            best_ip = None
            for line in result.stdout.split('\n'):
                if 'inet ' in line and not line.strip().startswith('inet 127'):
                    ip = line.strip().split()[1].split('/')[0]
                    if ip.startswith('192.168.'):
                        return ip
                    if not best_ip:
                        best_ip = ip
            return best_ip or "127.0.0.1"
        except Exception:
            return "127.0.0.1"
    
    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", DISCOVERY_PORT))
        self.sock.settimeout(1.0)
        self.running = True
        
        print(f"[discovery] Server started on {self.mqtt_host}:{self.mqtt_port}")
        print("[discovery] Waiting for gateways...")
        
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
                self._handle_request(data, addr)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[discovery] Error: {e}")
        
        self.sock.close()
    
    def _handle_request(self, data: bytes, addr):
        if not data.startswith(MAGIC):
            return
        
        msg = data[len(MAGIC):]
        if msg == b"WHERE_ARE_YOU":
            # Gateway is asking for us
            response = json.dumps({
                "mqtt_host": self.mqtt_host,
                "mqtt_port": self.mqtt_port,
                "server": "roztash-bridge"
            }).encode()
            self.sock.sendto(MAGIC + b"HERE_I_AM" + response, addr)
            print(f"[discovery] Responded to {addr[0]}")
            
        elif msg.startswith(b"HERE_I_AM"):
            # Another server responded
            try:
                info = json.loads(msg[9:].decode())
                print(f"[discovery] Found server: {info}")
                self.gateways_seen.append((addr[0], info))
            except:
                pass
    
    def stop(self):
        self.running = False


class DiscoveryClient:
    """Client that discovers the server via broadcast."""
    
    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        
    def discover(self) -> tuple[str, int] | None:
        """Broadcast discovery request and wait for response."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.settimeout(self.timeout)
        
        # Send discovery request
        request = MAGIC + b"WHERE_ARE_YOU"
        
        # Try all common broadcast addresses
        broadcast_addrs = [
            "255.255.255.255",
            "192.168.255.255",
            "10.255.255.255",
            "172.31.255.255",
        ]
        
        for bc_addr in broadcast_addrs:
            try:
                self.sock.sendto(request, (bc_addr, DISCOVERY_PORT))
            except:
                pass
        
        # Get local IP to exclude our own responses
        local_ip = self._get_local_ip()
        print(f"[discovery] Searching for server (local: {local_ip})...")
        
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                data, addr = self.sock.recvfrom(1024)
                if addr[0] == local_ip:
                    continue  # Skip our own broadcast echo
                if data.startswith(MAGIC + b"HERE_I_AM"):
                    info = json.loads(data[len(MAGIC)+9:].decode())
                    # Use the actual responder's IP, not what's in the JSON
                    print(f"[discovery] Found server at {addr[0]}:{info.get('mqtt_port', 1883)}")
                    self.sock.close()
                    # Return the actual responder IP, not the value from JSON
                    return addr[0], info.get('mqtt_port', 1883)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[discovery] Error: {e}")
                break
        
        self.sock.close()
        return None
    
    def _get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"


def run_server(mqtt_host: Optional[str] = None, mqtt_port: int = 1883):
    """Run as discovery server (on the Windows PC)."""
    server = DiscoveryServer(mqtt_host, mqtt_port)
    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[discovery] Stopping...")
        server.stop()


def run_client() -> Optional[tuple[str, int]]:
    """Run as discovery client (on the ESP32 gateway)."""
    client = DiscoveryClient()
    return client.discover()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Roztash Service Discovery")
    parser.add_argument("--server", action="store_true", help="Run as server")
    parser.add_argument("--client", action="store_true", help="Run as client (for gateway)")
    parser.add_argument("--mqtt-host", default=None, help="MQTT host IP for server")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT port")
    
    args = parser.parse_args()
    
    if args.server:
        run_server(args.mqtt_host, args.mqtt_port)
    elif args.client:
        result = run_client()
        if result:
            print(f"RESULT: {result[0]}:{result[1]}")
            exit(0)
        else:
            print("RESULT: NOT_FOUND", file=sys.stderr)
            exit(1)
    else:
        parser.print_help()