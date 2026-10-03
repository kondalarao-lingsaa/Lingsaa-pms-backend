"""Field rules shared by every PMS form. They mirror the frontend rules (src/pms/utils/validation.js),
which follow the Add Customer form in Lingsaa_Accounts: never trust the browser alone."""
import re
from typing import Optional

MOBILE_REGEX = re.compile(r"^[6-9]\d{9}$")
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
PERSON_NAME_REGEX = re.compile(r"^[A-Za-z][A-Za-z .'-]*$")
TITLE_REGEX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,&'()/:+#_-]*$")
LABEL_REGEX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]*$")
# Same patterns as the Add Customer form in Lingsaa_Accounts.
GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")
PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def clean(value: Optional[str]) -> Optional[str]:
    """Trim, collapse inner runs of spaces, and turn an empty string into None."""
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def capitalize_first(value: Optional[str]) -> Optional[str]:
    value = clean(value)
    return value[0].upper() + value[1:] if value else value


def capitalize_words(value: Optional[str]) -> Optional[str]:
    """Upper-case the first letter of every word without touching the rest (keeps HR, iOS, API)."""
    value = clean(value)
    return " ".join(w[0].upper() + w[1:] for w in value.split(" ")) if value else value


def person_name(value: Optional[str]) -> Optional[str]:
    value = clean(value)
    if value is None:
        return None
    if not PERSON_NAME_REGEX.match(value):
        raise ValueError("Name should contain only letters, no numbers")
    return " ".join(w[0].upper() + w[1:].lower() if w.islower() or w.isupper() else w for w in value.split(" "))


def title_text(value: Optional[str], label: str, *, required=False, min_len=3, words=True) -> Optional[str]:
    value = capitalize_words(value) if words else capitalize_first(value)
    if value is None:
        if required:
            raise ValueError(f"{label} is required")
        return None
    if len(value) < min_len:
        raise ValueError(f"{label} must be at least {min_len} characters")
    if not re.search(r"[A-Za-z]", value) or not TITLE_REGEX.match(value):
        raise ValueError(f"{label} must contain letters and only common symbols (. , & ( ) - / : + #)")
    return value


def tax_id(value: Optional[str]) -> Optional[str]:
    """GSTIN / PAN are stored upper-case with no spaces."""
    value = clean(value)
    return value.replace(" ", "").upper() if value else value


def gstin(value: Optional[str]) -> Optional[str]:
    value = tax_id(value)
    if value and not GSTIN_REGEX.match(value):
        raise ValueError("Enter a valid 15-character GSTIN (e.g. 22AAAAA0000A1Z5)")
    return value


def pan(value: Optional[str]) -> Optional[str]:
    value = tax_id(value)
    if value and not PAN_REGEX.match(value):
        raise ValueError("Enter a valid 10-character PAN (e.g. ABCDE1234F)")
    return value


def utc_iso(value) -> Optional[str]:
    """Timestamps come from SQL Server's clock, which runs in UTC; mark them as UTC ("Z") so browsers
    in any timezone show the right local time instead of treating them as local."""
    if value is None:
        return None
    text = value.isoformat()
    return text if value.tzinfo else f"{text}Z"
