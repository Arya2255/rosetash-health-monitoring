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


if __name__ == "__main__":
    unittest.main()
