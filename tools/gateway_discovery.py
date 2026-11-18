"""Discover Roztash Ethernet gateways without relying on MQTT."""

import ipaddress
import json
import math
import re
import select
import socket
import time
from itertools import islice

DISCOVERY_PORT = 19199
DISCOVERY_QUERY = b"ROZTASH_GATEWAY_DISCOVERYWHO_IS_THERE"
DISCOVERY_REPLY = b"ROZTASH_GATEWAY_DISCOVERYGATEWAY_HERE"
MAX_REPLY_SIZE = 512
_GW_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,22}")
_MAC = re.compile(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}")


def _broadcast_targets(candidates):
    targets = []
    for candidate in islice(candidates or (), 128):
        if not isinstance(candidate, dict):
            continue
        try:
            interface = ipaddress.IPv4Interface(f"{candidate['ip']}/{candidate['prefix']}")
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        ip = interface.ip
        network = interface.network
        if (ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_reserved
                or network.prefixlen >= 31
                or ip in (network.network_address, network.broadcast_address)):
            continue
        targets.append((str(network.broadcast_address), DISCOVERY_PORT,
                        str(ip), str(candidate.get("iface") or "")))
    targets.append(("255.255.255.255", DISCOVERY_PORT, None, ""))
    return list(dict.fromkeys(targets))


def _parse_reply(packet, peer_ip):
    if len(packet) > MAX_REPLY_SIZE or not packet.startswith(DISCOVERY_REPLY):
        return None
    try:
        doc = json.loads(packet[len(DISCOVERY_REPLY):].decode("utf-8"))
    except ValueError:
        return None
    if not isinstance(doc, dict) or type(doc.get("v")) is not int or doc["v"] != 1:
        return None
    gw, mac, fw, ip = (doc.get(field) for field in ("gw", "mac", "fw", "ip"))
    if (not isinstance(gw, str) or not _GW_ID.fullmatch(gw)
            or not isinstance(mac, str) or not _MAC.fullmatch(mac)
            or not isinstance(fw, str) or not 1 <= len(fw) <= 64
            or not fw.isascii() or not fw.isprintable()
            or not isinstance(ip, str)):
        return None
    try:
        ipaddress.IPv4Address(ip)
    except ipaddress.AddressValueError:
        return None
    if (doc.get("transport") != "ethernet"
            or type(doc.get("mqtt_connected")) is not bool):
        return None
    # AF_INET supplies the peer address. Never use an address from the payload.
    return {"v": 1, "gw": gw, "mac": mac.lower(), "fw": fw, "ip": peer_ip,
            "transport": "ethernet", "mqtt_connected": doc["mqtt_connected"]}


def discover_gateways(candidates=None, timeout_s=2.0, targets=None) -> list[dict]:
    """Send one query per IPv4 broadcast target, then collect valid UDP replies.

    ``candidates`` are local interface records with ``ip``, ``prefix`` and
    ``iface``. ``targets`` can override broadcasts with numeric IPv4/port pairs
    (e.g. for loopback tests). Observations are not authenticated, and a reply
    proves neither registry membership nor live MQTT telemetry.
    """
    try:
        timeout_s = float(timeout_s)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("timeout_s must be finite and nonnegative") from exc
    if not math.isfinite(timeout_s) or timeout_s < 0:
        raise ValueError("timeout_s must be finite and nonnegative")
    if targets is None:
        destinations = _broadcast_targets(candidates)
    else:
        destinations = []
        for target in islice(targets, 128):
            try:
                ip, port = target
                if type(port) is not int or not 1 <= port <= 65535:
                    continue
                destinations.append((str(ipaddress.IPv4Address(ip)), port, None, ""))
            except (TypeError, ValueError, ipaddress.AddressValueError):
                continue
        destinations = list(dict.fromkeys(destinations))
    if not destinations or timeout_s == 0:
        return []

    found = {}
    conflicted = set()
    mac_owners = {}
    deadline = time.monotonic() + timeout_s
    sockets = []
    last_error = None
    try:
        active_destinations = []
        for destination in destinations:
            _ip, _port, bind_ip, iface = destination
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                if iface and hasattr(socket, "SO_BINDTODEVICE"):
                    try:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                                        iface.encode() + b"\0")
                    except OSError:
                        pass
                sock.bind((bind_ip or "", 0))
                sock.setblocking(False)
            except OSError as exc:
                last_error = exc
                if sock is not None:
                    sock.close()
                continue
            sockets.append(sock)
            active_destinations.append(destination)
        sent = False
        for sock, (ip, port, _bind_ip, _iface) in zip(sockets, active_destinations):
            if time.monotonic() >= deadline:
                break
            try:
                sock.sendto(DISCOVERY_QUERY, (ip, port))
                sent = True
            except OSError as exc:
                last_error = exc
                continue
        if not sent and last_error is not None:
            raise last_error
        while sent and sockets:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            readable, _, _ = select.select(sockets, [], [], remaining)
            if not readable:
                break
            for sock in readable:
                try:
                    # Read a whole datagram so oversized packets are rejected,
                    # not truncated into an apparently valid reply.
                    packet, peer = sock.recvfrom(65_535)
                except BlockingIOError:
                    continue
                except OSError:
                    sockets.remove(sock)
                    sock.close()
                    continue
                reply = _parse_reply(packet, peer[0])
                if reply is not None and reply["gw"] not in conflicted:
                    owner = mac_owners.setdefault(reply["mac"], reply["gw"])
                    if owner != reply["gw"]:
                        conflicted.update((owner, reply["gw"]))
                        found.pop(owner, None)
                        found.pop(reply["gw"], None)
                        continue
                    # A gateway ID is the registry identity. Conflicting MACs
                    # invalidate that ID instead of trusting the first response.
                    previous = found.get(reply["gw"])
                    if previous is not None and previous["mac"] != reply["mac"]:
                        found.pop(reply["gw"])
                        conflicted.add(reply["gw"])
                    elif previous is None:
                        found[reply["gw"]] = reply
    finally:
        for sock in sockets:
            sock.close()
    return [found[key] for key in sorted(found)]