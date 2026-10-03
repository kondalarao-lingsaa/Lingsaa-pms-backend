"""Password hashing for the PMS's own login (PBKDF2-SHA256 from Python's standard library).

Only a salted hash is stored ("pbkdf2_sha256$<iterations>$<salt>$<hash>"); the password itself never is.
"""
import base64
import hashlib
import hmac
import re
import secrets

ITERATIONS = 260_000
MIN_LENGTH = 8


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        algorithm, iterations, salt, digest = (stored or "").split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(check, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    """None when the password is strong enough, else what is missing."""
    if len(password or "") < MIN_LENGTH:
        return f"Password must be at least {MIN_LENGTH} characters"
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must have at least one letter and one number"
    if len(password) > 128:
        return "Password must be at most 128 characters"
    return None
