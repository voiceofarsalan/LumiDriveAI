import os
from urllib.parse import quote
from dotenv import load_dotenv
from api import get, post, set_token

load_dotenv()

PHONE_CHECK_PATH   = os.getenv("PHONE_CHECK_PATH")       # /api/v1/auth/phone/check/{phone}
SIGNUP_FIRST_PATH  = os.getenv("SIGNUP_FIRST_PATH")      # /api/v1/auth/signup/first-step
SIGNUP_FINAL_PATH  = os.getenv("SIGNUP_FINAL_PATH")      # /api/v1/auth/signup/final-step

OTP_TYPE                 = os.getenv("OTP_TYPE", "sms")
USER_TYPE_ID             = os.getenv("USER_TYPE_ID", "")
DEFAULT_DEVICE_PUSH_TOKEN= os.getenv("DEFAULT_DEVICE_PUSH_TOKEN", "web-dev-dummy")

def phone_check(phone: str):
    path = PHONE_CHECK_PATH.replace("{phone}", quote(phone, safe=""))
    resp = get(path)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    return {"status": resp.status_code, "data": data}

def signup_first_step(phone: str, otp_type: str = OTP_TYPE):
    body = {"phone": phone, "otp_type": otp_type}
    return post(SIGNUP_FIRST_PATH, body)

def signup_final_step(sentOtp: str, name: str, phone: str, device_push_token: str = DEFAULT_DEVICE_PUSH_TOKEN, user_type_id: str = USER_TYPE_ID):
    body = {
        "sentOtp": sentOtp,
        "name": name,
        "phone": phone,
        "device_push_token": device_push_token,
        "user_type_id": user_type_id
    }
    resp = post(SIGNUP_FINAL_PATH, body)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}
    token = (data.get("accessToken")
             or data.get("access_token")
             or data.get("token")
             or data.get("data", {}).get("accessToken"))
    if resp.ok and token:
        set_token(token)
    return {"status": resp.status_code, "data": data, "token": token}

def ensure_token_via_signup_or_manual(phone: str):
    # 1) Check if phone exists
    chk = phone_check(phone)
    exists = False
    if chk["status"] == 200 and isinstance(chk["data"], dict):
        exists = bool(chk["data"].get("exists"))

    if not exists:
        # 2) Signup first-step -> send OTP
        r1 = signup_first_step(phone)
        if r1.status_code not in (200, 201):
            return {"ok": False, "error": "signup_first_step failed", "resp": r1.text}

        print("📲 OTP sent. Enter the OTP you received:")
        otp = input("OTP: ").strip()
        name = input("Your name (for account profile): ").strip() or "Lumi User"

        # 3) Signup final-step -> returns accessToken
        r2 = signup_final_step(sentOtp=otp, name=name, phone=phone)
        if r2.get("token"):
            return {"ok": True, "token": r2["token"], "created": True}
        return {"ok": False, "error": "signup_final_step failed", "resp": r2}

    # If user already exists but we don't have a working login flow here,
    # ask user to paste an existing JWT for now (or you can provide a login endpoint later).
    print("ℹ️ Phone exists. If you have a JWT, paste it now to proceed, else Ctrl+C and obtain one from the app.")
    pasted = input("Paste JWT (or leave blank): ").strip()
    if pasted and len(pasted.split(".")) == 3:
        set_token(pasted)
        return {"ok": True, "token": pasted, "created": False}

    return {"ok": False, "error": "User exists but no JWT provided. Add login flow or paste token."}
