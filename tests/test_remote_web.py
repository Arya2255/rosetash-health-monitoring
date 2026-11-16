"""Tunnel status must not claim the web app is ready on a closed origin."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import remote


class RemoteWebStatusTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(remote, 'ensure_config', return_value={
            'ok': True, 'host': 'panel.example.test', 'zone': 'example.test',
        }))
        self.enterContext(patch.object(remote, 'tunnel_running', return_value=True))
        self.enterContext(patch.object(remote, 'allowed_emails', return_value=['admin@example.test']))
        self.enterContext(patch.object(remote, 'public_url', return_value='https://panel.example.test'))
        self.enterContext(patch.object(remote, 'bin_ready', return_value=True))

    def test_live_tunnel_with_closed_origin_reports_web_unavailable(self):
        with patch.object(remote.urllib.request, 'urlopen', side_effect=ConnectionRefusedError):
            status = remote.status()
        self.assertFalse(status.get('web_running', True))
        self.assertEqual(status['label'], 'سرور وب خاموش است')
        self.assertNotIn('پنل از اینترنت با قفل ایمیلی کلادفلر باز است', status['detail'])

    def test_live_tunnel_with_flet_origin_reports_components_ready(self):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'<html><script src="flutter_bootstrap.js"></script></html>'
        response.__enter__.return_value = response
        with patch.object(remote.urllib.request, 'urlopen', return_value=response) as request:
            status = remote.status()
        self.assertTrue(status.get('web_running', False))
        self.assertEqual(status['label'], 'فعال')
        self.assertIn('سرور وب', status['detail'])
        self.assertEqual(request.call_args.args[0], 'http://127.0.0.1:8550/')

    def test_unrelated_http_service_does_not_count_as_flet(self):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'<html>Other service</html>'
        response.__enter__.return_value = response
        with patch.object(remote.urllib.request, 'urlopen', return_value=response):
            status = remote.status()
        self.assertFalse(status.get('web_running', True))


if __name__ == '__main__':
    unittest.main()
