"""Verify the shared source/frozen entrypoint without starting services."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import main as app_main


class WebEntrypointTests(unittest.TestCase):
    def test_web_mode_binds_tunnel_origin_and_uses_packaged_assets(self):
        with patch.object(app_main.ft, 'run') as run, patch.dict(os.environ, {}, clear=True), \
                patch('threading.Thread') as worker:
            app_main.run_app(web=True)
            self.assertEqual(os.environ.get('FLET_FORCE_WEB_SERVER'), 'true')
            self.assertEqual(run.call_args.kwargs['host'], '127.0.0.1')
            self.assertEqual(run.call_args.kwargs['port'], 8550)
            self.assertTrue(run.call_args.kwargs['no_cdn'])
            self.assertTrue(Path(run.call_args.kwargs['assets_dir']).is_absolute())
            self.assertTrue((Path(run.call_args.kwargs['assets_dir']) / 'logo-white.png').is_file())
            self.assertIs(worker.call_args.kwargs['target'], app_main.remote_autostart)
            worker.return_value.start.assert_called_once()

    def test_desktop_mode_remains_desktop(self):
        with patch.object(app_main.ft, 'run') as run, patch.dict(os.environ, {}, clear=True), \
                patch('threading.Thread') as worker:
            app_main.run_app()
            self.assertNotIn('FLET_FORCE_WEB_SERVER', os.environ)
            self.assertNotIn('port', run.call_args.kwargs)
            self.assertNotIn('host', run.call_args.kwargs)
            worker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
