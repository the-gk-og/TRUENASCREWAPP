"""services/auth_service.py — Password, TOTP, and backup code helpers."""
import secrets
import string
from werkzeug.security import check_password_hash, generate_password_hash


def generate_backup_codes(count: int = 10) -> list[str]:
    """Generate *count* backup codes formatted as XXXX-XXXX."""
    codes = []
    for _ in range(count):
        raw = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def hash_backup_codes(codes: list[str]) -> list[str]:
    """Hash backup codes for safe storage."""
    return [generate_password_hash(c.replace('-', '')) for c in codes]


def verify_backup_code(stored_hashes: list[str], provided_code: str):
    """
    Verify *provided_code* against *stored_hashes*.
    Returns the index of the matched hash (so the caller can remove it), or None.
    """
    provided_code = provided_code.replace('-', '').strip().upper()
    for i, hashed in enumerate(stored_hashes):
        if check_password_hash(hashed, provided_code):
            return i
    return None
