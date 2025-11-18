# jwt_utils.py
import base64
import json
from typing import Optional, Dict

def _b64url_decode(b: str) -> bytes:
    # Add padding for base64url
    pad = '=' * (-len(b) % 4)
    return base64.urlsafe_b64decode(b + pad)

def parse_jwt_unverified(token: str) -> Dict:
    """
    Parse a JWT without verifying signature to extract payload.
    Returns {} if parsing fails.
    """
    if not token or token.count('.') != 2:
        return {}
    header_b64, payload_b64, _sig = token.split('.')
    try:
        payload = json.loads(_b64url_decode(payload_b64).decode('utf-8'))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}

def get_user_id_from_jwt(token: str) -> Optional[str]:
    payload = parse_jwt_unverified(token)
    # your backend uses {"id": "<uuid>", "tokenVersion": ..., "iat":..., "exp":...}
    uid = payload.get("id")
    if isinstance(uid, str) and len(uid) >= 10:
        return uid
    return None
