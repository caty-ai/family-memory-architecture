#!/usr/bin/env python3
"""Helpers for validating private env files."""

import os
import stat


class PrivateFileError(Exception):
    """Raised when a private env file fails ownership or mode checks."""


def _os_error_text(exc):
    return exc.strerror or str(exc)


def ensure_private_file(path):
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise PrivateFileError(f"cannot inspect env file: {_os_error_text(exc)}") from exc
    if stat.S_ISLNK(st.st_mode):
        raise PrivateFileError("env file is a symlink")
    if not stat.S_ISREG(st.st_mode):
        raise PrivateFileError("env file is not a regular file")
    expected_uid = os.getuid()
    if st.st_uid != expected_uid:
        raise PrivateFileError(f"env file uid is {st.st_uid}, expected {expected_uid}")
    actual = stat.S_IMODE(st.st_mode)
    if actual != 0o600:
        raise PrivateFileError(f"env file mode is {actual:04o}, expected 0600")
