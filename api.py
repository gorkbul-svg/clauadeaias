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

# ── Tam Analiz (Sektör için) ──────────────────────────────
@app.get("/stock/{ticker}/full")
def hisse_tam_analiz(ticker: str):
    """Tüm verileri tek seferde döndürür — sektör karşılaştırma için."""
    try:
        return {
            "fiyat":    get_stock_price(ticker),
            "finansal": get_financials(ticker),
            "teknik":   get_technical_indicators(ticker),
            "haberler": get_news_sentiment(ticker),
            "sektor":   compare_sector_peers(ticker)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Freemium & Kullanım ───────────────────────────────────
from database import (
    kullanim_kontrol, kullanim_artir, plan_guncelle,
    api_anahtar_olustur, api_anahtar_dogrula, api_anahtarlari_listele
)

@app.get("/kullanim/{kullanici_id}")
def kullanim_durumu(kullanici_id: int):
    """Kullanıcının plan ve kullanım durumunu getir."""
    try:
        return kullanim_kontrol(kullanici_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── İyzico Ödeme ──────────────────────────────────────────
import os, hashlib, hmac

IYZICO_API_KEY    = os.getenv("IYZICO_API_KEY", "")
IYZICO_SECRET_KEY = os.getenv("IYZICO_SECRET_KEY", "")
IYZICO_BASE_URL   = os.getenv("IYZICO_BASE_URL", "https://sandbox-api.iyzipay.com")

class OdemeRequest(BaseModel):
    kullanici_id: int
    plan: str = "premium"
    kart_no: str
    son_kullanma_ay: str
    son_kullanma_yil: str
    cvv: str
    kart_sahibi: str
    email: str

@app.post("/odeme/baslat")
async def odeme_baslat(req: OdemeRequest):
    """İyzico ile ödeme başlat."""
    import httpx, json, time, base64

    if not IYZICO_API_KEY:
        # Sandbox modu — gerçek ödeme yok
        plan_guncelle(req.kullanici_id, req.plan, "sandbox_token")
        return {
            "durum": "basarili",
            "mesaj": "Sandbox mod — gerçek ödeme alınmadı",
            "plan": req.plan,
            "kullanici_id": req.kullanici_id
        }

    try:
        # İyzico ödeme isteği
        payload = {
            "locale": "tr",
            "conversationId": f"bist_{req.kullanici_id}_{int(time.time())}",
            "price": "99.90",
            "paidPrice": "99.90",
            "currency": "TRY",
            "installment": "1",
            "basketId": f"premium_{req.kullanici_id}",
            "paymentChannel": "WEB",
            "paymentGroup": "SUBSCRIPTION",
            "paymentCard": {
                "cardHolderName": req.kart_sahibi,
                "cardNumber": req.kart_no,
                "expireMonth": req.son_kullanma_ay,
                "expireYear": req.son_kullanma_yil,
                "cvc": req.cvv,
                "registerCard": "0"
            },
            "buyer": {
                "id": str(req.kullanici_id),
                "name": req.kart_sahibi.split()[0],
                "surname": req.kart_sahibi.split()[-1] if len(req.kart_sahibi.split()) > 1 else "",
                "email": req.email,
                "identityNumber": "11111111111",
                "ip": "85.34.78.112",
                "registrationAddress": "Türkiye",
                "city": "Istanbul",
                "country": "Turkey"
            },
            "shippingAddress": {"address": "Türkiye", "city": "Istanbul", "country": "Turkey", "contactName": req.kart_sahibi},
            "billingAddress": {"address": "Türkiye", "city": "Istanbul", "country": "Turkey", "contactName": req.kart_sahibi},
            "basketItems": [{
                "id": "premium_plan",
                "name": "BIST Agent Premium - Aylık",
                "category1": "Yazılım",
                "itemType": "VIRTUAL",
                "price": "99.90"
            }]
        }

        auth = base64.b64encode(f"{IYZICO_API_KEY}:{IYZICO_SECRET_KEY}".encode()).decode()
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{IYZICO_BASE_URL}/payment/auth",
                json=payload,
                headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
            )
            data = res.json()

        if data.get("status") == "success":
            plan_guncelle(req.kullanici_id, req.plan, data.get("token"))
            return {"durum": "basarili", "plan": req.plan, "mesaj": "Premium üyelik aktifleştirildi"}
        else:
            raise HTTPException(status_code=400, detail=data.get("errorMessage", "Ödeme başarısız"))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/odeme/planlar")
def plan_listesi():
    """Mevcut planları listele."""
    return {
        "planlar": [
            {
                "id": "ucretsiz",
                "ad": "Ücretsiz",
                "fiyat": 0,
                "limit": 5,
                "ozellikler": ["Ayda 5 analiz", "Watchlist (10 hisse)", "Temel teknik analiz"]
            },
            {
                "id": "premium",
                "ad": "Premium",
                "fiyat": 99.90,
                "limit": -1,
                "ozellikler": ["Sınırsız analiz", "Sınırsız watchlist", "Gelişmiş analiz", "Haftalık rapor", "E-posta alarmı"]
            },
            {
                "id": "kurumsal",
                "ad": "Kurumsal",
                "fiyat": 499.90,
                "limit": -1,
                "ozellikler": ["Premium + API erişimi", "Çoklu kullanıcı", "Özel entegrasyon", "Destek"]
            }
        ]
    }

# ── API Anahtar Yönetimi ──────────────────────────────────
@app.get("/api-anahtarlar/{kullanici_id}")
def anahtarlari_listele(kullanici_id: int):
    try:
        return {"anahtarlar": api_anahtarlari_listele(kullanici_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api-anahtarlar/{kullanici_id}")
def anahtar_olustur(kullanici_id: int, isim: str = "Varsayılan"):
    try:
        return api_anahtar_olustur(kullanici_id, isim)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Fiyat Tahmini ─────────────────────────────────────────
@app.get("/stock/{ticker}/tahmin")
async def fiyat_tahmini(ticker: str, gun: int = 7):
    """Ensemble ML ile 7 günlük fiyat tahmini."""
    from fastapi.concurrency import run_in_threadpool
    try:
        from tahmin import ensemble_tahmin
        sonuc = await run_in_threadpool(ensemble_tahmin, ticker, gun)
        return sonuc
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Sosyal Özellikler ─────────────────────────────────────
from database import (
    sosyal_tablolari_olustur,
    paylasim_olustur, feed_getir, ticker_feed_getir,
    takip_et, takibi_birak, begeni_toggle,
    yorum_ekle, yorumlari_getir, profil_getir
)

@app.on_event("startup")
def sosyal_startup():
    sosyal_tablolari_olustur()

class PaylasimRequest(BaseModel):
    kullanici_id: int
    ticker: str
    yorum: str
    hedef_fiyat: Optional[float] = None
    yon: Optional[str] = None

class YorumRequest(BaseModel):
    kullanici_id: int
    yorum: str

# Feed
@app.get("/feed")
def genel_feed(limit: int = 20):
    return {"feed": feed_getir(None, limit)}

@app.get("/feed/{kullanici_id}")
def kisisel_feed(kullanici_id: int, limit: int = 20):
    return {"feed": feed_getir(kullanici_id, limit)}

@app.get("/feed/ticker/{ticker}")
def ticker_feed(ticker: str, limit: int = 20):
    return {"feed": ticker_feed_getir(ticker, limit)}

# Paylaşım
@app.post("/paylasim")
def paylasim_yap(req: PaylasimRequest):
    try:
        p = paylasim_olustur(req.kullanici_id, req.ticker, req.yorum, req.hedef_fiyat, req.yon)
        return {"mesaj": "Analiz paylaşıldı", "paylasim": p}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Beğeni
@app.post("/paylasim/{paylasim_id}/begeni/{kullanici_id}")
def begeni(paylasim_id: int, kullanici_id: int):
    try:
        return begeni_toggle(kullanici_id, paylasim_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Yorum
@app.get("/paylasim/{paylasim_id}/yorumlar")
def yorumlari_al(paylasim_id: int):
    return {"yorumlar": yorumlari_getir(paylasim_id)}

@app.post("/paylasim/{paylasim_id}/yorum")
def yorum_yap(paylasim_id: int, req: YorumRequest):
    try:
        y = yorum_ekle(req.kullanici_id, paylasim_id, req.yorum)
        return {"mesaj": "Yorum eklendi", "yorum": y}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Takip
@app.post("/takip/{takip_edilen_id}/{takip_eden_id}")
def takip(takip_edilen_id: int, takip_eden_id: int):
    takip_et(takip_eden_id, takip_edilen_id)
    return {"mesaj": "Takip edildi"}

@app.delete("/takip/{takip_edilen_id}/{takip_eden_id}")
def takip_kaldir(takip_edilen_id: int, takip_eden_id: int):
    takibi_birak(takip_eden_id, takip_edilen_id)
    return {"mesaj": "Takip bırakıldı"}

# Profil
@app.get("/profil/{kullanici_id}")
def profil(kullanici_id: int, izleyen_id: int = None):
    p = profil_getir(kullanici_id, izleyen_id)
    if not p:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    return p
