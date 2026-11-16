"""Upgrade a disposable copy of the previous SQLite schema without data loss."""
import ast
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'backend')]
import bridge


class MigrationTests(unittest.TestCase):
    def test_previous_schema_preserves_employee_and_adds_disabled_schedule(self):
        old_source=subprocess.check_output(['git','show','b8c01dc:backend/bridge.py'],cwd=ROOT,text=True)
        module=ast.parse(old_source)
        schema=next(ast.literal_eval(node.value) for node in module.body if isinstance(node,ast.Assign)
                    and any(isinstance(target,ast.Name) and target.id=='SCHEMA' for target in node.targets))
        with tempfile.TemporaryDirectory(prefix='monitor-migrate-') as directory:
            db=Path(directory)/'live.db'
            with sqlite3.connect(db) as con:
                con.executescript(schema)
                con.execute('INSERT INTO employees(mac,name,dept,photo,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                            ('aa:bb:cc:dd:ee:01','Migration Fixture','Fixture Dept','portrait.jpg',100,100))
                con.execute('INSERT INTO bands(mac,gw,rssi,seen_at) VALUES(?,?,?,?)',
                            ('aa:bb:cc:dd:ee:01','gw-a',-60,100))
            with patch.object(bridge,'DB_PATH',str(db)), patch.object(bridge,'PHOTOS_DIR',str(Path(directory)/'photos')),patch.object(bridge,'_db',None):
                try:
                    for _ in range(2):
                        row=dict(bridge.db().execute('SELECT * FROM employees').fetchone())
                        self.assertEqual(row['name'],'Migration Fixture')
                        self.assertEqual(row['dept'],'Fixture Dept')
                        self.assertEqual(row['photo'],'portrait.jpg')
                        self.assertEqual(json.loads(row['weekly_schedule']),{})
                        self.assertEqual(bridge.employee_scan_policy()['active_macs'],[])
                        self.assertEqual(bridge.monitoring_settings()['health_interval_s'],600)
                        self.assertEqual(bridge.db().execute('SELECT COUNT(*) FROM band_observations').fetchone()[0],1)
                        bridge._db.close();bridge._db=None
                finally:
                    if bridge._db is not None:bridge._db.close();bridge._db=None


if __name__=='__main__':
    unittest.main()
