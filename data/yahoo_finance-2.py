"""
Adım 1: Yahoo Finance API Entegrasyonu
--------------------------------------
yfinance üzerinden gerçek BIST verisi çeker.
BIST hisseleri Yahoo Finance'de ".IS" uzantısıyla bulunur.
Örnek: THYAO → THYAO.IS, AKBNK → AKBNK.IS

Kurulum:
    pip install yfinance pandas numpy
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional
import warnings
warnings.filterwarnings("ignore")


def bist_ticker(ticker: str) -> str:
    """THYAO → THYAO.IS dönüşümü"""
    ticker = ticker.upper().strip()
    if not ticker.endswith(".IS"):
        ticker += ".IS"
    return ticker


# ─────────────────────────────────────────────
# 1. ANLLIK FİYAT VERİSİ
# ─────────────────────────────────────────────

def get_stock_price(ticker: str) -> dict:
    """
    Hissenin anlık fiyat bilgisini getirir.
    
    Döndürür:
        ticker, sirket, fiyat, degisim_yuzde, hacim,
        haftalik_dusuk_52, haftalik_yuksek_52, piyasa_degeri
    """
    try:
        stock = yf.Ticker(bist_ticker(ticker))
        info = stock.info

        # Fiyat bilgisi
        fiyat = info.get("currentPrice") or info.get("regularMarketPrice", 0)
        onceki_kapanis = info.get("previousClose", fiyat)
        degisim = ((fiyat - onceki_kapanis) / onceki_kapanis * 100) if onceki_kapanis else 0

        return {
            "ticker": ticker.upper(),
            "sirket": info.get("longName", ticker),
            "fiyat": round(fiyat, 2),
            "para_birimi": info.get("currency", "TRY"),
            "degisim_yuzde": round(degisim, 2),
            "hacim": info.get("regularMarketVolume", 0),
            "ortalama_hacim_10g": info.get("averageVolume10days", 0),
            "haftalik_dusuk_52": info.get("fiftyTwoWeekLow", 0),
            "haftalik_yuksek_52": info.get("fiftyTwoWeekHigh", 0),
            "piyasa_degeri_try": info.get("marketCap", 0),
            "tarih": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "kaynak": "Yahoo Finance"
        }

    except Exception as e:
        return {"hata": str(e), "ticker": ticker}


# ─────────────────────────────────────────────
# 2. TEMEL FİNANSAL VERİLER
# ─────────────────────────────────────────────

def get_financials(ticker: str, period: str = "yillik") -> dict:
    """
    Hissenin temel finansal metriklerini getirir.
    
    Döndürür:
        F/K, PD/DD, ROE, net kar marjı, borç/özsermaye,
        gelir büyümesi, EPS, temettü verimi
    """
    try:
        stock = yf.Ticker(bist_ticker(ticker))
        info = stock.info

        # Kar/zarar tablosu
        financials = stock.financials  # Yıllık
        quarterly = stock.quarterly_financials  # Çeyreklik

        tablo = quarterly if period == "son_ceyrek" else financials

        # Net kar büyümesi (son 2 dönem karşılaştırması)
        kar_buyume = None
        if tablo is not None and not tablo.empty and "Net Income" in tablo.index:
            karlar = tablo.loc["Net Income"].dropna()
            if len(karlar) >= 2:
                yeni, eski = karlar.iloc[0], karlar.iloc[1]
                if eski != 0:
                    kar_buyume = round((yeni - eski) / abs(eski) * 100, 1)

        return {
            "ticker": ticker.upper(),
            "FK_orani": round(info.get("trailingPE", 0) or 0, 2),
            "ileri_FK": round(info.get("forwardPE", 0) or 0, 2),
            "PD_DD": round(info.get("priceToBook", 0) or 0, 2),
            "ROE_yuzde": round((info.get("returnOnEquity", 0) or 0) * 100, 2),
            "ROA_yuzde": round((info.get("returnOnAssets", 0) or 0) * 100, 2),
            "net_kar_marji_yuzde": round((info.get("profitMargins", 0) or 0) * 100, 2),
            "borc_ozsermaye": round(info.get("debtToEquity", 0) or 0, 2),
            "gelir_buyume_yuzde": round((info.get("revenueGrowth", 0) or 0) * 100, 2),
            "kar_buyume_yuzde": kar_buyume,
            "EPS": round(info.get("trailingEps", 0) or 0, 2),
            "temettü_verimi_yuzde": round((info.get("dividendYield", 0) or 0) * 100, 2),
            "serbest_nakit_akisi": info.get("freeCashflow"),
            "donem": "Çeyreklik" if period == "son_ceyrek" else "Yıllık"
        }

    except Exception as e:
        return {"hata": str(e), "ticker": ticker}


# ─────────────────────────────────────────────
# 3. TEKNİK ANALİZ GÖSTERGELERİ
# ─────────────────────────────────────────────

def get_technical_indicators(ticker: str, period_days: int = 200) -> dict:
    """
    Teknik analiz göstergelerini hesaplar.
    
    Döndürür:
        RSI, MACD, MA20/50/200, Bollinger Bantları, trend yönü
    """
    try:
        stock = yf.Ticker(bist_ticker(ticker))
        # Yeterli geçmiş veri için 1 yıl al
        df = stock.history(period="1y")

        if df.empty:
            return {"hata": "Geçmiş veri bulunamadı", "ticker": ticker}

        close = df["Close"]
        son_fiyat = close.iloc[-1]

        # Hareketli Ortalamalar
        ma20  = close.rolling(20).mean().iloc[-1]
        ma50  = close.rolling(50).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else None

        # RSI (14 günlük)
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = (100 - (100 / (1 + rs))).iloc[-1]

        # MACD (12, 26, 9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line   = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_val    = macd_line.iloc[-1]
        signal_val  = signal_line.iloc[-1]
        macd_yorum  = "Al sinyali" if macd_val > signal_val else "Sat sinyali"

        # Bollinger Bantları (20 günlük, 2 std)
        ma20_series = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_ust = (ma20_series + 2 * std20).iloc[-1]
        bb_alt = (ma20_series - 2 * std20).iloc[-1]

        # Trend yönü
        trend = "Yükseliş" if son_fiyat > ma50 > ma200 else \
                "Düşüş"    if son_fiyat < ma50 < (ma200 or ma50) else "Yatay"

        # RSI yorumu
        rsi_yorum = "Aşırı alım (dikkat)" if rsi > 70 else \
                    "Aşırı satım (fırsat olabilir)" if rsi < 30 else "Normal bölge"

        return {
            "ticker": ticker.upper(),
            "son_fiyat": round(son_fiyat, 2),
            "RSI_14": round(rsi, 1),
            "RSI_yorum": rsi_yorum,
            "MACD": round(macd_val, 3),
            "MACD_sinyal": round(signal_val, 3),
            "MACD_yorum": macd_yorum,
            "MA20":  round(ma20, 2),
            "MA50":  round(ma50, 2),
            "MA200": round(ma200, 2) if ma200 else None,
            "bollinger_ust": round(bb_ust, 2),
            "bollinger_alt": round(bb_alt, 2),
            "bollinger_yuzde": round((son_fiyat - bb_alt) / (bb_ust - bb_alt) * 100, 1),
            "trend": trend,
            "veri_gun_sayisi": len(close)
        }

    except Exception as e:
        return {"hata": str(e), "ticker": ticker}


# ─────────────────────────────────────────────
# 4. GEÇMİŞ FİYAT VERİSİ (GRAFİK İÇİN)
# ─────────────────────────────────────────────

def get_price_history(ticker: str, period: str = "3mo") -> dict:
    """
    Hissenin geçmiş fiyat verisini getirir.
    period: '1mo', '3mo', '6mo', '1y', '2y'
    """
    try:
        stock = yf.Ticker(bist_ticker(ticker))
        df = stock.history(period=period)

        if df.empty:
            return {"hata": "Veri bulunamadı", "ticker": ticker}

        # Günlük veri
        tarihler = df.index.strftime("%Y-%m-%d").tolist()
        kapanis  = [round(float(x), 2) for x in df["Close"].tolist()]
        hacimler = [int(x) for x in df["Volume"].tolist()]
        yuksek   = [round(float(x), 2) for x in df["High"].tolist()]
        dusuk    = [round(float(x), 2) for x in df["Low"].tolist()]

        # Özet istatistikler
        ilk_fiyat = kapanis[0] if kapanis else 0
        son_fiyat = kapanis[-1] if kapanis else 0
        degisim_yuzde = round((son_fiyat - ilk_fiyat) / ilk_fiyat * 100, 2) if ilk_fiyat else 0

        return {
            "ticker": ticker.upper(),
            "period": period,
            "tarihler": tarihler,
            "kapanis": kapanis,
            "yuksek": yuksek,
            "dusuk": dusuk,
            "hacimler": hacimler,
            "ilk_fiyat": ilk_fiyat,
            "son_fiyat": son_fiyat,
            "degisim_yuzde": degisim_yuzde,
            "min_fiyat": round(min(kapanis), 2),
            "max_fiyat": round(max(kapanis), 2),
            "veri_sayisi": len(tarihler)
        }

    except Exception as e:
        return {"hata": str(e), "ticker": ticker}


# ─────────────────────────────────────────────
# 4. HABER & SENTIMENT
# ─────────────────────────────────────────────

def get_news_sentiment(ticker: str, days: int = 7) -> dict:
    """
    Yahoo Finance'den son haberleri çeker.
    Basit keyword-based sentiment skoru hesaplar.
    
    Not: Gerçek NLP için transformers/FinBERT entegre edilebilir.
    """
    try:
        stock = yf.Ticker(bist_ticker(ticker))
        news = stock.news or []

        # Son N gündeki haberleri filtrele
        threshold = datetime.now() - timedelta(days=days)
        recent_news = []
        for item in news:
            pub_time = item.get("providerPublishTime", 0)
            if pub_time and datetime.fromtimestamp(pub_time) >= threshold:
                recent_news.append(item)

        # Basit keyword sentiment
        pozitif_kelimeler = ["artış", "yükseliş", "kâr", "büyüme", "rekor",
                             "güçlü", "olumlu", "beat", "growth", "record",
                             "profit", "rise", "gain", "strong", "up"]
        negatif_kelimeler = ["düşüş", "zarar", "kayıp", "risk", "uyarı",
                             "endişe", "loss", "decline", "fall", "weak",
                             "miss", "risk", "concern", "down", "drop"]

        toplam_puan = 0
        haberler = []
        for item in recent_news[:10]:
            baslik = item.get("title", "")
            baslik_lower = baslik.lower()
            puan = sum(1 for k in pozitif_kelimeler if k in baslik_lower) - \
                   sum(1 for k in negatif_kelimeler if k in baslik_lower)
            toplam_puan += puan
            haberler.append({
                "baslik": baslik,
                "kaynak": item.get("publisher", ""),
                "tarih": datetime.fromtimestamp(
                    item.get("providerPublishTime", 0)
                ).strftime("%d.%m.%Y") if item.get("providerPublishTime") else "",
                "sentiment": "pozitif" if puan > 0 else "negatif" if puan < 0 else "nötr"
            })

        n = len(haberler) or 1
        ort_puan = toplam_puan / n
        sentiment_label = "Pozitif" if ort_puan > 0.3 else \
                          "Negatif" if ort_puan < -0.3 else "Nötr"

        return {
            "ticker": ticker.upper(),
            "sentiment_skoru": round(ort_puan, 2),
            "sentiment_label": sentiment_label,
            "haber_sayisi": len(haberler),
            "haberler": haberler,
            "analiz_donemi_gun": days
        }

    except Exception as e:
        return {"hata": str(e), "ticker": ticker}


# ─────────────────────────────────────────────
# 5. SEKTÖR KARŞILAŞTIRMASI
# ─────────────────────────────────────────────

# BIST sektör grupları — genişletilebilir
SEKTOR_GRUPLARI = {
    "THYAO": {"sektor": "Havacılık", "rakipler": ["PGSUS", "HAVAS"]},
    "PGSUS": {"sektor": "Havacılık", "rakipler": ["THYAO", "HAVAS"]},
    "AKBNK": {"sektor": "Bankacılık", "rakipler": ["GARAN", "ISCTR", "YKBNK"]},
    "GARAN": {"sektor": "Bankacılık", "rakipler": ["AKBNK", "ISCTR", "YKBNK"]},
    "ISCTR": {"sektor": "Bankacılık", "rakipler": ["AKBNK", "GARAN", "YKBNK"]},
    "YKBNK": {"sektor": "Bankacılık", "rakipler": ["AKBNK", "GARAN", "ISCTR"]},
    "EREGL": {"sektor": "Demir-Çelik", "rakipler": ["KRDMD", "CEMTS"]},
    "KRDMD": {"sektor": "Demir-Çelik", "rakipler": ["EREGL", "CEMTS"]},
    "BIMAS": {"sektor": "Perakende", "rakipler": ["MGROS", "SOKM"]},
    "MGROS": {"sektor": "Perakende", "rakipler": ["BIMAS", "SOKM"]},
    "SISE":  {"sektor": "Cam & İnşaat", "rakipler": ["TRKCM", "ANACM"]},
    "KCHOL": {"sektor": "Holding", "rakipler": ["SAHOL", "TKFEN"]},
    "SAHOL": {"sektor": "Holding", "rakipler": ["KCHOL", "TKFEN"]},
    "TUPRS": {"sektor": "Petrokimya", "rakipler": ["PETKM", "AEFES"]},
}

def compare_sector_peers(ticker: str) -> dict:
    """
    Hisseyi sektör rakipleriyle karşılaştırır.
    Her rakip için temel metrikler çekilir.
    """
    ticker = ticker.upper()
    sektor_bilgi = SEKTOR_GRUPLARI.get(ticker, {
        "sektor": "Diğer",
        "rakipler": []
    })

    rakipler_data = []
    for rakip in sektor_bilgi["rakipler"]:
        try:
            rakip_info = yf.Ticker(bist_ticker(rakip)).info
            rakipler_data.append({
                "ticker": rakip,
                "sirket": rakip_info.get("longName", rakip),
                "FK": round(rakip_info.get("trailingPE", 0) or 0, 1),
                "PD_DD": round(rakip_info.get("priceToBook", 0) or 0, 2),
                "ROE_yuzde": round((rakip_info.get("returnOnEquity", 0) or 0) * 100, 1),
                "piyasa_degeri": rakip_info.get("marketCap", 0)
            })
        except Exception:
            rakipler_data.append({"ticker": rakip, "hata": "veri alınamadı"})

    # Sektör ortalaması
    gecerli = [r for r in rakipler_data if "FK" in r and r["FK"] > 0]
    sektor_ort_FK = round(
        sum(r["FK"] for r in gecerli) / len(gecerli), 1
    ) if gecerli else None

    return {
        "ticker": ticker,
        "sektor": sektor_bilgi["sektor"],
        "sektor_ort_FK": sektor_ort_FK,
        "rakipler": rakipler_data
    }


# ─────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import json

    ticker = "THYAO"
    print(f"\n{'='*50}")
    print(f"  {ticker} TEST")
    print(f"{'='*50}")

    print("\n[1] Fiyat:")
    print(json.dumps(get_stock_price(ticker), ensure_ascii=False, indent=2))

    print("\n[2] Finansallar:")
    print(json.dumps(get_financials(ticker), ensure_ascii=False, indent=2))

    print("\n[3] Teknik:")
    print(json.dumps(get_technical_indicators(ticker), ensure_ascii=False, indent=2))

    print("\n[4] Haberler:")
    print(json.dumps(get_news_sentiment(ticker, days=7), ensure_ascii=False, indent=2))

    print("\n[5] Sektör:")
    print(json.dumps(compare_sector_peers(ticker), ensure_ascii=False, indent=2))
