"""Local-only first-run profile attached to a private unsigned executable.

This is packaging, NOT encryption: distribute personalized EXEs only privately.
Public CI artifacts contain no real credentials, employee records or sessions.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import struct
import zipfile

MAGIC = b'ROZTASH_PRIVATE_PROFILE_V1\0'
TRAILER = struct.Struct('<Q32s' + str(len(MAGIC)) + 's')
MAX_SIZE = 128 * 1024 * 1024
FILES = {
    'remote.json': 'cloudflared/rosetash-remote.json',
    'cf-api-token': 'cloudflared/rosetash-cf-api-token',
    'tunnel-token': 'cloudflared/rosetash-tunnel-token',
    'admin_roles.json': 'admin_roles.json',
    'emergency-key': '.emergency_key',
    'state/live.db': 'state/live.db',
}


def validate_profile(data):
    if len(data) > MAX_SIZE:
        raise ValueError('Private profile exceeds size limit')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or sum(i.file_size for i in archive.infolist()) > MAX_SIZE:
            raise ValueError('Invalid private profile entries')
        for name in names:
            path = PurePosixPath(name)
            if (path.is_absolute() or '..' in path.parts or '\\' in name
                    or not (name in FILES or
                            (len(path.parts) == 3 and path.parts[:2] == ('state', 'photos')
                             and path.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')))):
                raise ValueError('Unexpected private profile path')
        if archive.testzip() is not None:
            raise ValueError('Corrupt private profile archive')
    return names


def read_profile(executable):
    with Path(executable).open('rb') as stream:
        stream.seek(0, 2)
        size = stream.tell()
        if size < TRAILER.size:
            return None
        stream.seek(-TRAILER.size, 2)
        length, digest, magic = TRAILER.unpack(stream.read(TRAILER.size))
        if magic != MAGIC:
            return None
        if length > MAX_SIZE or length > size - TRAILER.size:
            raise ValueError('Invalid private profile length')
        stream.seek(size - TRAILER.size - length)
        data = stream.read(length)
    if hashlib.sha256(data).digest() != digest:
        raise ValueError('Private profile checksum mismatch')
    validate_profile(data)
    return data


def append_profile(executable, data):
    validate_profile(data)
    if read_profile(executable) is not None:
        raise ValueError('Executable already has a private profile')
    with Path(executable).open('ab') as stream:
        stream.write(data)
        stream.write(TRAILER.pack(len(data), hashlib.sha256(data).digest(), MAGIC))


def install_profile(executable, root):
    """Never replace any existing settings or database on an upgrade."""
    root = Path(root)
    data = read_profile(executable)
    if data is None:
        return []
    installed = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            target = root / FILES.get(name, name)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            with os.fdopen(fd, 'wb') as stream:
                stream.write(archive.read(name))
            installed.append(name)
    return installed
