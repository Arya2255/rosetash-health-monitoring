"""Resource URLs and network adapters must work away from the Linux host."""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parents[1])]
import live
import backend.bridge as bridge


class PortableResourcesTests(unittest.TestCase):
    def test_photo_is_inlined_for_remote_browsers(self):
        image=io.BytesIO(b'\x89PNG\r\n\x1a\nfixture')
        image.headers={'Content-Type':'image/png'}
        with patch.object(live.urllib.request,'urlopen',return_value=image):
            value=live.photo_src({'photo':'/api/photo/aa:bb:cc:dd:ee:ff'})
        self.assertTrue(value.startswith('data:image/png;base64,'))
        self.assertNotIn('127.0.0.1',value)

    def test_photo_rejects_nonlocal_path(self):
        with patch.object(live.urllib.request,'urlopen') as fetch:
            self.assertIsNone(live.photo_src({'photo':'https://example.invalid/photo'}))
            fetch.assert_not_called()

    def test_windows_lists_all_local_ipv4_interfaces(self):
        rows=[{'InterfaceAlias':'Ethernet','IPAddress':'192.0.2.10','PrefixLength':24},
              {'InterfaceAlias':'Loopback','IPAddress':'127.0.0.1','PrefixLength':8}]
        with patch.object(bridge.sys,'platform','win32'), \
                patch.object(bridge,'_run_cmd',return_value=json.dumps(rows)) as run, \
                patch.object(bridge.socket,'socket',side_effect=OSError):
            values=bridge._host_ip_candidates()
        self.assertEqual(values,[{'iface':'Ethernet','ip':'192.0.2.10','prefix':'24'}])
        self.assertEqual(run.call_args.args[0][0],'powershell')


if __name__=='__main__':unittest.main()
