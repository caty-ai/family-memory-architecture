"""Small crash-safe helpers for writing script state files."""

import json
import os
import tempfile


def atomic_write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        tmp_name = handle.name
        try:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
            umask = os.umask(0)
            os.umask(umask)
            os.fchmod(handle.fileno(), 0o666 & ~umask)
        except BaseException:
            os.unlink(tmp_name)
            raise
    replaced = False
    try:
        os.replace(tmp_name, path)
        replaced = True
    finally:
        if not replaced and os.path.exists(tmp_name):
            os.unlink(tmp_name)
    dirfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def atomic_write_json(path, obj, indent=2, sort_keys=True):
    atomic_write_text(path, json.dumps(obj, indent=indent, sort_keys=sort_keys) + "\n")
