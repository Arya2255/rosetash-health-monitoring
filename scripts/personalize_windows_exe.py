"""Create the owner's PRIVATE deployment EXE locally; never run with real data in CI.

The result contains readable SMTP/tunnel credentials and personal records.
It must not be uploaded to GitHub or distributed to other users.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from private_profile import append_profile, read_profile, install_profile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    if args.output.exists():
        raise SystemExit('Refusing to overwrite an existing private deployment')
    import remote
    cfg = remote.config()
    smtp = cfg.get('smtp',{})
    if not smtp.get('password') or smtp.get('password')=='APP_PASSWORD' or not smtp.get('user'):
        raise SystemExit('Source mail configuration is incomplete')
    # Allowlist only deployment settings: never copy sessions, PIDs or Linux binaries.
    selected={k:cfg[k] for k in ('zone','zone_id','account_id','host','tunnel_id','emails','smtp') if k in cfg}
    selected['auto_start']=True
    private={ 'remote.json': json.dumps(selected,ensure_ascii=False).encode('utf-8') }
    base=Path(remote._home())
    for source,target in (('rosetash-cf-api-token','cf-api-token'),('rosetash-tunnel-token','tunnel-token')):
        path=base/source
        if path.is_file():private[target]=path.read_bytes()
    state=Path.home()/'.config/roztash'
    for source,target in (('admin_roles.json','admin_roles.json'),('.emergency_key','emergency-key')):
        path=state/source
        if path.is_file():private[target]=path.read_bytes()
    if 'admin_roles.json' not in private:
        from admin_roles import list_admins
        private['admin_roles.json']=json.dumps({'roles':{a['email']:a['role'] for a in list_admins()},'names':{}},ensure_ascii=False).encode('utf-8')
    db_path=Path(os.environ.get('ROZTASH_BRIDGE_DB',str(ROOT/'backend/state/live.db')))
    with tempfile.TemporaryDirectory(prefix='roztash-private-export-',dir=os.environ.get('TMPDIR')) as temp:
        temp=Path(temp)
        backup=temp/'live.db'
        # SQLite online backup includes committed WAL content without stopping the live bridge.
        with sqlite3.connect('file:'+str(db_path)+'?mode=ro',uri=True) as source, sqlite3.connect(backup) as dest:
            source.backup(dest)
            assert dest.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        private['state/live.db']=backup.read_bytes()
        for image in (db_path.parent/'photos').glob('*'):
            if image.is_file() and image.suffix.lower() in ('.jpg','.jpeg','.png','.webp'):
                private['state/photos/'+image.name]=image.read_bytes()
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,blob in private.items():archive.writestr(name,blob)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with args.base.open('rb') as source,os.fdopen(fd,'wb') as target:shutil.copyfileobj(source,target)
        append_profile(args.output,buffer.getvalue())
        assert read_profile(args.output)==buffer.getvalue()
        # Verify exact final payload extraction locally; credentials remain unprinted.
        profile=temp/'verify'
        installed=install_profile(args.output,profile)
        assert len(installed)==len(private)
        assert json.loads((profile/'cloudflared/rosetash-remote.json').read_text())==selected
        with sqlite3.connect(profile/'state/live.db') as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        with args.base.open('rb') as a,args.output.open('rb') as b:
            while block:=a.read(1024*1024):assert b.read(len(block))==block
    print('PRIVATE deliverable:',args.output.resolve())
    print('Bytes:',args.output.stat().st_size)
    print('SHA256:',hashlib.file_digest(args.output.open('rb'),'sha256').hexdigest())
    print('Verified: executable prefix unchanged; SMTP/tunnel settings and consistent SQLite snapshot imported')
    print('Private profile file count:',len(private))
    print('Do not upload this personalized executable or its profile to GitHub.')


if __name__=='__main__':main()
