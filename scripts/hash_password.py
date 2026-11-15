#!/usr/bin/env python3
"""Generate a password hash for CUE_PASSWORD_HASH without echoing the password."""

import getpass
import sys

from security import hash_password


def main():
    password = getpass.getpass("Cue password (minimum 16 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 16:
        print("Use at least 16 characters.", file=sys.stderr)
        return 1
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    print(hash_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
