"""
auth.py — Google OAuth 2.0
JWT token ile oturum yönetimi
"""

import os
import httpx
import jwt
from datetime import datetime, timedelta
from fastapi import HTTPException
from database import kullanici_bul_veya_olustur

# ── Ortam Değişkenleri ────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
JWT_SECRET           = os.getenv("JWT_SECRET", "bist-agent-secret-key-2026")
FRONTEND_URL         = os.getenv("FRONTEND_URL", "https://gorkbul-svg.github.io/clauadeaias")
BACKEND_URL          = os.getenv("BACKEND_URL", "https://web-production-9272.up.railway.app")

GOOGLE_AUTH_URL      = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL     = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL  = "https://www.googleapis.com/oauth2/v2/userinfo"
REDIRECT_URI         = f"{BACKEND_URL}/auth/google/callback"

# ── JWT ──────────────────────────────────────────────────
def jwt_olustur(kullanici_id: int, email: str) -> str:
    payload = {
        "sub": str(kullanici_id),
        "email": email,
        "exp": datetime.utcnow() + timedelta(days=30)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def jwt_dogrula(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token süresi doldu")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Geçersiz token")

# ── Google OAuth URL ──────────────────────────────────────
def google_auth_url() -> str:
    from urllib.parse import urlencode
    params = {
        "client_id":     GOOGLE_CLIENT_ID.strip(),
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "offline",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

# ── Google Callback ───────────────────────────────────────
async def google_callback(code: str) -> dict:
    """Google'dan gelen code ile token al, kullanıcı bilgilerini getir."""
    async with httpx.AsyncClient() as client:
        # Token al
        token_res = await client.post(GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri":  REDIRECT_URI,
            "grant_type":    "authorization_code",
        })
        token_data = token_res.json()

        if "error" in token_data:
            raise HTTPException(status_code=400, detail=token_data.get("error_description", "OAuth hatası"))

        access_token = token_data["access_token"]

        # Kullanıcı bilgilerini al
        user_res = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        user_info = user_res.json()

    # Kullanıcıyı DB'ye kaydet / güncelle
    kullanici = kullanici_bul_veya_olustur(
        google_id    = user_info["id"],
        email        = user_info["email"],
        ad           = user_info.get("name", ""),
        fotograf_url = user_info.get("picture")
    )

    # JWT oluştur
    token = jwt_olustur(kullanici["id"], kullanici["email"])

    return {
        "token":      token,
        "kullanici":  kullanici,
        "frontend_url": FRONTEND_URL
    }
