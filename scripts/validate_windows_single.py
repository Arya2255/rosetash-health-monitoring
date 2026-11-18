"""Validate the single-file Windows payload without executing hardware tools.

Run before packaging with --inputs-only, and after packaging with the EXE path.
Only application assets and the manifest-listed gateway bundle are project data.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PREFIX = "distribution/gateway-provisioner/"
WINDOWS_TOOLS = {
    "esptool.exe", "mklittlefs.exe", "libwinpthread-1.dll",
    "LICENSE.esptool.txt", "LICENSE.mklittlefs.txt",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def payload_files(root=ROOT):
    """Return the allowlisted project payload and check every manifest digest."""
    bundle = root / BUNDLE_PREFIX
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["fw_version"] == "0.5.2-alerts", "Wrong firmware version")
    require(manifest["flash"]["chip"] == "esp32s3", "Wrong gateway chip")
    require(manifest["flash"]["size"] == "16MB", "Wrong flash size")
    require(WINDOWS_TOOLS <= manifest["tools"]["windows-amd64"].keys(),
            "Incomplete Windows tools/DLL/licenses in manifest")
    entries = {entry["file"]: entry for entry in manifest["flash"]["files"]}
    for platform, tools in manifest["tools"].items():
        entries.update({f"tools/{platform}/{name}": entry for name, entry in tools.items()})
    expected_bundle = {"manifest.json", *entries}
    actual_bundle = {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()}
    require(actual_bundle == expected_bundle,
            f"Unexpected or missing gateway files: {actual_bundle ^ expected_bundle}")
    for name, entry in entries.items():
        content = (bundle / name).read_bytes()
        require(len(content) == entry["size"], f"Wrong size: {name}")
        require(hashlib.sha256(content).hexdigest() == entry["sha256"],
                f"Wrong SHA-256: {name}; preserve bundle bytes at checkout")
    result = {BUNDLE_PREFIX + name: bundle / name for name in expected_bundle}
    assets = root / "src/assets"
    for file in assets.rglob("*"):
        if file.is_file():
            require(file.suffix.lower() in {".png", ".jpg", ".jpeg", ".ttf"},
                    f"Unexpected asset type (possible local state): {file.name}")
            result["assets/" + file.relative_to(assets).as_posix()] = file
    for filename in ("logo-colored.png", "logo-white.png", "factory-map.jpg",
                     "fonts/Vazirmatn-Regular.ttf", "fonts/Vazirmatn-Medium.ttf",
                     "fonts/Vazirmatn-SemiBold.ttf", "fonts/Vazirmatn-Bold.ttf",
                     "fonts/Vazirmatn-ExtraBold.ttf"):
        require("assets/" + filename in result, f"Missing asset: {filename}")
    return result


def validate_payload(names, extract, expected):
    """Check the packed bytes, including all DLLs and licenses, against checkout."""
    project_names = {name for name in names
                     if name.startswith(("assets/", BUNDLE_PREFIX))}
    require(project_names == set(expected),
            f"Unexpected or missing packed project data: {project_names ^ set(expected)}")
    for name, file in expected.items():
        require(extract(name) == file.read_bytes(), f"Packed bytes differ: {name}")
    forbidden_parts = {".git", ".venv", ".cloudflared", ".config", "logs", "__pycache__"}
    forbidden_names = {".env", "session.json", "admin_roles.json", "config.json",
                       "rosetash-remote.json", "rosetash-cf-api-token",
                       "rosetash-tunnel-token", "bridge-auth.key"}
    for name in names:
        path = PurePosixPath(name.lower())
        require(not (set(path.parts) & forbidden_parts)
                and path.name not in forbidden_names
                and path.suffix not in {".log", ".key", ".env"},
                f"Local configuration, credentials or logs in archive: {name}")


def validate_exe(executable, root=ROOT):
    from PyInstaller.archive.readers import CArchiveReader

    require(executable.is_file(), f"Missing executable: {executable}")
    require(list(executable.parent.iterdir()) == [executable],
            "Delivery directory must contain exactly one EXE and no sidecar files")
    with executable.open("rb") as stream:
        require(stream.read(2) == b"MZ", "Not a Windows PE executable")
        stream.seek(0x3C)
        pe_offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(pe_offset)
        require(stream.read(4) == b"PE\0\0", "Invalid PE signature")
        require(struct.unpack("<H", stream.read(2))[0] == 0x8664, "Not a Windows x64 EXE")
        stream.seek(pe_offset + 24 + 68)
        require(struct.unpack("<H", stream.read(2))[0] == 2, "Expected windowed GUI EXE")

    archive = CArchiveReader(str(executable))
    names = {name.replace("\\", "/"): name for name in archive.toc}
    extract = lambda name: archive.extract(names[name])
    expected = payload_files(root)
    validate_payload(names, extract, expected)
    runtime_manifest = "runtime/windows/runtime-manifest.json"
    require(runtime_manifest in names, "Bundled broker/tunnel runtime missing")
    runtime = json.loads(extract(runtime_manifest))
    for name in ("mosquitto/mosquitto.exe", "mosquitto/mosquitto_pub.exe",
                 "mosquitto/mosquitto_sub.exe", "cloudflared.exe"):
        require(name in runtime, "Missing service executable: " + name)
    for name, metadata in runtime.items():
        item = "runtime/windows/" + name
        require(item in names, "Missing service runtime file: " + name)
        data = extract(item)
        require(len(data) == metadata['size'] and
                hashlib.sha256(data).hexdigest() == metadata['sha256'],
                "Service runtime hash mismatch: " + name)
    require(not any(entry[-1] == "d" for entry in archive.toc.values()),
            "Archive references an external PyInstaller dependency")
    require(any(name.startswith("python3") and name.endswith(".dll") for name in names),
            "Embedded Python runtime missing")
    require("PYZ.pyz" in names, "Embedded Python modules missing")
    modules = archive.open_embedded_archive(names["PYZ.pyz"]).toc
    for module in ("flet", "flet_desktop", "flet_web.fastapi.serve_fastapi_web_app",
                   "uvicorn", "uvicorn.protocols.websockets.websockets_impl",
                   "provisioner", "views.login", "remote", "portable_runtime",
                   "private_profile", "state_paths", "backend.bridge", "backend.battery_alerts",
                   "backend.staff_alerts",
                   "ble_discovery", "bleak", "bleak.backends.winrt.scanner",
                   "tools.discovery_udp",
                   "http.server", "smtplib", "urllib.request", "tzdata"):
        require(module in modules, f"Missing Python module: {module}")
    require("tzdata/zoneinfo/Asia/Tehran" in names, "Missing Tehran timezone data")
    # no_cdn=True must be usable without a browser downloading the UI runtime.
    import importlib
    flet_web = importlib.import_module("flet_web")
    assert flet_web.__file__ is not None
    web_root = Path(flet_web.__file__).parent / "web"
    web_files = [p for p in web_root.rglob("*")
                 if p.is_file() and p.suffix not in {".py", ".pyc"}]
    require(bool(web_files), "Installed Flet web runtime is empty")
    for file in web_files:
        name = "flet_web/web/" + file.relative_to(web_root).as_posix()
        require(name in names, f"Missing embedded web runtime asset: {name}")
        require(extract(name) == file.read_bytes(), f"Web runtime bytes differ: {name}")

    client_path = "flet_desktop/app/flet-windows.zip"
    require(client_path in names, "Flet desktop client is not embedded (offline launch would fail)")
    with zipfile.ZipFile(io.BytesIO(extract(client_path))) as client:
        require(client.testzip() is None, "Corrupt embedded Flet client archive")
        require({"flet/flet.exe", "flet/flutter_windows.dll"} <= set(client.namelist()),
                "Embedded Flet Windows client is incomplete")
        require(any(name.startswith("flet/data/flutter_assets/") for name in client.namelist()),
                "Embedded Flutter assets missing")
    print(f"PASS: x64 GUI onefile EXE; {len(expected)} project payload files match checkout; "
          "Flet/Python runtimes and required modules embedded")
    print(f"EXE SHA-256: {hashlib.sha256(executable.read_bytes()).hexdigest()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", nargs="?", type=Path)
    parser.add_argument("--inputs-only", action="store_true")
    args = parser.parse_args()
    if args.inputs_only:
        print(f"PASS: {len(payload_files())} allowlisted payload files; all gateway hashes match")
    elif args.exe:
        validate_exe(args.exe.resolve())
    else:
        parser.error("Pass an EXE path or --inputs-only")


if __name__ == "__main__":
    main()
