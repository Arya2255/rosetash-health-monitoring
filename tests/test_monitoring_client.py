"""Signed monitoring client requests and readable HTTP failures (no live server)."""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from email.message import Message
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import live
import bridge_auth


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="monitor-client-")
        self.addCleanup(self.temp.cleanup)
        p=patch.dict(os.environ,{"ROZTASH_BRIDGE_AUTH_FILE":str(Path(self.temp.name)/"key")})
        p.start(); self.addCleanup(p.stop)
        p=patch.object(live,"MODE","auto");p.start();self.addCleanup(p.stop)

    def test_monitoring_write_is_signed_for_the_actual_actor_and_body(self):
        def accept(request,timeout):
            path=urllib.parse.urlparse(request.full_url).path
            actor=bridge_auth.verify_request("POST",path,request.data,dict(request.header_items()))
            self.assertEqual(actor,"viewer@example.test")
            self.assertEqual(json.loads(request.data)["scan_paused"],True)
            return io.BytesIO(b'{"ok":true}')
        with patch.object(live.urllib.request,"urlopen",side_effect=accept):
            ok,err=live.save_employee_monitoring({"mac":"aa:bb:cc:dd:ee:01",
                                                "actor":"viewer@example.test","scan_paused":True})
        self.assertTrue(ok,err)

    def test_forbidden_http_response_is_not_misreported_as_no_connection(self):
        error=urllib.error.HTTPError("http://127.0.0.1/api/monitoring",403,"Forbidden",Message(),
                                    io.BytesIO(b'{"ok":false,"error":"forbidden"}'))
        with patch.object(live.urllib.request,"urlopen",side_effect=error):
            ok,msg=live.save_employee_monitoring({"actor":"viewer@example.test","scan_paused":True})
        self.assertFalse(ok)
        self.assertEqual(msg,live._ERROR_FA["forbidden"])

    def test_vibrate_http_400_returns_bridge_reason_not_no_connection(self):
        error=urllib.error.HTTPError("http://127.0.0.1/api/command",400,"Bad Request",Message(),
                                    io.BytesIO(b'{"ok":false,"error":"no gateway known yet"}'))
        with patch.object(live.urllib.request,"urlopen",side_effect=error):
            ok, msg = live.send_vibrate("aa:bb:cc:dd:ee:01")
        self.assertFalse(ok)
        self.assertIn("وضعیت گیت‌وی", msg)

    def test_vibrate_unrecognized_error_does_not_copy_internal_details(self):
        error = urllib.error.HTTPError("http://127.0.0.1/api/command", 400, "Bad Request", Message(),
                                       io.BytesIO(b'{"ok":false,"error":"internal path or device identifier"}'))
        with patch.object(live.urllib.request, "urlopen", side_effect=error), \
                patch.object(live.applog, "warn") as warning:
            ok, msg = live.send_vibrate()
        self.assertFalse(ok)
        self.assertIn("400", msg)
        self.assertNotIn("internal path", msg)
        self.assertNotIn("internal path", repr(warning.call_args))

    def test_vibrate_http_error_without_json_still_identifies_rejection(self):
        error = urllib.error.HTTPError("http://127.0.0.1/api/command", 502, "Bad Gateway", Message(),
                                       io.BytesIO(b"<html>upstream error</html>"))
        with patch.object(live.urllib.request, "urlopen", side_effect=error):
            ok, msg = live.send_vibrate()
        self.assertFalse(ok)
        self.assertIn("502", msg)
        self.assertNotIn("<html>", msg)


if __name__ == "__main__":
    unittest.main()
