"""Offline regressions for the ESP32-S3 provisioner's complete flash bundle."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import provisioner as pv


class BundleLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bundle-layout-")
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name)
        # Synthetic fixture bytes only; never sent to hardware.
        addresses = {
            "bootloader.bin": "0x0", "partitions.bin": "0x8000",
            "boot_app0.bin": "0xe000", "app.bin": "0x10000",
            "littlefs-blank.bin": "0x3D0000",
        }
        files = []
        for filename, address in addresses.items():
            path = self.bundle / "firmware" / filename
            path.parent.mkdir(exist_ok=True)
            data = ("test fixture " + filename).encode()
            path.write_bytes(data)
            files.append({"file": "firmware/" + filename, "addr": address,
                          "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        self.doc = {"fw_version": pv.TARGET_FW_VERSION,
                    "flash": {"chip": "esp32s3", "size": "16MB", "files": files},
                    "littlefs": {"offset": "0x3D0000", "size": 0x20000,
                                 "page": 256, "block": 4096}}

    def load(self):
        (self.bundle / "manifest.json").write_text(json.dumps(self.doc))
        return pv.load_manifest(self.bundle)

    def test_complete_s3_layout_is_accepted(self):
        ok, result = self.load()
        self.assertTrue(ok, result)

    def test_legacy_bootloader_offset_is_rejected(self):
        self.doc["flash"]["files"][0]["addr"] = "0x1000"
        ok, result = self.load()
        self.assertFalse(ok, "legacy ESP32 bootloader offset was accepted")
        self.assertIn("error", result)

    def test_missing_or_duplicate_entry_is_rejected(self):
        original = copy.deepcopy(self.doc)
        for entries in ([], original["flash"]["files"][:-1],
                        original["flash"]["files"] + [original["flash"]["files"][0]]):
            with self.subTest(entries=len(entries)):
                self.doc = copy.deepcopy(original)
                self.doc["flash"]["files"] = entries
                self.assertFalse(self.load()[0], "incomplete/duplicate layout was accepted")

    def test_wrong_littlefs_geometry_is_rejected(self):
        self.doc["littlefs"]["offset"] = "0x300000"
        self.assertFalse(self.load()[0])

    def test_corrupted_artifact_is_rejected(self):
        (self.bundle / "firmware/app.bin").write_bytes(b"damaged")
        self.assertFalse(self.load()[0], "corrupted artifact was accepted")

    def test_malformed_manifest_returns_error(self):
        self.doc["flash"]["files"][0]["addr"] = "invalid"
        self.assertFalse(self.load()[0])


if __name__ == "__main__":
    unittest.main()
