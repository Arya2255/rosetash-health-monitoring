"""Portable bridge checks: isolated imports, fake MQTT children, loopback UDP only."""
import io
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
import bridge
from tools import discovery_udp as discovery


class PortableBridgeTests(unittest.TestCase):
    def test_package_import_without_backend_on_search_path(self):
        code = ("import sys; sys.path.insert(0, " + repr(str(ROOT)) + "); "
                "import backend.bridge as bridge; "
                "assert bridge.battery_policy.__name__ == 'backend.battery_alerts'; "
                "assert bridge._db is None")
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


    def test_mqtt_executable_overrides_preserve_arguments_and_defaults(self):
        for override in (None, "", r"C:\Program Files\Mosquitto\mosquitto"):
            with self.subTest(override=override), patch.dict(os.environ, clear=False):
                for kind in ("pub", "sub"):
                    key = "ROZTASH_MOSQUITTO_" + kind.upper()
                    os.environ.pop(key, None)
                    if override is not None:
                        os.environ[key] = override + ("_" + kind + ".exe" if override else "")
                pub = os.environ.get("ROZTASH_MOSQUITTO_PUB") or "mosquitto_pub"
                sub = os.environ.get("ROZTASH_MOSQUITTO_SUB") or "mosquitto_sub"
                with patch.object(bridge.subprocess, "run", return_value=SimpleNamespace(
                        returncode=0, stderr="", stdout="")) as run:
                    self.assertEqual(bridge.publish("roztash/test/cmd", '{"v":1}', retained=True),
                                     (True, "sent"))
                self.assertEqual(run.call_args.args[0], [
                    pub, "-h", bridge.MQTT_HOST, "-p", str(bridge.MQTT_PORT),
                    "-r", "-t", "roztash/test/cmd", "-m", '{"v":1}'])
                child = SimpleNamespace(stdout=io.StringIO("roztash/test/status {}\n"), kill=Mock())
                with patch.object(bridge.subprocess, "Popen", return_value=child) as popen, \
                        patch.object(bridge.time, "sleep", side_effect=KeyboardInterrupt), \
                        patch.object(bridge, "ingest") as ingest, patch.object(bridge, "log"):
                    with self.assertRaises(KeyboardInterrupt):
                        bridge.subscriber_loop()
                self.assertEqual(popen.call_args.args[0], [
                    sub, "-h", bridge.MQTT_HOST, "-p", str(bridge.MQTT_PORT),
                    "-t", bridge.MQTT_TOPIC, "-F", "%t %p"])
                ingest.assert_called_once_with("roztash/test/status", "{}")
                child.kill.assert_called_once_with()

    def test_database_is_initialized_before_worker_threads(self):
        events = []
        worker = SimpleNamespace(start=lambda: events.append("thread"))
        with patch.object(bridge, "db", side_effect=lambda: events.append("db")), \
                patch.object(bridge.os, "makedirs"), patch.object(bridge, "DiscoveryServer"), \
                patch.object(bridge.threading, "Thread", return_value=worker), \
                patch.object(bridge, "Server"), patch.object(bridge, "log"):
            bridge.main()
        self.assertEqual(events, ["db", "thread", "thread", "thread"])

    def test_windows_children_have_no_console_and_posix_kwargs_stay_compatible(self):
        for platform in ("win32", "linux"):
            with self.subTest(platform=platform), patch.object(bridge.sys, "platform", platform), \
                    patch.object(bridge.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
                with patch.object(bridge.subprocess, "run", return_value=SimpleNamespace(
                        returncode=0, stderr="", stdout="")) as run:
                    self.assertEqual(bridge.publish("roztash/test/cmd", "{}"), (True, "sent"))
                expected = {"capture_output": True, "text": True, "timeout": 5}
                if platform == "win32":
                    expected["creationflags"] = 0x08000000
                self.assertEqual(run.call_args.kwargs, expected)
                with patch.object(bridge.subprocess, "run", return_value=SimpleNamespace(stdout=b"ok")) as run:
                    self.assertEqual(bridge._run_cmd(["test-command"]), "ok")
                expected.pop("text")
                expected["timeout"] = 8.0
                self.assertEqual(run.call_args.kwargs, expected)
                child = SimpleNamespace(stdout=iter(()), kill=Mock())
                with patch.object(bridge.subprocess, "Popen", return_value=child) as popen, \
                        patch.object(bridge.time, "sleep", side_effect=KeyboardInterrupt), \
                        patch.object(bridge, "log"):
                    with self.assertRaises(KeyboardInterrupt):
                        bridge.subscriber_loop()
                expected = {"stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL,
                            "text": True, "bufsize": 1}
                if platform == "win32":
                    expected["creationflags"] = 0x08000000
                self.assertEqual(popen.call_args.kwargs, expected)


class DiscoveryTests(unittest.TestCase):
    def test_local_broker_uses_route_to_each_requesting_peer(self):
        peers = [("192.0.2.20", 45000), ("198.51.100.20", 45001)]
        locals_ = ["192.0.2.10", "198.51.100.10"]
        for host in (None, "127.0.0.1", "127.2.3.4", "0.0.0.0", "localhost", "::1"):
            with self.subTest(host=host):
                server = discovery.DiscoveryServer(host, 1884)
                server.sock = Mock()
                for peer, local in zip(peers, locals_):
                    route = Mock()
                    route.__enter__ = Mock(return_value=route)
                    route.__exit__ = Mock(return_value=False)
                    route.getsockname.return_value = (local, 45002)
                    with patch.object(discovery.socket, "socket", return_value=route), \
                            patch.object(discovery.socket, "getaddrinfo", side_effect=AssertionError("unexpected fallback")):
                        server._handle_request(discovery.MAGIC + b"WHERE_ARE_YOU", peer)
                    route.connect.assert_called_once_with(peer)
                    route.send.assert_not_called()
                    route.sendto.assert_not_called()
                    packet, target = server.sock.sendto.call_args.args
                    self.assertEqual(target, peer)
                    prefix = discovery.MAGIC + b"HERE_I_AM"
                    self.assertTrue(packet.startswith(prefix))
                    self.assertEqual(json.loads(packet[len(prefix):]), {
                        "mqtt_host": local, "mqtt_port": 1884, "server": "roztash-bridge"})

    def test_configured_remote_broker_is_preserved(self):
        for host in ("broker.example.test", "203.0.113.10"):
            with self.subTest(host=host):
                server = discovery.DiscoveryServer(host, 1884)
                server.sock = Mock()
                with patch.object(discovery.socket, "socket", side_effect=AssertionError("no route probe for remote broker")):
                    server._handle_request(discovery.MAGIC + b"WHERE_ARE_YOU", ("192.0.2.20", 45000))
                packet = server.sock.sendto.call_args.args[0]
                self.assertEqual(json.loads(packet[len(discovery.MAGIC) + 9:])["mqtt_host"], host)

    def test_route_failure_uses_hostname_ipv4_then_safe_loopback_fallback(self):
        server = discovery.DiscoveryServer("localhost")
        addresses = [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", (ip, 0))
                     for ip in ("127.0.0.1", "0.0.0.0", "192.0.2.10")]
        with patch.object(discovery.socket, "socket", side_effect=OSError("no route")), \
                patch.object(discovery.socket, "gethostname", return_value="test-host"), \
                patch.object(discovery.socket, "getaddrinfo", return_value=addresses) as resolve:
            self.assertEqual(server._get_local_ip(("192.0.2.20", 45000)), "192.0.2.10")
            resolve.assert_called_once_with("test-host", None, socket.AF_INET, socket.SOCK_DGRAM)
        with patch.object(discovery.socket, "socket", side_effect=OSError("no route")), \
                patch.object(discovery.socket, "getaddrinfo", side_effect=socket.gaierror("offline")):
            self.assertEqual(server._get_local_ip(("192.0.2.20", 45000)), "127.0.0.1")

    def test_discovery_port_environment_override_and_default(self):
        for configured, expected in ((None, 19198), ("28765", 28765), ("0", 0)):
            with self.subTest(configured=configured), patch.dict(os.environ):
                os.environ.pop("ROZTASH_DISCOVERY_PORT", None)
                if configured is not None:
                    os.environ["ROZTASH_DISCOVERY_PORT"] = configured
                spec = importlib.util.spec_from_file_location("isolated_discovery", ROOT / "tools/discovery_udp.py")
                assert spec is not None and spec.loader is not None
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.assertEqual(module.DISCOVERY_PORT, expected)
                server = module.DiscoveryServer("localhost")
                listener = Mock()

                def stop_after_receive(_size):
                    server.stop()
                    return b"invalid request", ("127.0.0.1", 45000)

                listener.recvfrom.side_effect = stop_after_receive
                with patch.object(module.socket, "socket", return_value=listener):
                    server.start()
                listener.bind.assert_called_once_with(("", expected))
                listener.sendto.assert_not_called()
                listener.close.assert_called_once_with()

    def test_discovery_round_trip_over_loopback_and_silent_route_probe(self):
        server = discovery.DiscoveryServer("0.0.0.0", 1884)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as gateway, \
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
            gateway.bind(("127.0.0.1", 0))
            listener.bind(("127.0.0.1", 0))
            gateway.settimeout(0.05)
            listener.settimeout(1)
            peer = gateway.getsockname()
            self.assertEqual(server._get_local_ip(peer), "127.0.0.1")
            with self.assertRaises(socket.timeout):
                gateway.recvfrom(1024)  # The route lookup sent no probe packet.
            gateway.settimeout(1)
            server.sock = listener
            gateway.sendto(discovery.MAGIC + b"WHERE_ARE_YOU", listener.getsockname())
            request, source = listener.recvfrom(1024)
            with patch.object(subprocess, "run", side_effect=AssertionError("no OS commands for discovery")):
                server._handle_request(request, source)
            response, source = gateway.recvfrom(1024)
            prefix = discovery.MAGIC + b"HERE_I_AM"
            self.assertEqual(source, listener.getsockname())
            self.assertTrue(response.startswith(prefix))
            self.assertEqual(json.loads(response[len(prefix):]), {
                "mqtt_host": "127.0.0.1", "mqtt_port": 1884, "server": "roztash-bridge"})


if __name__ == "__main__":
    unittest.main()
