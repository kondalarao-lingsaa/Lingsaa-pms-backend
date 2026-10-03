import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jose import jwt  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import decode_token  # noqa: E402

claims = {
    "sub": "123",
    "client_id": "client-abc",
    "role": "projectManager",
    "is_superadmin": False,
    "exp": datetime.now(timezone.utc) + timedelta(minutes=5)
}

token = jwt.encode(claims, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
print(f"Encoded a test token using JWT_SECRET (algorithm={settings.JWT_ALGORITHM}).")

decoded = decode_token(token)
print(f"Decoded successfully: {decoded}")

assert decoded["client_id"] == "client-abc"
print("Round-trip OK: security.decode_token() works correctly with this secret/algorithm.")
