"""Authentication of local UI-to-bridge monitoring writes; isolated test key only."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import bridge_auth


class BridgeAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bridge-auth-test-")
        self.addCleanup(self.temp.cleanup)
        self.key = Path(self.temp.name) / "request.key"
        env = patch.dict(os.environ, {"ROZTASH_BRIDGE_AUTH_FILE": str(self.key)})
        env.start()
        self.addCleanup(env.stop)

    def test_valid_actor_body_path_and_time_are_bound(self):
        body = b'{"scan_paused":true}'
        headers = bridge_auth.sign_request("POST", "/api/monitoring", body,
                                           "viewer@example.test", now=1000)
        self.assertEqual(bridge_auth.verify_request("POST", "/api/monitoring", body,
                                                    headers, now=1000), "viewer@example.test")
        self.assertIsNone(bridge_auth.verify_request("POST", "/api/monitoring", b"{}", headers, now=1000))
        self.assertIsNone(bridge_auth.verify_request("POST", "/api/monitoring/settings", body, headers, now=1000))
        headers["X-Roztash-Actor"] = "owner@example.test"
        self.assertIsNone(bridge_auth.verify_request("POST", "/api/monitoring", body, headers, now=1000))

    def test_expired_unsigned_and_malformed_requests_rejected(self):
        headers = bridge_auth.sign_request("POST", "/api/monitoring", b"{}", "viewer@example.test", now=1000)
        self.assertIsNone(bridge_auth.verify_request("POST", "/api/monitoring", b"{}", headers, now=1400))
        self.assertIsNone(bridge_auth.verify_request("POST", "/api/monitoring", b"{}", {}, now=1000))
        headers["X-Roztash-Time"] = "not-a-time"
        self.assertIsNone(bridge_auth.verify_request("POST", "/api/monitoring", b"{}", headers, now=1000))

    def test_key_is_private_and_reused(self):
        first = bridge_auth.sign_request("POST", "/api/monitoring", b"{}", "viewer@example.test", now=1000)
        second = bridge_auth.sign_request("POST", "/api/monitoring", b"{}", "viewer@example.test", now=1000)
        self.assertEqual(first, second)
        self.assertEqual(len(self.key.read_bytes()), 32)
        if os.name != "nt":
            self.assertEqual(self.key.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
