"""Stable paths for mutable state; immutable resources stay in the executable."""
import os
from pathlib import Path


def config_home():
    return Path(os.environ.get('ROZTASH_CONFIG_HOME') or os.path.expanduser('~/.config/roztash'))


def config_file(name):
    custom = os.environ.get('ROZTASH_CONFIG_HOME')
    return Path(custom) / name if custom else Path(os.path.expanduser('~/.config/roztash/' + name))
