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
