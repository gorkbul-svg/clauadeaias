"""
api.py — BIST Araştırma Agent API
Q2 Update: Watchlist, Fiyat Alarmları, Analiz Geçmişi
"""

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
import threading, uuid, time
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

# ── Background Job Store ──────────────────────────────────
_jobs: dict = {}

def job_baslat(job_id: str, fn, *args):
    _jobs[job_id] = {"durum": "calisıyor", "sonuc": None, "hata": None, "baslangic": time.time()}
    def _calistir():
        try:
            _jobs[job_id]["sonuc"] = fn(*args)
            _jobs[job_id]["durum"] = "tamam"
        except Exception as e:
            _jobs[job_id]["hata"]  = str(e)
            _jobs[job_id]["durum"] = "hata"
    t = threading.Thread(target=_calistir, daemon=True)
    t.start()
    return job_id

@app.get("/job/{job_id}")
def job_durum(job_id: str):
    if job_id not in _jobs:
        return {"job_id": job_id, "durum": "calisıyor", "sonuc": None, "hata": None, "sure": 0}
    j = _jobs[job_id]
    return {
        "job_id": job_id,
        "durum":  j["durum"],
        "sonuc":  j["sonuc"] if j["durum"] == "tamam" else None,
        "hata":   j["hata"],
        "sure":   round(time.time() - j["baslangic"], 1),
    }

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

# ── Whitelist ─────────────────────────────────────────────
# İzin verilen email adresleri — buraya ekle/çıkar
IZIN_VERILEN_EMAILLER = {
    "gorkbul@gmail.com",
}

# True → whitelist aktif, False → herkese açık
WHITELIST_AKTIF = True

def email_izinli_mi(email: str) -> bool:
    if not WHITELIST_AKTIF:
        return True
    return email.lower() in {e.lower() for e in IZIN_VERILEN_EMAILLER}

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

    # Whitelist kontrolü
    email = kullanici.get("email", "")
    if not email_izinli_mi(email):
        # Erken erişim sayfasına yönlendir
        return RedirectResponse(
            f"{frontend}/demo.html?erisim=beklemede&email={email}"
        )

    # Frontend'e token ve kullanıcı bilgisi ile yönlendir
    return RedirectResponse(
        f"{frontend}/demo.html?token={token}&user_id={kullanici['id']}&name={kullanici['ad']}"
    )

@app.get("/auth/whitelist-kontrol")
def whitelist_kontrol(email: str):
    """Email whitelist'te mi kontrol et."""
    return {
        "izinli":          email_izinli_mi(email),
        "whitelist_aktif": WHITELIST_AKTIF,
    }

@app.post("/auth/bekleme-listesi")
async def bekleme_listesine_ekle(req: Request):
    """Erken erişim için bekleme listesine ekle."""
    data  = await req.json()
    email = data.get("email", "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Geçersiz email")
    # DB'ye kaydet
    from database import db_baglanti
    with db_baglanti() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bekleme_listesi
            (id INTEGER PRIMARY KEY, email TEXT UNIQUE, tarih TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
        """)
        try:
            conn.execute("INSERT INTO bekleme_listesi (email) VALUES (?)", (email,))
            conn.commit()
            return {"mesaj": "Bekleme listesine eklendi", "email": email}
        except Exception:
            return {"mesaj": "Bu email zaten listede", "email": email}

@app.get("/auth/bekleme-listesi")
def bekleme_listesini_goster():
    """Bekleme listesindeki tüm emailler (admin)."""
    from database import db_baglanti
    try:
        with db_baglanti() as conn:
            rows = conn.execute(
                "SELECT email, tarih FROM bekleme_listesi ORDER BY tarih"
            ).fetchall()
            return {"liste": [{"email": r[0], "tarih": r[1]} for r in rows], "toplam": len(rows)}
    except Exception:
        return {"liste": [], "toplam": 0}

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

# ── Karar Paneli ──────────────────────────────────────────
@app.get("/stock/{ticker}/karar")
async def karar_paneli(ticker: str):
    """
    Teknik + Temel + ML + Topluluk verilerini birleştirip
    AL / SAT / BEKLE skoru üretir.
    """
    from fastapi.concurrency import run_in_threadpool
    from database import ticker_feed_getir

    ticker = ticker.upper()

    # 1. Tüm verileri topla
    try: fiyat    = get_stock_price(ticker)
    except: fiyat = {}
    try: teknik   = get_technical_indicators(ticker)
    except: teknik = {}
    try: finansal = get_financials(ticker)
    except: finansal = {}

    # 2. Teknik skor (0-100)
    teknik_skor = 50
    teknik_sinyaller = []
    rsi = teknik.get("RSI_14", 50)
    if rsi < 30:
        teknik_skor += 20
        teknik_sinyaller.append({"sinyal": "RSI Aşırı Satım", "yon": "al", "agirlik": "yüksek"})
    elif rsi > 70:
        teknik_skor -= 20
        teknik_sinyaller.append({"sinyal": "RSI Aşırı Alım", "yon": "sat", "agirlik": "yüksek"})
    else:
        teknik_sinyaller.append({"sinyal": f"RSI Nötr ({rsi:.0f})", "yon": "bekle", "agirlik": "orta"})

    macd = teknik.get("MACD", 0)
    macd_signal = teknik.get("MACD_signal", 0)
    if macd and macd_signal:
        if macd > macd_signal:
            teknik_skor += 15
            teknik_sinyaller.append({"sinyal": "MACD Yükseliş Kesişimi", "yon": "al", "agirlik": "yüksek"})
        else:
            teknik_skor -= 15
            teknik_sinyaller.append({"sinyal": "MACD Düşüş Kesişimi", "yon": "sat", "agirlik": "yüksek"})

    trend = teknik.get("trend", "")
    if "yükseliş" in trend.lower():
        teknik_skor += 10
        teknik_sinyaller.append({"sinyal": "Yükseliş Trendi", "yon": "al", "agirlik": "orta"})
    elif "düşüş" in trend.lower():
        teknik_skor -= 10
        teknik_sinyaller.append({"sinyal": "Düşüş Trendi", "yon": "sat", "agirlik": "orta"})

    teknik_skor = max(0, min(100, teknik_skor))

    # 3. Temel skor (0-100)
    temel_skor = 50
    temel_sinyaller = []
    fk = finansal.get("FK_orani", 0)
    if fk and fk > 0:
        if fk < 10:
            temel_skor += 20
            temel_sinyaller.append({"sinyal": f"Düşük F/K ({fk:.1f})", "yon": "al", "agirlik": "yüksek"})
        elif fk > 25:
            temel_skor -= 15
            temel_sinyaller.append({"sinyal": f"Yüksek F/K ({fk:.1f})", "yon": "sat", "agirlik": "orta"})
        else:
            temel_sinyaller.append({"sinyal": f"F/K Makul ({fk:.1f})", "yon": "bekle", "agirlik": "düşük"})

    roe = finansal.get("ROE_yuzde", 0)
    if roe > 20:
        temel_skor += 15
        temel_sinyaller.append({"sinyal": f"Güçlü ROE (%{roe:.1f})", "yon": "al", "agirlik": "yüksek"})
    elif roe < 5:
        temel_skor -= 10
        temel_sinyaller.append({"sinyal": f"Zayıf ROE (%{roe:.1f})", "yon": "sat", "agirlik": "orta"})

    pd_dd = finansal.get("PD_DD", 0)
    if pd_dd and 0 < pd_dd < 1.5:
        temel_skor += 10
        temel_sinyaller.append({"sinyal": f"Düşük PD/DD ({pd_dd:.2f})", "yon": "al", "agirlik": "orta"})

    temel_skor = max(0, min(100, temel_skor))

    # 4. ML tahmini skoru (0-100)
    ml_skor = 50
    ml_ozet = {}
    try:
        from tahmin import ensemble_tahmin
        ml = await run_in_threadpool(ensemble_tahmin, ticker, 7)
        degisim = ml.get("degisim_yuzde", 0)
        if degisim > 3:
            ml_skor = 75
        elif degisim > 0:
            ml_skor = 60
        elif degisim > -3:
            ml_skor = 40
        else:
            ml_skor = 25
        ml_ozet = {
            "7_gun_hedef": ml.get("7_gun_hedef"),
            "degisim_yuzde": degisim,
            "guven_skoru": ml.get("guven_skoru"),
            "yon": ml.get("yon")
        }
    except:
        ml_ozet = {"hata": "ML tahmini alınamadı"}

    # 5. Topluluk skoru (0-100)
    topluluk_skor = 50
    topluluk_ozet = {}
    try:
        paylasimlar = ticker_feed_getir(ticker, 20)
        al_sayisi   = sum(1 for p in paylasimlar if p.get("yon") == "al")
        sat_sayisi  = sum(1 for p in paylasimlar if p.get("yon") == "sat")
        bekle_sayisi = sum(1 for p in paylasimlar if p.get("yon") == "bekle")
        toplam = len(paylasimlar)
        if toplam > 0:
            topluluk_skor = 50 + int((al_sayisi - sat_sayisi) / toplam * 50)
        topluluk_ozet = {
            "toplam_analiz": toplam,
            "al": al_sayisi,
            "sat": sat_sayisi,
            "bekle": bekle_sayisi
        }
    except:
        topluluk_ozet = {"toplam_analiz": 0}

    # 6. Ensemble karar skoru
    # Ağırlıklar: Teknik %35, Temel %30, ML %25, Topluluk %10
    genel_skor = round(
        teknik_skor  * 0.35 +
        temel_skor   * 0.30 +
        ml_skor      * 0.25 +
        topluluk_skor * 0.10
    )

    if genel_skor >= 62:
        karar = "AL"
        karar_renk = "yesil"
        karar_aciklama = "Teknik, temel ve ML göstergeleri yükseliş sinyali veriyor."
    elif genel_skor <= 38:
        karar = "SAT"
        karar_renk = "kirmizi"
        karar_aciklama = "Birden fazla gösterge düşüş baskısına işaret ediyor."
    else:
        karar = "BEKLE"
        karar_renk = "sari"
        karar_aciklama = "Göstergeler karışık sinyal veriyor, net yön oluşmadı."

    return {
        "ticker": ticker,
        "son_fiyat": fiyat.get("fiyat", 0),
        "sirket": fiyat.get("sirket", ticker),
        "karar": karar,
        "karar_renk": karar_renk,
        "karar_aciklama": karar_aciklama,
        "genel_skor": genel_skor,
        "skorlar": {
            "teknik": teknik_skor,
            "temel": temel_skor,
            "ml": ml_skor,
            "topluluk": topluluk_skor
        },
        "teknik_sinyaller": teknik_sinyaller,
        "temel_sinyaller": temel_sinyaller,
        "ml_ozet": ml_ozet,
        "topluluk_ozet": topluluk_ozet,
        "uyari": "Bu analiz yatırım tavsiyesi değildir."
    }

# ── WebSocket Canlı Alarm ─────────────────────────────────
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Set
import asyncio, json

# Bağlı kullanıcılar: {kullanici_id: set(websocket)}
ws_baglantilari: Dict[int, Set[WebSocket]] = {}

@app.websocket("/ws/alarmlar/{kullanici_id}")
async def websocket_alarmlar(ws: WebSocket, kullanici_id: int):
    await ws.accept()
    if kullanici_id not in ws_baglantilari:
        ws_baglantilari[kullanici_id] = set()
    ws_baglantilari[kullanici_id].add(ws)
    print(f"[WS] Kullanıcı {kullanici_id} bağlandı. Toplam: {sum(len(v) for v in ws_baglantilari.values())}")
    try:
        while True:
            await asyncio.sleep(30)
            await ws.send_json({"tip": "ping"})
    except WebSocketDisconnect:
        ws_baglantilari[kullanici_id].discard(ws)
        print(f"[WS] Kullanıcı {kullanici_id} ayrıldı")

async def ws_bildirim_gonder(kullanici_id: int, mesaj: dict):
    """Kullanıcıya WebSocket bildirimi gönder."""
    if kullanici_id not in ws_baglantilari:
        return
    kopuk = set()
    for ws in ws_baglantilari[kullanici_id]:
        try:
            await ws.send_json(mesaj)
        except:
            kopuk.add(ws)
    ws_baglantilari[kullanici_id] -= kopuk

# ── Gelişmiş Alarm Kontrolü ───────────────────────────────
async def gelismis_alarm_kontrol():
    """
    Her 60 saniyede tüm aktif alarmları kontrol eder.
    4 alarm türü: hedef fiyat, RSI, %5 hareket, MACD
    """
    import yfinance as yf
    from database import get_db

    while True:
        await asyncio.sleep(60)
        try:
            conn = get_db()
            alarmlar = conn.execute("""
                SELECT a.*, k.email, k.ad
                FROM alarmlar a
                JOIN kullanicilar k ON a.kullanici_id = k.id
                WHERE a.aktif = 1
            """).fetchall()
            conn.close()

            # Ticker'ları grupla (tek API çağrısı)
            ticker_gruplari: Dict[str, list] = {}
            for alarm in alarmlar:
                t = alarm["ticker"]
                ticker_gruplari.setdefault(t, []).append(dict(alarm))

            for ticker, ticker_alarmlari in ticker_gruplari.items():
                try:
                    stock  = yf.Ticker(ticker + ".IS")
                    df     = stock.history(period="2d", interval="1m")
                    if df.empty:
                        continue

                    fiyat  = float(df["Close"].iloc[-1])
                    hacim  = float(df["Volume"].iloc[-1])

                    # RSI hesapla
                    close  = df["Close"]
                    delta  = close.diff()
                    gain   = delta.clip(lower=0).rolling(14).mean()
                    loss   = (-delta.clip(upper=0)).rolling(14).mean()
                    rs     = gain / loss
                    rsi    = float(100 - (100 / (1 + rs.iloc[-1])))

                    # MACD
                    ema12  = close.ewm(span=12).mean()
                    ema26  = close.ewm(span=26).mean()
                    macd   = ema12 - ema26
                    signal = macd.ewm(span=9).mean()
                    macd_son    = float(macd.iloc[-1])
                    macd_onceki = float(macd.iloc[-2]) if len(macd) > 1 else macd_son
                    signal_son    = float(signal.iloc[-1])
                    signal_onceki = float(signal.iloc[-2]) if len(signal) > 1 else signal_son

                    # %5 hareket (son 1 saatte)
                    if len(df) > 60:
                        fiyat_1s_once = float(df["Close"].iloc[-60])
                        degisim_pct = (fiyat - fiyat_1s_once) / fiyat_1s_once * 100
                    else:
                        degisim_pct = 0

                    for alarm in ticker_alarmlari:
                        bildirimler = []

                        # 1. Hedef fiyat
                        if alarm.get("hedef_fiyat"):
                            hedef = float(alarm["hedef_fiyat"])
                            tip   = alarm.get("alarm_tipi", "yukari")
                            if tip == "yukari" and fiyat >= hedef:
                                bildirimler.append({
                                    "tip": "hedef_fiyat",
                                    "baslik": f"🎯 {ticker} Hedef Fiyata Ulaştı!",
                                    "mesaj": f"{ticker} {fiyat:.2f}₺ → Hedef: {hedef:.2f}₺",
                                    "renk": "yesil"
                                })
                            elif tip == "asagi" and fiyat <= hedef:
                                bildirimler.append({
                                    "tip": "hedef_fiyat",
                                    "baslik": f"⚠️ {ticker} Hedef Fiyata Düştü!",
                                    "mesaj": f"{ticker} {fiyat:.2f}₺ → Hedef: {hedef:.2f}₺",
                                    "renk": "kirmizi"
                                })

                        # 2. RSI aşırı bölge
                        if rsi > 70:
                            bildirimler.append({
                                "tip": "rsi",
                                "baslik": f"📈 {ticker} RSI Aşırı Alım!",
                                "mesaj": f"RSI: {rsi:.0f} — Satış baskısı oluşabilir",
                                "renk": "turuncu"
                            })
                        elif rsi < 30:
                            bildirimler.append({
                                "tip": "rsi",
                                "baslik": f"📉 {ticker} RSI Aşırı Satım!",
                                "mesaj": f"RSI: {rsi:.0f} — Alım fırsatı oluşabilir",
                                "renk": "mavi"
                            })

                        # 3. %5 ani hareket
                        if abs(degisim_pct) >= 5:
                            yon = "🚀 Yükseldi" if degisim_pct > 0 else "💥 Düştü"
                            bildirimler.append({
                                "tip": "ani_hareket",
                                "baslik": f"{yon} {ticker} %{abs(degisim_pct):.1f}!",
                                "mesaj": f"Son 1 saatte ani hareket: {degisim_pct:+.1f}%",
                                "renk": "yesil" if degisim_pct > 0 else "kirmizi"
                            })

                        # 4. MACD kesişimi
                        macd_kesisim = (
                            (macd_onceki < signal_onceki and macd_son > signal_son) or
                            (macd_onceki > signal_onceki and macd_son < signal_son)
                        )
                        if macd_kesisim:
                            yukari = macd_son > signal_son
                            bildirimler.append({
                                "tip": "macd",
                                "baslik": f"⚡ {ticker} MACD Kesişimi!",
                                "mesaj": f"{'Yükseliş' if yukari else 'Düşüş'} kesişimi — {fiyat:.2f}₺",
                                "renk": "yesil" if yukari else "kirmizi"
                            })

                        # Bildirimleri gönder
                        for b in bildirimler:
                            b["ticker"] = ticker
                            b["fiyat"]  = fiyat
                            b["zaman"]  = datetime.now().strftime("%H:%M")
                            await ws_bildirim_gonder(alarm["kullanici_id"], b)

                except Exception as e:
                    print(f"[ALARM] {ticker} hata: {e}")

        except Exception as e:
            print(f"[ALARM] Genel hata: {e}")

@app.on_event("startup")
async def alarm_baslat():
    asyncio.create_task(gelismis_alarm_kontrol())

# ── WebSocket Canlı Alarm ─────────────────────────────────
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
import asyncio, json
from typing import Dict, Set

# Bağlı istemciler: {kullanici_id: set(websocket)}
ws_baglantilari: Dict[int, Set[WebSocket]] = {}

class BaglantiYoneticisi:
    def __init__(self):
        self.aktif: Dict[int, Set[WebSocket]] = {}

    async def baglan(self, ws: WebSocket, kullanici_id: int):
        await ws.accept()
        if kullanici_id not in self.aktif:
            self.aktif[kullanici_id] = set()
        self.aktif[kullanici_id].add(ws)

    def ayril(self, ws: WebSocket, kullanici_id: int):
        if kullanici_id in self.aktif:
            self.aktif[kullanici_id].discard(ws)

    async def gonder(self, kullanici_id: int, mesaj: dict):
        if kullanici_id in self.aktif:
            kopuk = set()
            for ws in self.aktif[kullanici_id]:
                try:
                    await ws.send_json(mesaj)
                except:
                    kopuk.add(ws)
            self.aktif[kullanici_id] -= kopuk

    async def herkese_gonder(self, mesaj: dict):
        for uid in list(self.aktif.keys()):
            await self.gonder(uid, mesaj)

baglanti_yoneticisi = BaglantiYoneticisi()

@app.websocket("/ws/{kullanici_id}")
async def websocket_endpoint(ws: WebSocket, kullanici_id: int):
    await baglanti_yoneticisi.baglan(ws, kullanici_id)
    try:
        # Bağlantı onayı
        await ws.send_json({"tip": "baglandi", "mesaj": "Canlı alarm sistemi aktif ✓"})

        # İstemciden mesaj dinle (ping/pong & alarm kaydı)
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("tip") == "ping":
                    await ws.send_json({"tip": "pong"})
                elif msg.get("tip") == "alarm_kaydet":
                    # Anlık alarm kontrolü tetikle
                    ticker = msg.get("ticker", "")
                    if ticker:
                        await alarm_kontrol_et(kullanici_id, ticker, ws)
            except:
                pass
    except WebSocketDisconnect:
        baglanti_yoneticisi.ayril(ws, kullanici_id)

async def alarm_kontrol_et(kullanici_id: int, ticker: str, ws: WebSocket = None):
    """Tek hisse için tüm alarm türlerini kontrol et."""
    try:
        fiyat  = await run_in_threadpool(get_stock_price, ticker)
        teknik = await run_in_threadpool(get_technical_indicators, ticker)
        guncel = fiyat.get("fiyat", 0)
        degisim = fiyat.get("degisim_yuzde", 0)

        alarmlar = []

        # 1. Hedef fiyat alarmları (DB'den)
        conn = get_db()
        try:
            hedef_alarmlar = conn.execute("""
                SELECT * FROM alarmlar
                WHERE kullanici_id = ? AND ticker = ? AND aktif = 1
            """, (kullanici_id, ticker.upper())).fetchall()
        finally:
            conn.close()

        for alarm in hedef_alarmlar:
            hedef = alarm["hedef_fiyat"]
            tip   = alarm["alarm_tipi"]
            if tip == "yukari" and guncel >= hedef:
                alarmlar.append({
                    "tip": "alarm",
                    "tur": "hedef_fiyat",
                    "ticker": ticker.upper(),
                    "mesaj": f"🎯 {ticker} hedef fiyata ulaştı!",
                    "detay": f"Güncel: {guncel:.2f} ₺ ≥ Hedef: {hedef:.2f} ₺",
                    "seviye": "yuksek",
                    "ses": "alarm"
                })
            elif tip == "asagi" and guncel <= hedef:
                alarmlar.append({
                    "tip": "alarm",
                    "tur": "hedef_fiyat",
                    "ticker": ticker.upper(),
                    "mesaj": f"🎯 {ticker} hedef fiyata düştü!",
                    "detay": f"Güncel: {guncel:.2f} ₺ ≤ Hedef: {hedef:.2f} ₺",
                    "seviye": "yuksek",
                    "ses": "alarm"
                })

        # 2. RSI aşırı alım/satım
        rsi = teknik.get("RSI_14", 50)
        if rsi >= 70:
            alarmlar.append({
                "tip": "alarm",
                "tur": "rsi",
                "ticker": ticker.upper(),
                "mesaj": f"⚠️ {ticker} aşırı alım bölgesinde!",
                "detay": f"RSI: {rsi:.1f} ≥ 70 — Satış baskısı oluşabilir",
                "seviye": "orta",
                "ses": "uyari"
            })
        elif rsi <= 30:
            alarmlar.append({
                "tip": "alarm",
                "tur": "rsi",
                "ticker": ticker.upper(),
                "mesaj": f"📉 {ticker} aşırı satım bölgesinde!",
                "detay": f"RSI: {rsi:.1f} ≤ 30 — Toparlanma fırsatı olabilir",
                "seviye": "orta",
                "ses": "firsat"
            })

        # 3. %5 ani hareket
        if degisim >= 5:
            alarmlar.append({
                "tip": "alarm",
                "tur": "ani_hareket",
                "ticker": ticker.upper(),
                "mesaj": f"🚀 {ticker} güçlü yükseliş!",
                "detay": f"Günlük değişim: +{degisim:.2f}% — Hacim artışı kontrol et",
                "seviye": "yuksek",
                "ses": "yukselis"
            })
        elif degisim <= -5:
            alarmlar.append({
                "tip": "alarm",
                "tur": "ani_hareket",
                "ticker": ticker.upper(),
                "mesaj": f"📉 {ticker} sert düşüş!",
                "detay": f"Günlük değişim: {degisim:.2f}% — Dikkat!",
                "seviye": "kritik",
                "ses": "dusus"
            })

        # 4. MACD kesişimi
        macd = teknik.get("MACD", 0)
        macd_signal = teknik.get("MACD_signal", 0)
        if macd and macd_signal:
            if macd > macd_signal and macd > 0:
                alarmlar.append({
                    "tip": "alarm",
                    "tur": "macd",
                    "ticker": ticker.upper(),
                    "mesaj": f"📈 {ticker} MACD yükseliş kesişimi!",
                    "detay": f"MACD ({macd:.3f}) > Sinyal ({macd_signal:.3f})",
                    "seviye": "orta",
                    "ses": "firsat"
                })

        # Alarmları gönder
        hedef = ws or None
        for alarm in alarmlar:
            if hedef:
                try:
                    await hedef.send_json(alarm)
                except:
                    pass
            else:
                await baglanti_yoneticisi.gonder(kullanici_id, alarm)

        return alarmlar
    except Exception as e:
        return []

# Periyodik fiyat izleyici (her 30 sn watchlist kontrol)
@app.on_event("startup")
async def canli_alarm_baslat():
    asyncio.create_task(fiyat_izleyici())

async def fiyat_izleyici():
    """30 saniyede bir tüm bağlı kullanıcıların watchlist'ini kontrol et."""
    await asyncio.sleep(10)  # Startup bekle
    while True:
        try:
            if baglanti_yoneticisi.aktif:
                conn = get_db()
                try:
                    for kullanici_id in list(baglanti_yoneticisi.aktif.keys()):
                        watchlist = conn.execute("""
                            SELECT ticker FROM watchlist WHERE kullanici_id = ?
                        """, (kullanici_id,)).fetchall()
                        for row in watchlist:
                            await alarm_kontrol_et(kullanici_id, row["ticker"])
                            await asyncio.sleep(0.5)
                finally:
                    conn.close()
        except Exception as e:
            print(f"[ALARM] Hata: {e}")
        await asyncio.sleep(30)

# ── BIST Isı Haritası ─────────────────────────────────────
BIST_HISSELER = {
    "Bankacılık": ["GARAN","AKBNK","YKBNK","ISCTR","HALKB","VAKBN","TSKB","ALBRK"],
    "Sanayi": ["EREGL","KRDMD","CEMTS","TRKCM","FROTO","TOASO","OTKAR","AGHOL"],
    "Enerji": ["TUPRS","AKENR","AKSEN","ZOREN","ODAS","EUPWR","BIMAS","MGROS"],
    "Teknoloji": ["ASELS","NETAS","LOGO","DOAS","INDES","ARMDA","FONET","OBASI"],
    "Havacılık": ["THYAO","PGSUS","CLEBI","HAVAŞ","TAVHL"],
    "Perakende": ["BIMAS","MGROS","SOKM","MAVI","LCWGN"],
    "GYO": ["ISGYO","EKGYO","TRGYO","OZGYO","AVGYO"],
    "Holding": ["KCHOL","SAHOL","SISE","DOHOL","TKFEN"],
}

# Piyasa değeri ağırlıkları (yaklaşık, milyar TL)
PIYASA_DEGERI = {
    "GARAN":220,"AKBNK":180,"YKBNK":150,"ISCTR":160,"HALKB":90,"VAKBN":80,
    "THYAO":280,"EREGL":120,"TUPRS":200,"ASELS":180,"KCHOL":250,"SAHOL":200,
    "SISE":110,"BIMAS":160,"FROTO":140,"TOASO":130,"PGSUS":80,"TSKB":50,
    "TAVHL":90,"KRDMD":60,"MGROS":70,"SOKM":65,"LOGO":40,"NETAS":30,
    "DOHOL":45,"TKFEN":55,"ISGYO":35,"EKGYO":40,"AKENR":50,"AKSEN":45,
    "MAVI":38,"LCWGN":32,"ALBRK":28,"ZOREN":42,"OTKAR":38,"TRKCM":44,
    "DOAS":36,"INDES":25,"ARMDA":20,"FONET":18,"CEMTS":22,"AGHOL":85,
    "CLEBI":28,"OZGYO":22,"TRGYO":30,"AVGYO":18,"ODAS":35,"EUPWR":30,
    "OBASI":15,"HAVAŞ":20,
}

@app.get("/bist/isi-haritasi")
async def isi_haritasi():
    """BIST hisselerinin günlük değişimini sektör bazında döndür."""
    import yfinance as yf
    from fastapi.concurrency import run_in_threadpool

    def hisse_veri_getir():
        sonuc = []
        # Tüm ticker'ları tek seferde çek (daha hızlı)
        tum_hisseler = []
        for sektor, hisseler in BIST_HISSELER.items():
            for ticker in hisseler:
                tum_hisseler.append((sektor, ticker))

        for sektor, ticker in tum_hisseler:
            try:
                stock = yf.Ticker(f"{ticker}.IS")
                df    = stock.history(period="5d")
                if df.empty or len(df) < 2:
                    continue
                bugun   = float(df["Close"].iloc[-1])
                dun     = float(df["Close"].iloc[-2])
                if dun == 0:
                    continue
                degisim = round((bugun - dun) / dun * 100, 2)
                hacim   = float(df["Volume"].iloc[-1])
                sonuc.append({
                    "ticker":        ticker,
                    "sektor":        sektor,
                    "fiyat":         round(bugun, 2),
                    "degisim":       degisim,
                    "hacim":         hacim,
                    "piyasa_degeri": PIYASA_DEGERI.get(ticker, 20),
                })
            except Exception as e:
                print(f"[ISI] {ticker} hata: {e}")
        return sonuc

    veriler = await run_in_threadpool(hisse_veri_getir)
    return {"hisseler": veriler, "toplam": len(veriler)}

# ── Fırsat Tarayıcı ───────────────────────────────────────
BIST100 = [
    # Bankacılık (en likit)
    "GARAN","AKBNK","YKBNK","ISCTR","HALKB","VAKBN",
    # Havacılık & Ulaşım
    "THYAO","PGSUS","TAVHL",
    # Sanayi & Metal
    "EREGL","KRDMD","OTKAR","FROTO","TOASO",
    # Enerji
    "TUPRS","AKSEN","ZOREN",
    # Teknoloji & Savunma
    "ASELS","LOGO",
    # Holding
    "KCHOL","SAHOL","SISE","TKFEN",
    # Perakende & Tüketim
    "BIMAS","MGROS","SOKM","ULKER","MAVI",
    # Telecom & Medya
    "TTKOM","TCELL",
    # GYO & İnşaat
    "EKGYO","ISGYO","ENKAI",
    # Diğer
    "KOZAL","PETKM","GUBRF","ARCLK","BRISA","CIMSA","SODA",
]

@app.get("/bist/firsat-tarayici")
async def firsat_tarayici(batch: int = 0):
    import yfinance as yf
    import numpy as np
    from fastapi.concurrency import run_in_threadpool

    BATCH_SIZE  = 10
    hedef_liste = BIST100[batch * BATCH_SIZE:(batch + 1) * BATCH_SIZE]

    def hisse_tara(ticker: str, df=None) -> dict | None:
        try:
            if df is None:
                stock = yf.Ticker(f"{ticker}.IS")
                df    = stock.history(period="3mo", interval="1d")
            if df.empty or len(df) < 30:
                return None

            kapanis = df["Close"]
            hacim   = df["Volume"]

            # ── RSI ──────────────────────────────────────
            delta = kapanis.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rs    = gain / loss
            rsi   = 100 - (100 / (1 + rs))
            rsi_son     = float(rsi.iloc[-1])
            rsi_onceki  = float(rsi.iloc[-2])

            # RSI dip dönüş: önceki gün <30, bugün yükseliyor
            sinyal_rsi = rsi_onceki < 32 and rsi_son > rsi_onceki and rsi_son < 45

            # ── Hacim artışı ─────────────────────────────
            hacim_ort   = float(hacim.iloc[-20:-1].mean())
            hacim_bugun = float(hacim.iloc[-1])
            sinyal_hacim = hacim_bugun >= hacim_ort * 2.0

            # ── Destek seviyesi ──────────────────────────
            son_fiyat  = float(kapanis.iloc[-1])
            son_30_min = float(kapanis.iloc[-30:].min())
            destek_mesafe = (son_fiyat - son_30_min) / son_30_min * 100
            sinyal_destek = destek_mesafe <= 3.0  # Dip'e %3 yakın

            # ── MACD sıfır altı pozitif kesişim ──────────
            ema12  = kapanis.ewm(span=12).mean()
            ema26  = kapanis.ewm(span=26).mean()
            macd   = ema12 - ema26
            signal = macd.ewm(span=9).mean()
            macd_son     = float(macd.iloc[-1])
            macd_onceki  = float(macd.iloc[-2])
            sig_son      = float(signal.iloc[-1])
            sig_onceki   = float(signal.iloc[-2])
            # MACD sıfırın altında, sinyal çizgisini yukarı kesiyor
            sinyal_macd = (
                macd_son < 0 and
                macd_onceki < sig_onceki and
                macd_son > sig_son
            )

            # ── Bollinger alt bant ────────────────────────
            bb_ort = kapanis.rolling(20).mean()
            bb_std = kapanis.rolling(20).std()
            bb_alt = bb_ort - 2 * bb_std
            bb_alt_son  = float(bb_alt.iloc[-1])
            bb_alt_onc  = float(bb_alt.iloc[-2])
            fiyat_onc   = float(kapanis.iloc[-2])
            # Önceki gün alt banda değdi, bugün kapanış bant üstünde
            sinyal_bb = fiyat_onc <= bb_alt_onc and son_fiyat > bb_alt_son

            # ── Yabancı yoğunlaşması (simüle) ───────────
            # Gerçek veri için MKK API gerekir.
            # Hacim + fiyat artışı + RSI kombinasyonuyla proxy
            sinyal_yabanci = (
                hacim_bugun >= hacim_ort * 1.5 and
                float(kapanis.iloc[-1]) > float(kapanis.iloc[-3]) and
                rsi_son > 35
            )

            # ── Toplam skor ───────────────────────────────
            sinyaller = {
                "rsi_dip":   sinyal_rsi,
                "hacim":     sinyal_hacim,
                "destek":    sinyal_destek,
                "macd":      sinyal_macd,
                "bollinger": sinyal_bb,
                "yabanci":   sinyal_yabanci,
            }
            skor = sum(sinyaller.values())

            if skor < 2:  # En az 2 sinyal şartı
                return None

            # Değişim
            degisim = round((son_fiyat - float(kapanis.iloc[-2])) / float(kapanis.iloc[-2]) * 100, 2)

            return {
                "ticker":    ticker,
                "fiyat":     round(son_fiyat, 2),
                "degisim":   degisim,
                "rsi":       round(rsi_son, 1),
                "skor":      skor,
                "sinyaller": sinyaller,
                "destek_mesafe": round(destek_mesafe, 1),
                "hacim_orani":   round(hacim_bugun / hacim_ort, 1) if hacim_ort > 0 else 0,
            }
        except Exception as e:
            print(f"[TARAYICI] {ticker}: {e}")
            return None

    def tara():
        import warnings
        warnings.filterwarnings("ignore")
        semboller = [f"{t}.IS" for t in hedef_liste]
        try:
            df_bulk = yf.download(semboller, period="3mo", interval="1d", progress=False, auto_adjust=True, group_by="ticker")
        except:
            return {"firsatlar": [], "toplam": 0, "taranan": 0, "son_batch": True}

        sonuclar = []
        for ticker in hedef_liste:
            try:
                sembol = f"{ticker}.IS"
                if len(hedef_liste)==1:
                    df = df_bulk
                else:
                    try:
                        df = df_bulk[sembol]
                    except Exception:
                        continue
                if df is None or df.empty:
                    continue
                r = hisse_tara(ticker, df=df)
                if r:
                    sonuclar.append(r)
            except:
                continue
        sonuclar.sort(key=lambda x: (-x["skor"], x["rsi"]))
        return {"firsatlar": sonuclar, "toplam": len(sonuclar), "taranan": len(hedef_liste), "son_batch": (batch+1)*10 >= len(BIST100)}

    return await run_in_threadpool(tara)

# ── Seviye Hesaplayıcı ────────────────────────────────────
@app.get("/stock/{ticker}/seviyeler")
async def seviye_hesapla(ticker: str):
    """
    Otomatik alım bölgesi, stop-loss ve hedef fiyat hesaplar.
    Pivot + Fibonacci + ATR + Bollinger kullanır.
    """
    import yfinance as yf
    import numpy as np
    from fastapi.concurrency import run_in_threadpool

    def hesapla():
        stock = yf.Ticker(f"{ticker.upper()}.IS")
        df    = stock.history(period="3mo", interval="1d")
        if df.empty or len(df) < 30:
            raise ValueError("Yeterli veri yok")

        kapanis = df["Close"]
        yuksek  = df["High"]
        dusuk   = df["Low"]

        gun_fiyat = float(kapanis.iloc[-1])
        gun_yuk   = float(yuksek.iloc[-1])
        gun_dus   = float(dusuk.iloc[-1])

        # ── Pivot Noktaları (dünün H/L/C) ────────────────
        d_kap = float(kapanis.iloc[-2])
        d_yuk = float(yuksek.iloc[-2])
        d_dus = float(dusuk.iloc[-2])
        pivot = (d_yuk + d_dus + d_kap) / 3
        d1    = 2 * pivot - d_dus   # Direnç 1
        d2    = pivot + (d_yuk - d_dus)  # Direnç 2
        s1    = 2 * pivot - d_yuk   # Destek 1
        s2    = pivot - (d_yuk - d_dus)  # Destek 2

        # ── ATR (Average True Range) ──────────────────────
        tr_list = []
        for i in range(1, len(df)):
            tr = max(
                float(yuksek.iloc[i]) - float(dusuk.iloc[i]),
                abs(float(yuksek.iloc[i]) - float(kapanis.iloc[i-1])),
                abs(float(dusuk.iloc[i]) - float(kapanis.iloc[i-1]))
            )
            tr_list.append(tr)
        atr = float(np.mean(tr_list[-14:]))

        # ── Son 30 günlük dip/tepe ────────────────────────
        son30_min = float(dusuk.iloc[-30:].min())
        son30_max = float(yuksek.iloc[-30:].max())
        son10_min = float(dusuk.iloc[-10:].min())
        son10_max = float(yuksek.iloc[-10:].max())

        # ── Bollinger Bantları ────────────────────────────
        bb_ort  = float(kapanis.rolling(20).mean().iloc[-1])
        bb_std  = float(kapanis.rolling(20).std().iloc[-1])
        bb_alt  = bb_ort - 2 * bb_std
        bb_ust  = bb_ort + 2 * bb_std

        # ── Fibonacci Seviyeleri ──────────────────────────
        fib_aralik = son30_max - son30_min
        fib_236 = son30_max - fib_aralik * 0.236
        fib_382 = son30_max - fib_aralik * 0.382
        fib_500 = son30_max - fib_aralik * 0.500
        fib_618 = son30_max - fib_aralik * 0.618

        # ── Alım Bölgesi ──────────────────────────────────
        # Destek1, BB alt ve son10 dip arasındaki bölge
        alim_alt = round(max(s1, bb_alt, son10_min - atr * 0.3), 2)
        alim_ust = round(min(s1 + atr * 0.5, gun_fiyat * 0.995), 2)
        if alim_alt > alim_ust:
            alim_alt, alim_ust = round(gun_fiyat - atr, 2), round(gun_fiyat - atr * 0.3, 2)

        # ── Stop-Loss ─────────────────────────────────────
        stop_loss = round(max(alim_alt - atr * 1.2, son30_min - atr * 0.5), 2)

        # ── Hedefler ─────────────────────────────────────
        # Giriş noktası olarak alım bölgesi ortası
        giris = round((alim_alt + alim_ust) / 2, 2)
        risk  = giris - stop_loss

        hedef1 = round(giris + risk * 1.5, 2)   # R/R: 1.5
        hedef2 = round(giris + risk * 2.5, 2)   # R/R: 2.5
        hedef3 = round(giris + risk * 4.0, 2)   # R/R: 4.0

        # Fibonacci ile karşılaştır, daha mantıklı olanı seç
        if abs(fib_236 - hedef1) / hedef1 < 0.03:
            hedef1 = round(fib_236, 2)
        if abs(fib_382 - hedef2) / hedef2 < 0.04:
            hedef2 = round(fib_382, 2)

        # ── Risk/Ödül ─────────────────────────────────────
        rr1 = round((hedef1 - giris) / risk, 1) if risk > 0 else 0
        rr2 = round((hedef2 - giris) / risk, 1) if risk > 0 else 0

        # ── Yüzde hesapları ───────────────────────────────
        stop_pct   = round((stop_loss - giris) / giris * 100, 1)
        hedef1_pct = round((hedef1 - giris) / giris * 100, 1)
        hedef2_pct = round((hedef2 - giris) / giris * 100, 1)
        hedef3_pct = round((hedef3 - giris) / giris * 100, 1)

        # ── Genel değerlendirme ───────────────────────────
        rr_degerlendirme = (
            "Mükemmel" if rr2 >= 3 else
            "İyi"      if rr2 >= 2 else
            "Orta"     if rr2 >= 1.5 else
            "Zayıf"
        )

        return {
            "ticker":   ticker.upper(),
            "gun_fiyat": round(gun_fiyat, 2),
            "giris": {
                "alt":  alim_alt,
                "ust":  alim_ust,
                "orta": giris,
                "aciklama": f"Destek ({round(s1,2)}₺) + Bollinger alt ({round(bb_alt,2)}₺) bölgesi"
            },
            "stop_loss": {
                "fiyat": stop_loss,
                "pct":   stop_pct,
                "aciklama": f"ATR ({round(atr,2)}₺) tabanlı · 30g dip: {round(son30_min,2)}₺"
            },
            "hedefler": [
                {"no":1, "fiyat":hedef1, "pct":hedef1_pct, "rr":rr1, "aciklama":"Kısa vade hedef"},
                {"no":2, "fiyat":hedef2, "pct":hedef2_pct, "rr":rr2, "aciklama":"Orta vade hedef"},
                {"no":3, "fiyat":hedef3, "pct":hedef3_pct, "rr":round(rr2*1.6,1), "aciklama":"Uzun vade hedef"},
            ],
            "seviyeler": {
                "pivot":   round(pivot, 2),
                "destek1": round(s1, 2),
                "destek2": round(s2, 2),
                "direnc1": round(d1, 2),
                "direnc2": round(d2, 2),
                "bb_alt":  round(bb_alt, 2),
                "bb_ust":  round(bb_ust, 2),
                "fib_382": round(fib_382, 2),
                "fib_618": round(fib_618, 2),
            },
            "atr": round(atr, 2),
            "rr_degerlendirme": rr_degerlendirme,
            "uyari": "Bu hesaplamalar teknik analiz göstergelerine dayanır, yatırım tavsiyesi değildir."
        }

    from fastapi.concurrency import run_in_threadpool
    try:
        return await run_in_threadpool(hesapla)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Para Akışı Tarayıcı ───────────────────────────────────
@app.get("/bist/para-akisi")
async def para_akisi(batch: int = 0):
    import yfinance as yf
    import numpy as np
    from fastapi.concurrency import run_in_threadpool

    BATCH_SIZE  = 10
    hedef_liste = BIST100[batch * BATCH_SIZE:(batch + 1) * BATCH_SIZE]

    def hisse_para_akisi(ticker: str, df_saat=None, df_gun=None) -> dict | None:
        try:
            if df_saat is None:
                stock   = yf.Ticker(f"{ticker}.IS")
                df_saat = stock.history(period="60d", interval="1h")
                df_gun  = stock.history(period="30d", interval="1d")

            if df_saat.empty or len(df_saat) < 24:
                return None

            kapanis = df_saat["Close"].values
            yuksek  = df_saat["High"].values
            dusuk   = df_saat["Low"].values
            hacim   = df_saat["Volume"].values

            # ── MFI — 14 saatlik pencere ──────────────────
            typical_price  = (yuksek + dusuk + kapanis) / 3
            raw_money_flow = typical_price * hacim

            positive_mf, negative_mf = [], []
            for i in range(1, len(typical_price)):
                if typical_price[i] > typical_price[i-1]:
                    positive_mf.append(raw_money_flow[i])
                    negative_mf.append(0)
                else:
                    positive_mf.append(0)
                    negative_mf.append(raw_money_flow[i])

            mfi_period = 14  # 14 saatlik MFI
            pos_sum = sum(positive_mf[-mfi_period:])
            neg_sum = sum(negative_mf[-mfi_period:])
            if neg_sum == 0:
                mfi = 100.0
            else:
                mfi = 100 - (100 / (1 + pos_sum / neg_sum))

            # ── OBV — günlük veri üzerinden ───────────────
            if not df_gun.empty and len(df_gun) >= 10:
                kap_g = df_gun["Close"].values
                hac_g = df_gun["Volume"].values
                obv = [0]
                for i in range(1, len(kap_g)):
                    if kap_g[i] > kap_g[i-1]:
                        obv.append(obv[-1] + hac_g[i])
                    elif kap_g[i] < kap_g[i-1]:
                        obv.append(obv[-1] - hac_g[i])
                    else:
                        obv.append(obv[-1])
                obv = np.array(obv)
                obv_son5 = float(np.mean(obv[-5:]))
                obv_onc5 = float(np.mean(obv[-10:-5]))
                obv_degisim = ((obv_son5 - obv_onc5) / abs(obv_onc5) * 100) if obv_onc5 != 0 else 0
            else:
                obv_degisim = 0
            obv_skor = min(100, max(0, 50 + obv_degisim * 2))

            # ── Saatlik Hacim Analizi ─────────────────────
            # Son 20 saatin ortalamasına göre mevcut saat
            hacim_ort20 = float(np.mean(hacim[-21:-1]))
            hacim_son   = float(hacim[-1])
            hacim_oran  = hacim_son / hacim_ort20 if hacim_ort20 > 0 else 1

            fiyat_degisim = (kapanis[-1] - kapanis[-2]) / kapanis[-2] * 100
            if fiyat_degisim > 0 and hacim_oran > 1.2:
                hacim_skor = min(100, 60 + hacim_oran * 10)
            elif fiyat_degisim < 0 and hacim_oran > 1.2:
                hacim_skor = max(0, 40 - hacim_oran * 10)
            else:
                hacim_skor = 50

            # ── Gün içi para akışı (son 8 saat) ──────────
            bugun_mf_pozitif = 0.0
            bugun_mf_negatif = 0.0
            son8 = min(8, len(typical_price))
            for i in range(-son8, 0):
                tp  = typical_price[i]
                tp0 = typical_price[i-1]
                mf  = raw_money_flow[i]
                if tp > tp0:
                    bugun_mf_pozitif += mf
                else:
                    bugun_mf_negatif += mf
            gunici_oran = round(
                bugun_mf_pozitif / (bugun_mf_pozitif + bugun_mf_negatif) * 100
                if (bugun_mf_pozitif + bugun_mf_negatif) > 0 else 50, 1
            )

            # ── Para Akış Skoru ───────────────────────────
            para_skoru = round(mfi * 0.40 + obv_skor * 0.35 + hacim_skor * 0.25, 1)

            yon = "giris" if para_skoru >= 65 else "cikis" if para_skoru <= 35 else "notr"

            # ── Son 8 saatlik trend çubukları ─────────────
            trend = []
            for i in range(-min(8, len(typical_price)), 0):
                tp_su  = typical_price[i]
                tp_onc = typical_price[i-1]
                trend.append({
                    "yon": "↑" if tp_su > tp_onc else "↓",
                    "guc": round(raw_money_flow[i] / 1e6, 1),
                })

            gun_fiyat   = float(kapanis[-1])
            gun_degisim = round(fiyat_degisim, 2)

            return {
                "ticker":       ticker,
                "fiyat":        round(gun_fiyat, 2),
                "degisim":      gun_degisim,
                "para_skoru":   para_skoru,
                "yon":          yon,
                "mfi":          round(mfi, 1),
                "obv_degisim":  round(obv_degisim, 1),
                "hacim_oran":   round(hacim_oran, 2),
                "gunici_oran":  gunici_oran,
                "trend":        trend,
                "hacim_tl":     round(hacim_son * gun_fiyat / 1e6, 1),
                "aralik":       "1s",
            }
        except Exception as e:
            print(f"[PARA AKIŞI] {ticker}: {e}")
            return None

    def tara():
        import warnings
        warnings.filterwarnings("ignore")
        semboller = [f"{t}.IS" for t in hedef_liste]
        try:
            df_bulk  = yf.download(semboller, period="60d", interval="1h",  progress=False, auto_adjust=True, group_by="ticker")
            df_bulk_g = yf.download(semboller, period="30d", interval="1d", progress=False, auto_adjust=True, group_by="ticker")
        except:
            return {"hisseler": [], "ozet": {"toplam":0,"giren":0,"cikan":0,"notr":0,"ortalama_skor":0}}

        sonuclar = []
        for ticker in hedef_liste:
            try:
                sembol = f"{ticker}.IS"
                def bulk_getir(bulk, sembol):
                    if len(hedef_liste) == 1:
                        return bulk
                    try:
                        return bulk[sembol]
                    except Exception:
                        return None

                df_s = bulk_getir(df_bulk, sembol)
                df_g = bulk_getir(df_bulk_g, sembol)
                if df_s is None or df_s.empty:
                    continue
                r = hisse_para_akisi(ticker, df_saat=df_s, df_gun=df_g)
                if r:
                    sonuclar.append(r)
            except:
                continue
        sonuclar.sort(key=lambda x: -x["para_skoru"])
        giren = [h for h in sonuclar if h["yon"] == "giris"]
        cikan = [h for h in sonuclar if h["yon"] == "cikis"]
        notr  = [h for h in sonuclar if h["yon"] == "notr"]
        return {
            "hisseler": sonuclar,
            "ozet": {
                "toplam": len(sonuclar), "giren": len(giren),
                "cikan": len(cikan), "notr": len(notr),
                "ortalama_skor": round(sum(h["para_skoru"] for h in sonuclar) / len(sonuclar), 1) if sonuclar else 0,
            }
        }

    return await run_in_threadpool(tara)

# ── Zanger Tarayıcı ───────────────────────────────────────
@app.get("/debug/zanger")
async def debug_zanger():
    import yfinance as yf
    import warnings
    warnings.filterwarnings("ignore")
    from fastapi.concurrency import run_in_threadpool

    def kontrol():
        semboller = ["GARAN.IS", "AKBNK.IS"]
        df = yf.download(semboller, period="6mo", interval="1d", progress=False, auto_adjust=True, group_by="ticker")
        
        try:
            df_garan = df["GARAN.IS"]
            kapanis  = df_garan["Close"].dropna().values
            yuksek   = df_garan["High"].dropna().values
            return {
                "shape":        str(df.shape),
                "garan_shape":  str(df_garan.shape),
                "garan_len":    len(kapanis),
                "garan_close":  str(kapanis[-3:].tolist()),
                "garan_high":   str(yuksek[-3:].tolist()),
                "cols":         str(df_garan.columns.tolist()),
            }
        except Exception as e:
            return {"hata": str(e), "shape": str(df.shape)}

    return await run_in_threadpool(kontrol)

@app.get("/bist/zanger")
async def zanger_tarayici(batch: int = 0):
    """
    Batch 0 → ilk 20 hisse, Batch 1 → son 20 hisse
    """
    import yfinance as yf
    import numpy as np
    from fastapi.concurrency import run_in_threadpool

    BATCH_SIZE = 10
    baslangic = batch * BATCH_SIZE
    bitis     = baslangic + BATCH_SIZE
    hedef_liste = BIST100[baslangic:bitis]

    def zanger_hesapla(ticker: str, bist100_getiri: float) -> dict | None:
        try:
            stock = yf.Ticker(f"{ticker}.IS")
            df    = stock.history(period="6mo", interval="1d")
            if df.empty or len(df) < 60:
                return None

            kapanis = df["Close"].values
            yuksek  = df["High"].values
            dusuk   = df["Low"].values
            hacim   = df["Volume"].values

            gun_fiyat  = float(kapanis[-1])
            gun_yuksek = float(yuksek[-1])
            gun_dusuk  = float(dusuk[-1])

            # ── Kriter 1: 52 Haftalık Zirveye Yakınlık ───
            zirve_52h = float(np.max(yuksek))  # Tüm mevcut veri
            zirveye_uzaklik = (zirve_52h - gun_fiyat) / zirve_52h * 100
            k1_zirve = zirveye_uzaklik <= 5.0  # Zirveye %5 içinde

            # ── Kriter 2: Hacim Patlaması ─────────────────
            hacim_ort50  = float(np.mean(hacim[-51:-1]))
            hacim_bugun  = float(hacim[-1])
            hacim_oran   = hacim_bugun / hacim_ort50 if hacim_ort50 > 0 else 1
            k2_hacim     = hacim_oran >= 2.0

            # ── Kriter 3: Relative Strength ───────────────
            # Son 63 gün (3 ay) hisse getirisi vs BIST100
            if len(kapanis) >= 63:
                hisse_getiri = (kapanis[-1] - kapanis[-63]) / kapanis[-63] * 100
            else:
                hisse_getiri = 0
            rs_fark  = hisse_getiri - bist100_getiri
            k3_rs    = rs_fark > 0  # BIST100'ü geçiyor

            # RS Skoru: 1-99 arası normalize
            rs_skor = min(99, max(1, int(50 + rs_fark * 1.5)))

            # ── Kriter 4: Baz Oluşumu ─────────────────────
            # Son 5-15 günde fiyat volatilitesi düşük mü?
            baz_gun = min(10, len(kapanis) - 1)
            baz_yuksek = float(np.max(yuksek[-baz_gun:]))
            baz_dusuk  = float(np.min(dusuk[-baz_gun:]))
            baz_genislik = (baz_yuksek - baz_dusuk) / baz_dusuk * 100
            k4_baz = baz_genislik <= 8.0  # Dar bant = baz oluşumu

            # Baz tipi tahmini
            if baz_genislik <= 3:
                baz_tipi = "Sıkışma"
            elif baz_genislik <= 6:
                baz_tipi = "Dar Baz"
            else:
                baz_tipi = "Geniş Baz"

            # ── Kriter 5: Kırılım ─────────────────────────
            # Dünkü high kırıldı mı? + Hacim teyidi
            dun_yuksek  = float(yuksek[-2])
            k5_kirilim  = gun_fiyat > dun_yuksek and hacim_oran >= 1.5

            # ── Zanger Skoru ──────────────────────────────
            kriterler = {
                "zirve_yakini":  k1_zirve,
                "hacim_patlamasi": k2_hacim,
                "relative_guc":  k3_rs,
                "baz_olusumu":   k4_baz,
                "kirilim":       k5_kirilim,
            }
            skor = sum(kriterler.values())

            if skor < 2:
                return None

            # Sinyal gücü
            if skor == 5:
                guc = "MUKEMMEL"
            elif skor == 4:
                guc = "GUCLU"
            elif skor == 3:
                guc = "IYI"
            else:
                guc = "TAKIPTE"

            fiyat_degisim = round(
                (kapanis[-1] - kapanis[-2]) / kapanis[-2] * 100, 2
            )

            # ATR (volatilite)
            tr_list = [
                max(float(yuksek[i]) - float(dusuk[i]),
                    abs(float(yuksek[i]) - float(kapanis[i-1])),
                    abs(float(dusuk[i]) - float(kapanis[i-1])))
                for i in range(1, len(df))
            ]
            atr = round(float(np.mean(tr_list[-14:])), 2)

            return {
                "ticker":          ticker,
                "fiyat":           round(gun_fiyat, 2),
                "degisim":         fiyat_degisim,
                "skor":            skor,
                "guc":             guc,
                "kriterler":       kriterler,
                "zirveye_uzaklik": round(zirveye_uzaklik, 1),
                "zirve_52h":       round(zirve_52h, 2),
                "hacim_oran":      round(hacim_oran, 1),
                "rs_skor":         rs_skor,
                "rs_fark":         round(rs_fark, 1),
                "baz_tipi":        baz_tipi,
                "baz_genislik":    round(baz_genislik, 1),
                "dun_yuksek":      round(dun_yuksek, 2),
                "atr":             atr,
                "hisse_getiri_3ay": round(hisse_getiri, 1),
            }
        except Exception as e:
            print(f"[ZANGER] {ticker}: {e}")
            return None

    def tara():
        import warnings
        warnings.filterwarnings("ignore")

        # BIST100 getirisi — birkaç sembol dene
        bist_getiri = 0.0
        for xu_sembol in ["XU100.IS", "^XU100", "BIST.IS"]:
            try:
                df_xu = yf.download(xu_sembol, period="3mo", interval="1d", progress=False, auto_adjust=True)
                if not df_xu.empty and len(df_xu) >= 10:
                    idx = min(63, len(df_xu)-1)
                    bist_getiri = float((df_xu["Close"].iloc[-1] - df_xu["Close"].iloc[-idx]) / df_xu["Close"].iloc[-idx] * 100)
                    print(f"[ZANGER] BIST getiri {xu_sembol}: {bist_getiri:.1f}%")
                    break
            except Exception as e:
                print(f"[ZANGER] {xu_sembol} hatasi: {e}")
                continue

        # Tüm batch'i tek seferde çek
        semboller = [f"{t}.IS" for t in hedef_liste]
        try:
            df_bulk = yf.download(
                semboller, period="6mo", interval="1d",
                progress=False, auto_adjust=True, group_by="ticker"
            )
        except Exception as e:
            print(f"[ZANGER] Bulk download hatası: {e}")
            return {"hisseler": [], "toplam": 0, "taranan": 0, "bist_getiri": round(bist_getiri,1), "batch": batch, "son_batch": True}

        sonuclar = []
        for ticker in hedef_liste:
            try:
                sembol = f"{ticker}.IS"
                if len(hedef_liste) == 1:
                    df = df_bulk
                else:
                    try:
                        df = df_bulk[sembol]
                    except Exception as e:
                        print(f"[ZANGER] {ticker} df erişim hatası: {e}")
                        continue

                if df is None or df.empty or len(df) < 30:
                    print(f"[ZANGER] {ticker} veri yetersiz: {len(df) if df is not None else 0}")
                    continue

                print(f"[ZANGER] {ticker} df kolonlar: {df.columns.tolist()}")
                kapanis = df["Close"].dropna().values
                yuksek  = df["High"].dropna().values
                dusuk   = df["Low"].dropna().values
                hacim   = df["Volume"].dropna().values
                n = min(len(kapanis), len(yuksek), len(dusuk), len(hacim))
                if n < 30:
                    continue
                kapanis, yuksek, dusuk, hacim = kapanis[-n:], yuksek[-n:], dusuk[-n:], hacim[-n:]

                gun_fiyat = float(kapanis[-1])

                # K1: 52H zirve
                zirve = float(np.max(yuksek))
                zirveye_uzaklik = (zirve - gun_fiyat) / zirve * 100
                k1 = zirveye_uzaklik <= 5.0

                # K2: Hacim patlaması
                hacim_ort = float(np.mean(hacim[-51:-1])) if n > 51 else float(np.mean(hacim[:-1]))
                hacim_oran = float(hacim[-1]) / hacim_ort if hacim_ort > 0 else 1
                k2 = hacim_oran >= 2.0

                # K3: RS
                hisse_getiri = (kapanis[-1] - kapanis[-min(63,n)]) / kapanis[-min(63,n)] * 100
                rs_fark = hisse_getiri - bist_getiri
                k3 = rs_fark > 0
                rs_skor = min(99, max(1, int(50 + rs_fark * 1.5)))

                # K4: Baz
                baz_gun = min(10, n-1)
                baz_genislik = (float(np.max(yuksek[-baz_gun:])) - float(np.min(dusuk[-baz_gun:]))) / float(np.min(dusuk[-baz_gun:])) * 100
                k4 = baz_genislik <= 8.0
                baz_tipi = "Sikisma" if baz_genislik <= 3 else "Dar Baz" if baz_genislik <= 6 else "Genis Baz"

                # K5: Kırılım
                k5 = gun_fiyat > float(yuksek[-2]) and hacim_oran >= 1.5

                kriterler = {"zirve_yakini": k1, "hacim_patlamasi": k2, "relative_guc": k3, "baz_olusumu": k4, "kirilim": k5}
                skor = sum(kriterler.values())
                print(f"[ZANGER] {ticker}: skor={skor} zirve={round(zirveye_uzaklik,1)}pct hacim={round(hacim_oran,1)}x rs={round(rs_fark,1)}pct baz={round(baz_genislik,1)}pct")
                if skor < 1:
                    continue

                guc = "MUKEMMEL" if skor==5 else "GUCLU" if skor==4 else "IYI" if skor==3 else "TAKIPTE"
                fiyat_degisim = round((kapanis[-1]-kapanis[-2])/kapanis[-2]*100, 2)
                try:
                    atr = round(float(np.mean([max(float(yuksek[i])-float(dusuk[i]), abs(float(yuksek[i])-float(kapanis[i-1])), abs(float(dusuk[i])-float(kapanis[i-1]))) for i in range(1,n)][-14:])), 2)
                except:
                    atr = 0.0

                sonuclar.append({
                    "ticker": ticker, "fiyat": round(float(gun_fiyat),2), "degisim": float(fiyat_degisim),
                    "skor": int(skor), "guc": guc,
                    "kriterler": {k: bool(v) for k,v in kriterler.items()},
                    "zirveye_uzaklik": round(float(zirveye_uzaklik),1),
                    "zirve_52h": round(float(zirve),2),
                    "hacim_oran": round(float(hacim_oran),1),
                    "rs_skor": int(rs_skor),
                    "rs_fark": round(float(rs_fark),1),
                    "baz_tipi": str(baz_tipi),
                    "baz_genislik": round(float(baz_genislik),1),
                    "dun_yuksek": round(float(yuksek[-2]),2),
                    "atr": float(atr),
                    "hisse_getiri_3ay": round(float(hisse_getiri),1),
                })
            except Exception as e:
                print(f"[ZANGER] {ticker}: {e}")
                continue

        sonuclar.sort(key=lambda x: (-x["skor"], -x["rs_skor"]))
        print(f"[ZANGER] Batch {batch} tamamlandı: {len(sonuclar)} sonuç")
        return {
            "hisseler":    sonuclar,
            "toplam":      int(len(sonuclar)),
            "taranan":     int(len(hedef_liste)),
            "bist_getiri": float(round(bist_getiri, 1)),
            "batch":       int(batch),
            "son_batch":   bool(bitis >= len(BIST100)),
        }

    sonuc = await run_in_threadpool(tara)
    return sonuc
