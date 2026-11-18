"""Exercise private first-run configuration using ONLY synthetic CI values."""
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from private_profile import append_profile


def main():
    original = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix='roztash-personalize-test-') as tmp:
        root = Path(tmp)
        binary = root/'app.exe'
        shutil.copy2(original,binary)
        database=root/'seed.db'
        with sqlite3.connect(database) as db:
            db.execute('CREATE TABLE test_marker(value TEXT)')
            db.execute('INSERT INTO test_marker VALUES(?)',('synthetic',))
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('remote.json',json.dumps({'auto_start':False,'smtp':{
                'host':'smtp.example.invalid','port':587,'user':'ci@example.invalid','password':'SYNTHETIC_ONLY'}}))
            z.writestr('admin_roles.json',json.dumps({'roles':{},'names':{}}))
            z.writestr('state/live.db',database.read_bytes())
        append_profile(binary,out.getvalue())
        env={k:v for k,v in os.environ.items() if not k.startswith(('ROZTASH_','ROSETASH_','FLET_'))}
        env['ROZTASH_HOME']=str(root/'profile')
        env['USERPROFILE']=str(root/'isolated-user')
        env['LOCALAPPDATA']=str(root/'isolated-user/AppData/Local')
        env['PYTHONUTF8']='1'
        subprocess.run([str(binary),'--inspect-install'],env=env,check=True,timeout=60)
        check=json.loads((root/'profile/install-check.json').read_text())
        assert all(check[k] for k in ('smtp_configured','database_present','broker_bundled','tunnel_bundled')),check
        cfg=root/'profile/cloudflared/rosetash-remote.json'
        parsed=json.loads(cfg.read_text())
        assert parsed['smtp']['password']=='SYNTHETIC_ONLY'
        parsed['smtp']['password']='LOCALLY_CHANGED'
        cfg.write_text(json.dumps(parsed))
        subprocess.run([str(binary),'--inspect-install'],env=env,check=True,timeout=60)
        assert json.loads(cfg.read_text())['smtp']['password']=='LOCALLY_CHANGED'
        db=sqlite3.connect(root/'profile/state/live.db')
        try:
            assert db.execute('SELECT value FROM test_marker').fetchone()==('synthetic',)
        finally:
            # SQLite's context manager commits/rolls back but does not close the
            # connection; Windows refuses TemporaryDirectory cleanup otherwise.
            db.close()
        assert not (root/'profile/session.json').exists()
    print('PASS: personalized EXE starts; config/DB imported; upgrades preserve state; no credentials or mail used')


if __name__=='__main__':main()
