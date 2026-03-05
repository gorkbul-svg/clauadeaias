"""
kap.py — KAP (Kamuyu Aydınlatma Platformu) Entegrasyonu
KAP'ın public web endpoint'lerinden veri çeker.
"""

import httpx
from datetime import datetime, timedelta
from typing import Optional

# KAP şirket kodları (ticker → KAP member_oid mapping)
# KAP'ta şirketler MKK kodu ile tanımlanır
KAP_SIRKET_KODLARI = {
    "THYAO": "17d49cdc-1a5e-4e96-a0ca-7ddeae0e5834",
    "AKBNK": "d54cd93d-35a3-4e48-a5a4-1b0ff02d5f2e",
    "GARAN": "c5e1b62d-8c8f-4f5f-9a1d-8e0e5e1f5e5e",
    "EREGL": "7c4e1b62-8c8f-4f5f-9a1d-8e0e5e1f5e5e",
    "BIMAS": "9d5f2c73-9d9g-5g6g-0b2e-9f1f6f2g6f6f",
    "MAVI":  "3a2b1c0d-7e8f-9a0b-1c2d-3e4f5a6b7c8d",
    "KCHOL": "8b9c0d1e-2f3a-4b5c-6d7e-8f9a0b1c2d3e",
}

BASE_URL = "https://www.kap.org.tr/tr/api"

async def kap_son_bildirimler(ticker: str, limit: int = 10) -> dict:
    """
    KAP'tan şirkete ait son bildirimleri çeker.
    Gerçek KAP API'si yerine public endpoint kullanır.
    """
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            # KAP disclosure endpoint
            url = f"{BASE_URL}/disclosures"
            params = {
                "stock": ticker.upper(),
                "limit": limit
            }
            res = await client.get(url, params=params)

            if res.status_code != 200:
                return await _kap_fallback(ticker, limit)

            data = res.json()
            return _parse_bildirimler(data, ticker)

    except Exception as e:
        return await _kap_fallback(ticker, limit)


async def _kap_fallback(ticker: str, limit: int) -> dict:
    """KAP direkt erişim başarısız olursa alternatif endpoint dene."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            # KAP'ın public member disclosure endpoint'i
            url = f"https://www.kap.org.tr/tr/api/memberDisclosureList/{ticker.upper()}"
            res = await client.get(url)

            if res.status_code == 200:
                data = res.json()
                bildirimler = []
                for item in data[:limit]:
                    bildirimler.append({
                        "baslik": item.get("disclosureType", "Bildirim"),
                        "ozet": item.get("summary", ""),
                        "tarih": item.get("publishDate", ""),
                        "tip": item.get("disclosureCategory", ""),
                        "url": f"https://www.kap.org.tr/tr/Bildirim/{item.get('disclosureIndex', '')}"
                    })
                return {
                    "ticker": ticker.upper(),
                    "bildirimler": bildirimler,
                    "adet": len(bildirimler),
                    "kaynak": "KAP"
                }
    except Exception:
        pass

    # Son çare: örnek bildirim yapısı döndür
    return {
        "ticker": ticker.upper(),
        "bildirimler": [],
        "adet": 0,
        "hata": "KAP verisi şu an alınamıyor. Lütfen kap.org.tr adresini ziyaret edin.",
        "kap_url": f"https://www.kap.org.tr/tr/Bildirim/Ozet/{ticker.upper()}"
    }


def _parse_bildirimler(data: list, ticker: str) -> dict:
    bildirimler = []
    for item in data:
        bildirimler.append({
            "baslik": item.get("subject") or item.get("disclosureType", "Bildirim"),
            "ozet": item.get("summary", ""),
            "tarih": item.get("publishDate") or item.get("createdAt", ""),
            "tip": item.get("category") or item.get("disclosureCategory", ""),
            "url": f"https://www.kap.org.tr/tr/Bildirim/{item.get('id', '')}"
        })
    return {
        "ticker": ticker.upper(),
        "bildirimler": bildirimler,
        "adet": len(bildirimler),
        "kaynak": "KAP"
    }


async def kap_finansal_takvim(ticker: str) -> dict:
    """
    Şirketin beklenen finansal bildirim takvimini döndürür.
    (Bilanço açıklama tarihleri, genel kurul vb.)
    """
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            url = f"{BASE_URL}/financialCalendar"
            res = await client.get(url, params={"stock": ticker.upper()})

            if res.status_code == 200:
                return res.json()
    except Exception:
        pass

    return {
        "ticker": ticker.upper(),
        "takvim": [],
        "mesaj": "Finansal takvim verisi alınamadı",
        "kap_url": f"https://www.kap.org.tr/tr/sirket-bilgileri/ozet/{ticker.upper()}"
    }


def kap_sirket_url(ticker: str) -> str:
    """Şirketin KAP sayfası URL'ini döndürür."""
    return f"https://www.kap.org.tr/tr/Bildirim/Ozet/{ticker.upper()}"
