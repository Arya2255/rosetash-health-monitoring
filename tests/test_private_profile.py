"""Private personalization is local-only, allowlisted, and never logs secrets."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import private_profile as pp


def payload(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()


class PrivateProfileTests(unittest.TestCase):
    def test_profile_round_trip_only_initializes_missing_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / 'app.exe'
            binary.write_bytes(b'MZ synthetic executable fixture')
            data = payload({'remote.json': json.dumps({'smtp': {'password': 'synthetic-only'}}),
                            'admin_roles.json': '{"roles": {}}', 'state/live.db': 'fixture'})
            pp.append_profile(binary, data)
            self.assertEqual(pp.read_profile(binary), data)
            state = root / 'user'
            result = pp.install_profile(binary, state)
            self.assertIn('remote.json', result)
            config = state / 'cloudflared/rosetash-remote.json'
            self.assertEqual(json.loads(config.read_text())['smtp']['password'], 'synthetic-only')
            config.write_text('{"changed":true}')
            self.assertEqual(pp.install_profile(binary, state), [])
            self.assertEqual(json.loads(config.read_text()), {'changed': True})

    def test_unpersonalized_binary_has_no_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'app.exe'
            p.write_bytes(b'MZ test')
            self.assertIsNone(pp.read_profile(p))

    def test_rejects_unexpected_paths_and_auth_sessions(self):
        for name in ('../outside', '/absolute', 'session.json', 'unknown.json', 'state/photos/../../bad'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                pp.validate_profile(payload({name: 'fixture'}))

    def test_corruption_is_reported_without_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'app.exe'
            p.write_bytes(b'MZ test')
            pp.append_profile(p, payload({'remote.json': '{}'}))
            b = bytearray(p.read_bytes()); b[15] ^= 1; p.write_bytes(b)
            with self.assertRaisesRegex(ValueError, 'checksum'):
                pp.read_profile(p)


if __name__ == '__main__':
    unittest.main()
