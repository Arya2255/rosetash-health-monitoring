"""Authenticate monitoring writes from the trusted local Flet server to its bridge.

Both processes run as the same OS user. Browser clients never receive this key.
This does not protect against a process already running as that OS user.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path


def _key_path() -> Path:
    return Path(os.environ.get("ROZTASH_BRIDGE_AUTH_FILE") or
                Path.home() / ".config" / "roztash" / "bridge-auth.key")


def _load_key(create=False) -> bytes:
    path = _key_path()
    if create and not path.exists():
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        pending = path.with_name(path.name + ".pending-" + secrets.token_hex(8))
        try:
            fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(secrets.token_bytes(32))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(pending, path)
            except FileExistsError:
                pass
        finally:
            pending.unlink(missing_ok=True)
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("invalid bridge authentication key")
    return key


def _message(method, path, body, stamp, actor):
    return "\n".join((method.upper(), path, stamp, actor,
                      hashlib.sha256(body).hexdigest())).encode("utf-8")


def sign_request(method, path, body, actor, *, now=None) -> dict[str, str]:
    actor = str(actor or "").strip().lower()
    if not actor or any(c in actor for c in "\r\n"):
        raise ValueError("actor required")
    stamp = str(int(time.time() if now is None else now))
    signature = hmac.new(_load_key(create=True),
                         _message(method, path, body, stamp, actor), hashlib.sha256).hexdigest()
    return {"X-Roztash-Actor": actor, "X-Roztash-Time": stamp,
            "X-Roztash-Signature": signature}


def verify_request(method, path, body, headers, *, now=None):
    try:
        lowered = {k.lower(): v for k, v in headers.items()}
        actor = lowered.get("x-roztash-actor", "")
        stamp = lowered.get("x-roztash-time", "")
        signature = lowered.get("x-roztash-signature", "")
        current = time.time() if now is None else now
        if (not actor or actor != actor.strip().lower() or any(c in actor for c in "\r\n")
                or abs(current - int(stamp)) > 300):
            return None
        expected = hmac.new(_load_key(), _message(method, path, body, stamp, actor),
                            hashlib.sha256).hexdigest()
        return actor if hmac.compare_digest(expected, signature) else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None
