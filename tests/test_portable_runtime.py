"""Verify portable startup paths using isolated temporary state only."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import portable_runtime as runtime


class PortableRuntimeTests(unittest.TestCase):
    def test_paths_point_to_writable_persistent_state(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{},clear=True):
            result = runtime.configure_state(Path(tmp)/'profile')
            self.assertEqual(Path(os.environ['ROZTASH_BRIDGE_DB']),result/'state/live.db')
            self.assertEqual(Path(os.environ['ROZTASH_CONFIG_HOME']),result)
            self.assertEqual(Path(os.environ['ROZTASH_CF_HOME']),result/'cloudflared')
            self.assertTrue((result/'logs').is_dir())

    def test_explicit_external_bridge_override_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'ROZTASH_BRIDGE':'http://example.invalid:9000'},clear=True):
            runtime.configure_state(Path(tmp))
            self.assertEqual(os.environ['ROZTASH_BRIDGE'],'http://example.invalid:9000')

    def test_valid_existing_bridge_is_reused_and_not_owned(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{},clear=True):
            runtime.configure_state(Path(tmp))
            supervisor=runtime.LocalServices(Path(tmp))
            with patch.object(runtime,'bridge_healthy',return_value=True),patch.object(runtime.subprocess,'Popen') as spawn:
                supervisor.start_bridge()
            spawn.assert_not_called()
            self.assertEqual(supervisor.children,[])

    def test_child_web_worker_does_not_start_recursive_services(self):
        with patch.dict(os.environ,{'ROZTASH_CHILD_WORKER':'web'},clear=True):
            self.assertFalse(runtime.should_bootstrap())


if __name__=='__main__':unittest.main()
