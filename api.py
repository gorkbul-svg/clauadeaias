"""
Adım 4a: FastAPI Backend
------------------------
Next.js frontend'i için REST API.
Agent'ı HTTP endpoint olarak sunar.

Kurulum:
    pip install fastapi uvicorn anthropic yfinance pandas numpy

Çalıştırma:
    uvicorn api:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import json
import os

from anthropic import Anthropic
from data.yahoo_finance import (
    get_stock_price, get_financials,
    get_technical_indicators, get_news_sentiment, compare_sector_peers
)
from data.risk_profili import ORNEK_PROFILLER, PROFIL_PARAMETRELERI, hisse_profile_uygunluk
from agent import TOOLS, execute_tool, SYSTEM_PROMPT, BISTAgent

app = FastAPI(title="BIST Araştırma Agent API", version="1.0.0")

# CORS — GitHub Pages + local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tüm originlere izin ver
    allow_methods=["*"],
    allow_headers=["*"],
)

# Aktif oturumlar (production'da Redis kullanılır)
aktif_oturumlar: dict[str, BISTAgent] = {}


# ── Request/Response Modelleri ──────────────────────

class ChatRequest(BaseModel):
    soru: str
    oturum_id: str
    kullanici_id: Optional[str] = None

class ChatResponse(BaseModel):
    yanit: str
    oturum_id: str

class StockRequest(BaseModel):
    ticker: str

class PortfolioRequest(BaseModel):
    tickers: list[str]
    kullanici_id: Optional[str] = None


# ── Endpoints ──────────────────────────────────────

@app.get("/")
def root():
    return {"mesaj": "BIST Araştırma Agent API çalışıyor", "versiyon": "1.0.0"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """Ana chat endpoint'i. Agent ile konuşma başlatır/devam ettirir."""
    oturum_id = req.oturum_id

    # Yeni oturum oluştur veya mevcut oturumu getir
    if oturum_id not in aktif_oturumlar:
        aktif_oturumlar[oturum_id] = BISTAgent(
            kullanici_id=req.kullanici_id,
            verbose=False
        )

    agent = aktif_oturumlar[oturum_id]

    try:
        yanit = agent.sor(req.soru)
        return ChatResponse(yanit=yanit, oturum_id=oturum_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/chat/{oturum_id}")
def oturumu_sifirla(oturum_id: str):
    """Konuşma geçmişini temizler."""
    if oturum_id in aktif_oturumlar:
        aktif_oturumlar[oturum_id].sifirla()
    return {"mesaj": "Oturum sıfırlandı"}


@app.get("/stock/{ticker}")
def hisse_ozet(ticker: str):
    """Hisse özet kartı için anlık veri."""
    try:
        fiyat    = get_stock_price(ticker)
        finansal = get_financials(ticker)
        teknik   = get_technical_indicators(ticker)
        return {
            "ticker": ticker.upper(),
            "fiyat": fiyat,
            "finansal": finansal,
            "teknik": teknik
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stock/{ticker}/full")
def hisse_tam_analiz(ticker: str):
    """Tüm verileri tek seferde döndürür."""
    try:
        return {
            "fiyat":   get_stock_price(ticker),
            "finansal": get_financials(ticker),
            "teknik":   get_technical_indicators(ticker),
            "haberler": get_news_sentiment(ticker),
            "sektor":   compare_sector_peers(ticker)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/portfolio")
def portfoy_analizi(req: PortfolioRequest):
    """Çoklu hisse portföy analizi."""
    from agent import _portfolio_analysis_tool
    try:
        result = _portfolio_analysis_tool(req.tickers, req.kullanici_id or "")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/profiles")
def profilleri_listele():
    """Mevcut yatırımcı profillerini döndürür."""
    return {
        isim: {
            "kullanici_id": p.kullanici_id,
            "ad": p.ad,
            "risk_toleransi": p.risk_toleransi,
            "risk_skoru": p.risk_skoru,
            "maks_kayip": p.maks_kayip_toleransi,
            "aciklama": PROFIL_PARAMETRELERI[p.risk_toleransi]["aciklama"]
        }
        for isim, p in ORNEK_PROFILLER.items()
    }
