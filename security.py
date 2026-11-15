"""Small standard-library security helpers for Cue's single-user deployment."""

import base64
import hashlib
import hmac
import secrets

_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 64
_MAXMEM = 64 * 1024 * 1024


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    """Return a salted scrypt password hash suitable for an environment variable."""
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a non-empty string.")
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_BYTES,
        maxmem=_MAXMEM,
    )
    return "$".join(
        (
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            _b64encode(salt),
            _b64encode(derived),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password hash; reject unknown parameters before doing expensive work."""
    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    try:
        algorithm, n_text, r_text, p_text, salt_text, digest_text = encoded.split("$")
        if (algorithm, int(n_text), int(r_text), int(p_text)) != (
            "scrypt",
            _SCRYPT_N,
            _SCRYPT_R,
            _SCRYPT_P,
        ):
            return False
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
        if len(salt) != _SALT_BYTES or len(expected) != _KEY_BYTES:
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=_SCRYPT_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
            dklen=_KEY_BYTES,
            maxmem=_MAXMEM,
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def constant_time_equal(expected: str, provided: str | None) -> bool:
    """Compare non-empty secret strings without leaking a content-dependent timing signal."""
    return (
        isinstance(expected, str)
        and bool(expected)
        and isinstance(provided, str)
        and hmac.compare_digest(expected, provided)
    )
