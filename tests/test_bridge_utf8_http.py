"""HTTP mutations remain successful with a legacy Windows service console."""
import http.client
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import bridge


class Cp1252Console:
    encoding = "cp1252"

    def write(self, value):
        value.encode(self.encoding)
        return len(value)

    def flush(self):
        pass


class BridgeUtf8HttpTests(unittest.TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory
        self.temp = TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        bridge._db = None
        for name, value in (("DB_PATH", str(Path(self.temp.name) / "db.sqlite")),
                            ("PHOTOS_DIR", str(Path(self.temp.name) / "photos"))):
            patcher = patch.object(bridge, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        if bridge._db is not None:
            bridge._db.close()
            bridge._db = None

    def test_persian_form_saves_return_json_and_persist_the_text(self):
        server = bridge.Server(("127.0.0.1", 0), bridge.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def stop_server():
            server.shutdown()
            server.server_close()
            thread.join(2)

        self.addCleanup(stop_server)
        mac = "aa:bb:cc:dd:ee:81"
        mutations = (
            ("/api/bands", {"mac": mac, "label": "مچ‌بند آزمایشی"}),
            ("/api/bands", {"mac": mac, "label": "مچ‌بند ویرایش‌شده"}),
            ("/api/employees", {"mac": mac, "name": "رضا"}),
            ("/api/employees", {"mac": mac, "name": "رضای آزمایشی"}),
            ("/api/catalogs", {"kind": "unit", "name": "واحد آزمایشی"}),
        )
        with patch.object(bridge.sys, "stdout", Cp1252Console()):
            for path, payload in mutations:
                with self.subTest(path=path, payload=payload):
                    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                    try:
                        connection.request("POST", path, body,
                                           {"Content-Type": "application/json"})
                        response = connection.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertTrue(json.load(response)["ok"])
                    finally:
                        connection.close()
        self.assertEqual(bridge.employees_list()[0]["name"], "رضای آزمایشی")
        self.assertEqual(bridge.bands_list()[0]["label"], "مچ‌بند ویرایش‌شده")
        self.assertEqual(bridge.catalogs_list()["unit"][0]["name"], "واحد آزمایشی")


if __name__ == "__main__":
    unittest.main()
