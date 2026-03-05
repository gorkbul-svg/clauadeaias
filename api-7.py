"""
api.py — BIST Araştırma Agent API
Q2 Update: Watchlist, Fiyat Alarmları, Analiz Geçmişi
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os

from anthropic import Anthropic
from data.yahoo_finance import (
    get_stock_price, get_financials,
    get_technical_indicators, get_news_sentiment, compare_sector_peers
)
from data.risk_profili import ORNEK_PROFILLER, PROFIL_PARAMETRELERI, hisse_profile_uygunluk
from agent import TOOLS, execute_tool, SYSTEM_PROMPT, BISTAgent
from database import (
    init_db,
    watchlist_getir, watchlist_ekle, watchlist_sil,
    alarm_ekle, alarm_listesi, alarm_sil,
    analiz_kaydet, analiz_gecmisi_getir, analiz_detay_getir
)

app = FastAPI(title="BIST Araştırma Agent API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    init_db()

aktif_oturumlar: dict[str, BISTAgent] = {}

class ChatRequest(BaseModel):
    soru: str
    oturum_id: str
    kullanici_id: Optional[str] = None

class ChatResponse(BaseModel):
    yanit: str
    oturum_id: str

class WatchlistEkleRequest(BaseModel):
    kullanici_id: int
    ticker: str
    not_metni: Optional[str] = None

class AlarmEkleRequest(BaseModel):
    kullanici_id: int
    ticker: str
    hedef_fiyat: float
    alarm_tipi: str

class PortfolioRequest(BaseModel):
    tickers: list[str]
    kullanici_id: Optional[str] = None

@app.get("/")
def root():
    return {"mesaj": "BIST Araştırma Agent API çalışıyor", "versiyon": "2.0.0"}

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    oturum_id = req.oturum_id
    if oturum_id not in aktif_oturumlar:
        aktif_oturumlar[oturum_id] = BISTAgent(kullanici_id=req.kullanici_id, verbose=False)
    agent = aktif_oturumlar[oturum_id]
    try:
        yanit = agent.sor(req.soru)
        try:
            kullanici_id = int(req.kullanici_id) if req.kullanici_id and req.kullanici_id.isdigit() else None
            ticker = next((t for t in ["THYAO","AKBNK","GARAN","EREGL","BIMAS","MAVI","KCHOL"] if t in req.soru.upper()), None)
            analiz_kaydet(oturum_id=oturum_id, soru=req.soru, yanit=yanit, kullanici_id=kullanici_id, ticker=ticker)
        except Exception:
            pass
        return ChatResponse(yanit=yanit, oturum_id=oturum_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/chat/{oturum_id}")
def oturumu_sifirla(oturum_id: str):
    if oturum_id in aktif_oturumlar:
        aktif_oturumlar[oturum_id].sifirla()
    return {"mesaj": "Oturum sıfırlandı"}

@app.get("/stock/{ticker}")
def hisse_ozet(ticker: str):
    try:
        return {"ticker": ticker.upper(), "fiyat": get_stock_price(ticker), "finansal": get_financials(ticker), "teknik": get_technical_indicators(ticker)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/profiles")
def profilleri_listele():
    return {isim: {"kullanici_id": p.kullanici_id, "ad": p.ad, "risk_toleransi": p.risk_toleransi} for isim, p in ORNEK_PROFILLER.items()}

# ── Watchlist ─────────────────────────────────────────────
@app.get("/watchlist/{kullanici_id}")
def watchlist_al(kullanici_id: int):
    try:
        liste = watchlist_getir(kullanici_id)
        for item in liste:
            try:
                v = get_stock_price(item["ticker"])
                item["guncel_fiyat"] = v.get("fiyat")
                item["degisim_yuzde"] = v.get("degisim_yuzde")
            except Exception:
                item["guncel_fiyat"] = None
                item["degisim_yuzde"] = None
        return {"watchlist": liste, "adet": len(liste)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/watchlist")
def watchlist_hisse_ekle(req: WatchlistEkleRequest):
    try:
        item = watchlist_ekle(req.kullanici_id, req.ticker, req.not_metni)
        return {"mesaj": f"{req.ticker.upper()} eklendi", "item": item}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/watchlist/{kullanici_id}/{ticker}")
def watchlist_hisse_sil(kullanici_id: int, ticker: str):
    if not watchlist_sil(kullanici_id, ticker):
        raise HTTPException(status_code=404, detail="Hisse bulunamadı")
    return {"mesaj": f"{ticker.upper()} silindi"}

# ── Alarmlar ─────────────────────────────────────────────
@app.get("/alarmlar/{kullanici_id}")
def alarmlari_al(kullanici_id: int):
    try:
        alarmlar = alarm_listesi(kullanici_id)
        return {"alarmlar": alarmlar, "adet": len(alarmlar)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/alarmlar")
def alarm_olustur(req: AlarmEkleRequest):
    if req.alarm_tipi not in ("yukari", "asagi"):
        raise HTTPException(status_code=400, detail="alarm_tipi 'yukari' veya 'asagi' olmalı")
    try:
        v = get_stock_price(req.ticker)
        alarm = alarm_ekle(req.kullanici_id, req.ticker, req.hedef_fiyat, req.alarm_tipi)
        yon = "üzerine çıktığında" if req.alarm_tipi == "yukari" else "altına indiğinde"
        return {"mesaj": f"{req.ticker.upper()} {req.hedef_fiyat:.2f} ₺ {yon} bildirim gönderilecek", "guncel_fiyat": v.get("fiyat"), "alarm": alarm}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/alarmlar/{alarm_id}/{kullanici_id}")
def alarm_kaldir(alarm_id: int, kullanici_id: int):
    if not alarm_sil(alarm_id, kullanici_id):
        raise HTTPException(status_code=404, detail="Alarm bulunamadı")
    return {"mesaj": "Alarm silindi"}

# ── Analiz Geçmişi ────────────────────────────────────────
@app.get("/gecmis/{kullanici_id}")
def gecmis_al(kullanici_id: int, limit: int = 20):
    try:
        gecmis = analiz_gecmisi_getir(kullanici_id, limit)
        return {"gecmis": gecmis, "adet": len(gecmis)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/gecmis/{kullanici_id}/{analiz_id}")
def gecmis_detay(kullanici_id: int, analiz_id: int):
    analiz = analiz_detay_getir(analiz_id, kullanici_id)
    if not analiz:
        raise HTTPException(status_code=404, detail="Analiz bulunamadı")
    return analiz

# ── Demo Kullanıcı Endpoint'i ─────────────────────────────
@app.get("/demo/init")
def demo_kullanici_olustur():
    """Demo için varsayılan kullanıcıyı oluştur."""
    from database import get_db
    conn = get_db()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO kullanicilar (id, google_id, email, ad)
            VALUES (1, 'demo_user', 'demo@bist-agent.com', 'Demo Kullanıcı')
        """)
        conn.commit()
        return {"mesaj": "Demo kullanıcı hazır", "kullanici_id": 1}
    finally:
        conn.close()

# ── Google Auth Endpoint'leri ─────────────────────────────
from fastapi.responses import RedirectResponse
from auth import google_auth_url, google_callback, jwt_dogrula

@app.get("/auth/google")
def google_giris():
    """Google OAuth başlat."""
    return RedirectResponse(google_auth_url())

@app.get("/auth/google/callback")
async def google_callback_endpoint(code: str):
    """Google OAuth callback — JWT ile frontend'e yönlendir."""
    result = await google_callback(code)
    token = result["token"]
    kullanici = result["kullanici"]
    frontend = result["frontend_url"]
    # Frontend'e token ve kullanıcı bilgisi ile yönlendir
    return RedirectResponse(
        f"{frontend}/demo.html?token={token}&user_id={kullanici['id']}&name={kullanici['ad']}"
    )

@app.get("/auth/me")
def ben_kimim(authorization: str = None):
    """JWT token ile kullanıcı bilgisi getir."""
    from fastapi import Header
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token gerekli")
    token = authorization.replace("Bearer ", "")
    payload = jwt_dogrula(token)
    from database import kullanici_getir
    kullanici = kullanici_getir(int(payload["sub"]))
    if not kullanici:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    return kullanici

# ── Grafik Endpoint'i ─────────────────────────────────────
@app.get("/stock/{ticker}/history")
def hisse_gecmis(ticker: str, period: str = "3mo"):
    """Hisse geçmiş fiyat verisi — grafik için."""
    from data.yahoo_finance import get_price_history
    try:
        return get_price_history(ticker, period)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Haber & Sentiment Endpoint'i ─────────────────────────
@app.get("/stock/{ticker}/news")
def hisse_haberler(ticker: str, days: int = 7):
    """Hisse haberleri ve sentiment skoru."""
    from data.yahoo_finance import get_news_sentiment
    try:
        return get_news_sentiment(ticker, days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── KAP Endpoint'leri ─────────────────────────────────────
from kap import kap_son_bildirimler, kap_finansal_takvim, kap_sirket_url

@app.get("/kap/{ticker}/bildirimler")
async def kap_bildirimler(ticker: str, limit: int = 10):
    """KAP'tan son bildirimleri getir."""
    try:
        return await kap_son_bildirimler(ticker, limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/kap/{ticker}/takvim")
async def kap_takvim(ticker: str):
    """KAP finansal takvim."""
    try:
        return await kap_finansal_takvim(ticker)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/kap/{ticker}/url")
def kap_url(ticker: str):
    """KAP şirket sayfası URL'i."""
    return {"ticker": ticker.upper(), "url": kap_sirket_url(ticker)}
