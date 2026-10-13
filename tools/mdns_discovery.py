#!/usr/bin/env python3
"""
mDNS Service Advertisement for Roztash Bridge
Announces 'roztash-bridge' on the local network so gateway ESP32 devices can
auto-discover the MQTT broker without knowing its IP address.
"""

import asyncio
import socket
from zeroconf import Zeroconf, ServiceInfo, ServiceListener

SERVICE_TYPE = "_roztash-mqtt._tcp.local."
SERVICE_NAME = "roztash-bridge"
SERVICE_PORT = 1883  # MQTT port

def get_local_ip() -> str:
    """Get the local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

async def advertise():
    """Advertise the Roztash MQTT service via mDNS."""
    local_ip = get_local_ip()
    print(f"[mdns] Local IP: {local_ip}")
    
    desc = {
        "mqtt_port": str(SERVICE_PORT),
        "version": "1.0",
        "platform": "roztash-bridge"
    }
    
    service_info = ServiceInfo(
        SERVICE_TYPE,
        f"{SERVICE_NAME}.{SERVICE_TYPE}",
        addresses=[socket.inet_aton(local_ip)],
        port=SERVICE_PORT,
        properties=desc,
        server=f"{SERVICE_NAME}.local."
    )
    
    zc = Zeroconf()
    await zc.register_service(service_info)
    print(f"[mdns] Advertising: {SERVICE_NAME}{SERVICE_TYPE}")
    print(f"[mdns] At: {local_ip}:{SERVICE_PORT}")
    print("[mdns] Press Ctrl+C to stop...")
    
    try:
        while True:
            await asyncio.sleep(60)
            # Re-announce to keep the service alive
            await zc.register_service(service_info)
            print("[mdns] Keepalive sent")
    except KeyboardInterrupt:
        pass
    finally:
        await zc.unregister_all_services()
        await zc.close()
        print("[mdns] Stopped")

async def resolve(hostname: str, timeout: int = 5) -> str | None:
    """
    Resolve a hostname to IP address using mDNS.
    Returns IP string or None if not found.
    """
    zc = Zeroconf()
    try:
        info = await asyncio.wait_for(
            zc.get_service_info(f"{hostname}.{SERVICE_TYPE}", timeout),
            timeout=timeout
        )
        if info and info.addresses:
            return socket.inet_ntoa(info.addresses[0])
    except asyncio.TimeoutError:
        print(f"[mdns] Timeout resolving {hostname}")
    except Exception as e:
        print(f"[mdns] Error resolving {hostname}: {e}")
    finally:
        await zc.close()
    return None

# CLI for resolving from ESP32 side
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        # Resolve mode: python mdns_discovery.py <hostname>
        print(f"[mdns] Resolving {sys.argv[1]}...")
        ip = asyncio.run(resolve(sys.argv[1]))
        if ip:
            print(ip)  # Output just the IP for shell capture
        else:
            print("NOT_FOUND", file=sys.stderr)
            sys.exit(1)
    else:
        # Advertise mode
        print("[mdns] Starting service advertisement...")
        asyncio.run(advertise())