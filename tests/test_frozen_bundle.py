"""Offline packaging regressions; never connect to a gateway or send mail."""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_provisioner(module_path):
    spec = importlib.util.spec_from_file_location("frozen_provisioner_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrozenBundleTests(unittest.TestCase):
    def test_onefile_uses_extraction_root_from_an_unrelated_working_directory(self):
        with tempfile.TemporaryDirectory(prefix="frozen-bundle-") as tmp:
            base = Path(tmp)
            extracted = base / "_MEI12345"
            extracted.mkdir()
            shutil.copy2(ROOT / "src/provisioner.py", extracted / "provisioner.py")
            expected = extracted / "distribution/gateway-provisioner"
            shutil.copytree(ROOT / "distribution/gateway-provisioner", expected)
            unrelated = base / "unrelated"
            unrelated.mkdir()
            previous_cwd = Path.cwd()
            try:
                os.chdir(unrelated)
                with patch.object(sys, "frozen", True, create=True), \
                        patch.object(sys, "_MEIPASS", str(extracted), create=True), \
                        patch.dict(os.environ, {}, clear=True):
                    pv = load_provisioner(extracted / "provisioner.py")
                    self.assertEqual(pv.bundle_dir(), expected)
                    ok, manifest = pv.load_manifest()
                    self.assertTrue(ok, manifest)
                    self.assertEqual(manifest["fw_version"], "0.5.2-alerts")
                    tools = pv.find_tools(platform="windows-amd64", home=unrelated)
                    self.assertEqual(tools["sources"], {
                        "esptool": "bundled", "mklittlefs": "bundled"})
                    for name in ("esptool", "mklittlefs"):
                        self.assertTrue(Path(tools[name]).is_relative_to(expected))
            finally:
                os.chdir(previous_cwd)

    def test_source_layout_is_preserved(self):
        with patch.object(sys, "frozen", False, create=True), \
                patch.dict(os.environ, {}, clear=True):
            pv = load_provisioner(ROOT / "src/provisioner.py")
            self.assertEqual(pv.bundle_dir(), ROOT / "distribution/gateway-provisioner")

    def test_flet_app_directory_layout_is_preserved_without_meipass(self):
        with tempfile.TemporaryDirectory(prefix="flet-bundle-") as tmp:
            base = Path(tmp)
            app = base / "app"
            app.mkdir()
            shutil.copy2(ROOT / "src/provisioner.py", app / "provisioner.py")
            with patch.object(sys, "frozen", True, create=True), \
                    patch.dict(os.environ, {}, clear=True):
                pv = load_provisioner(app / "provisioner.py")
                expected = base / "distribution/gateway-provisioner"
                expected.mkdir(parents=True)
                self.assertTrue(os.path.samefile(pv.bundle_dir(), expected))

    def test_environment_overrides_keep_both_spellings_and_precedence(self):
        with tempfile.TemporaryDirectory(prefix="override-bundle-") as tmp:
            base = Path(tmp)
            with patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "_MEIPASS", tmp, create=True):
                pv = load_provisioner(ROOT / "src/provisioner.py")
                for env, expected in (
                    ({"ROZTASH_PROVISIONER": str(base / "primary")}, base / "primary"),
                    ({"ROSETASH_PROVISIONER": str(base / "alias")}, base / "alias"),
                    ({"ROZTASH_PROVISIONER": str(base / "primary"),
                      "ROSETASH_PROVISIONER": str(base / "alias")}, base / "primary"),
                    ({"ROZTASH_PROVISIONER": ""}, base / "distribution/gateway-provisioner"),
                ):
                    with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                        self.assertEqual(pv.bundle_dir(), expected)

    def test_windowed_stdio_hook_allows_uvicorn_configuration(self):
        # Uvicorn config modifies global logging, so exercise it in a child.
        import subprocess
        code = (
            "import runpy, sys, uvicorn; "
            "sys.stdout = sys.stderr = None; "
            f"runpy.run_path({str(ROOT / 'scripts/pyi_windowed_stdio.py')!r}); "
            "uvicorn.Config('unused:app')"
        )
        result = subprocess.run([sys.executable, "-B", "-c", code],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_flet_resolves_assets_at_onefile_root(self):
        # Exercise the installed Flet resolver, not a duplicate of its logic.
        import importlib
        flet_app = importlib.import_module("flet.app")
        with tempfile.TemporaryDirectory(prefix="_MEI-assets-") as tmp:
            extracted = Path(tmp)
            shutil.copytree(ROOT / "src/assets", extracted / "assets")
            with patch.object(flet_app, "__file__", str(extracted / "flet/app.py")), \
                    patch.dict(os.environ, {}, clear=True):
                resolved = getattr(flet_app, "__get_assets_dir_path")("assets")
            self.assertTrue(os.path.samefile(Path(resolved), extracted / "assets"))
            self.assertTrue((Path(resolved) / "fonts/Vazirmatn-Regular.ttf").is_file())
            self.assertTrue((Path(resolved) / "logo-colored.png").is_file())


class PayloadValidationTests(unittest.TestCase):
    def test_windows_scan_backend_is_explicitly_packaged(self):
        workflow = (ROOT / '.github/workflows/build-windows-single.yml').read_text()
        self.assertIn('--collect-submodules bleak', workflow)
        hidden_line = next(line for line in workflow.splitlines() if '--hidden-import' in line)
        self.assertIn('ble_discovery', hidden_line.split())

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "validate_windows_single", ROOT / "scripts/validate_windows_single.py")
        assert spec is not None and spec.loader is not None
        cls.validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.validator)
        cls.expected = cls.validator.payload_files()

    def test_complete_payload_matches_repository_and_manifest(self):
        self.validator.validate_payload(
            self.expected, lambda name: self.expected[name].read_bytes(), self.expected)

    def test_missing_font_or_windows_dll_is_rejected(self):
        for name in ("assets/fonts/Vazirmatn-Regular.ttf",
                     "distribution/gateway-provisioner/tools/windows-amd64/libwinpthread-1.dll"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "missing"):
                self.validator.validate_payload(
                    set(self.expected) - {name}, lambda n: self.expected[n].read_bytes(),
                    self.expected)

    def test_altered_firmware_or_license_is_rejected(self):
        for name in ("distribution/gateway-provisioner/firmware/app.bin",
                     "distribution/gateway-provisioner/tools/windows-amd64/LICENSE.esptool.txt"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "bytes differ"):
                self.validator.validate_payload(
                    self.expected,
                    lambda n: b"corrupt fixture" if n == name else self.expected[n].read_bytes(),
                    self.expected)

    def test_user_configuration_sessions_and_logs_are_rejected(self):
        for name in (".env", ".cloudflared/rosetash-cf-api-token", "session.json",
                     "logs/app.log", "config.json"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "configuration"):
                self.validator.validate_payload(
                    {*self.expected, name}, lambda n: self.expected[n].read_bytes(),
                    self.expected)


if __name__ == "__main__":
    unittest.main()
