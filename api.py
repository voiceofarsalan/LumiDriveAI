import os, uuid, json
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
TOKEN = os.getenv("TOKEN") or ""

session = requests.Session()
session.headers.update({"Content-Type": "application/json"})

def _auth_header():
    headers = {}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers

def set_token(new_token: str):
    global TOKEN
    TOKEN = new_token or ""

def _idemp_headers():
    return {
        "X-Request-Id": str(uuid.uuid4()),
        "Idempotency-Key": str(uuid.uuid4())
    }

def post(path: str, body: dict, timeout: int = 25):
    url = f"{BASE_URL}{path}"
    headers = {**_auth_header(), **_idemp_headers()}
    print(f"\n🌍 POST {url}\n📦 Payload:", json.dumps(body, indent=2))
    resp = session.post(url, json=body, headers=headers, timeout=timeout)
    print("📥 Response:", resp.status_code)
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text[:1000])
    return resp

def patch(path: str, body: dict | None = None, timeout: int = 25):
    url = f"{BASE_URL}{path}"
    headers = {**_auth_header(), **_idemp_headers()}
    print(f"\n🩹 PATCH {url}")
    if body is not None:
        print("📦 Payload:", json.dumps(body, indent=2))
    resp = session.patch(url, json=body, headers=headers, timeout=timeout)
    print("📥 Response:", resp.status_code)
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text[:1000])
    return resp

def get(path: str, params: dict | None = None, timeout: int = 25):
    url = f"{BASE_URL}{path}"
    headers = _auth_header()
    print(f"\n🔎 GET {url}\n🔍 Params:", params)
    resp = session.get(url, params=params, headers=headers, timeout=timeout)
    print("📥 Response:", resp.status_code)
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text[:1000])
    return resp
