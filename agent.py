"""
Adım 3: Çoklu Hisse Portföy Analizi + Ana Agent
-------------------------------------------------
Claude Tool Use API ile birleşik BIST araştırma agent'ı.
Gerçek Yahoo Finance verisi + risk profili entegrasyonu.

Kurulum:
    pip install anthropic yfinance pandas numpy
    export ANTHROPIC_API_KEY="sk-ant-..."

Kullanım:
    python agent.py
"""

import json
import os
from anthropic import Anthropic

# Modüller (aynı proje içinde)
from data.yahoo_finance import (
    get_stock_price,
    get_financials,
    get_technical_indicators,
    get_news_sentiment,
    compare_sector_peers,
)
from data.risk_profili import (
    RiskProfili,
    ORNEK_PROFILLER,
    PROFIL_PARAMETRELERI,
    hisse_profile_uygunluk,
    profil_yukle,
)

client = Anthropic()


# ─────────────────────────────────────────────
# TOOL TANIMLARI
# ─────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_stock_price",
        "description": "BIST hissesinin anlık fiyat, hacim ve 52 haftalık aralık bilgisini getirir.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "BIST kodu (örn: THYAO, AKBNK)"}
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_financials",
        "description": "Hissenin F/K, PD/DD, ROE, kar büyümesi gibi temel finansal metriklerini getirir.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "period": {
                    "type": "string",
                    "enum": ["son_ceyrek", "yillik"],
                    "description": "Analiz dönemi (varsayılan: yillik)"
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_technical_indicators",
        "description": "RSI, MACD, Hareketli Ortalamalar ve Bollinger Bantlarını hesaplar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"}
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_news_sentiment",
        "description": "Son haberleri ve piyasa duyarlılığını (pozitif/negatif/nötr) döndürür.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "days": {"type": "integer", "description": "Kaç günlük haber (varsayılan: 7)"}
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "compare_sector_peers",
        "description": "Hisseyi sektör rakipleriyle karşılaştırır.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"}
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "check_profile_fit",
        "description": (
            "Bir hissenin yatırımcı risk profiline uygunluğunu değerlendirir. "
            "Profil bilgisi ve hisse metriklerini birleştirerek kişiselleştirilmiş yorum yapar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "kullanici_id": {"type": "string", "description": "Yatırımcı profil ID'si"}
            },
            "required": ["ticker", "kullanici_id"]
        }
    },
    {
        "name": "portfolio_analysis",
        "description": (
            "Birden fazla hissenin portföy düzeyinde analizini yapar. "
            "Çeşitlendirme, korelasyon, risk dağılımı ve ağırlık önerisi sunar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tickers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Analiz edilecek hisse listesi (en fazla 8)"
                },
                "kullanici_id": {"type": "string", "description": "Yatırımcı profil ID'si"}
            },
            "required": ["tickers"]
        }
    }
]


# ─────────────────────────────────────────────
# TOOL EXECUTOR
# ─────────────────────────────────────────────

def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Tool çağrısını gerçek fonksiyonlara yönlendirir."""

    try:
        if tool_name == "get_stock_price":
            result = get_stock_price(tool_input["ticker"])

        elif tool_name == "get_financials":
            result = get_financials(
                tool_input["ticker"],
                tool_input.get("period", "yillik")
            )

        elif tool_name == "get_technical_indicators":
            result = get_technical_indicators(tool_input["ticker"])

        elif tool_name == "get_news_sentiment":
            result = get_news_sentiment(
                tool_input["ticker"],
                tool_input.get("days", 7)
            )

        elif tool_name == "compare_sector_peers":
            result = compare_sector_peers(tool_input["ticker"])

        elif tool_name == "check_profile_fit":
            result = _profile_fit_tool(
                tool_input["ticker"],
                tool_input.get("kullanici_id", "")
            )

        elif tool_name == "portfolio_analysis":
            result = _portfolio_analysis_tool(
                tool_input["tickers"],
                tool_input.get("kullanici_id", "")
            )

        else:
            result = {"hata": f"Bilinmeyen tool: {tool_name}"}

    except Exception as e:
        result = {"hata": str(e), "tool": tool_name}

    return json.dumps(result, ensure_ascii=False, indent=2)


def _profile_fit_tool(ticker: str, kullanici_id: str) -> dict:
    """Hisseyi profille karşılaştırır."""
    # Profil yükle
    profil = None
    for isim, p in ORNEK_PROFILLER.items():
        if p.kullanici_id == kullanici_id or isim == kullanici_id:
            profil = p
            break
    if not profil:
        profil = ORNEK_PROFILLER.get("elif_buyume")  # Varsayılan

    finansallar = get_financials(ticker)
    teknik = get_technical_indicators(ticker)
    uygunluk = hisse_profile_uygunluk(profil, finansallar, teknik)

    return {
        "ticker": ticker.upper(),
        "yatirimci": profil.ad,
        "risk_toleransi": profil.risk_toleransi,
        "risk_skoru": profil.risk_skoru,
        **uygunluk
    }


def _portfolio_analysis_tool(tickers: list, kullanici_id: str) -> dict:
    """Çoklu hisse portföy analizi."""
    tickers = [t.upper() for t in tickers[:8]]  # Max 8 hisse

    # Profil
    profil = None
    for isim, p in ORNEK_PROFILLER.items():
        if p.kullanici_id == kullanici_id or isim == kullanici_id:
            profil = p
            break
    if not profil:
        profil = ORNEK_PROFILLER.get("elif_buyume")

    # Her hisse için temel veri topla
    hisseler = []
    sektorler = set()
    toplam_uygunluk = 0

    for ticker in tickers:
        try:
            fiyat    = get_stock_price(ticker)
            finansal = get_financials(ticker)
            teknik   = get_technical_indicators(ticker)
            uygunluk = hisse_profile_uygunluk(profil, finansal, teknik)

            sektor_bilgi = __import__(
                "data.yahoo_finance", fromlist=["SEKTOR_GRUPLARI"]
            ).SEKTOR_GRUPLARI.get(ticker, {})
            sektor = sektor_bilgi.get("sektor", "Diğer")
            sektorler.add(sektor)

            hisseler.append({
                "ticker": ticker,
                "sirket": fiyat.get("sirket", ticker),
                "sektor": sektor,
                "fiyat": fiyat.get("fiyat"),
                "degisim_yuzde": fiyat.get("degisim_yuzde"),
                "FK": finansal.get("FK_orani"),
                "ROE": finansal.get("ROE_yuzde"),
                "trend": teknik.get("trend"),
                "RSI": teknik.get("RSI_14"),
                "uygunluk_skoru": uygunluk["uygunluk_skoru"],
                "uygunluk_seviye": uygunluk["seviye"],
            })
            toplam_uygunluk += uygunluk["uygunluk_skoru"]

        except Exception as e:
            hisseler.append({"ticker": ticker, "hata": str(e)})

    # Çeşitlendirme skoru
    gecerli = [h for h in hisseler if "hata" not in h]
    n = len(gecerli)
    sektor_sayisi = len(sektorler)
    cesitlendirme_skoru = min(100, sektor_sayisi * 25)  # Her farklı sektör +25 puan

    # Eşit ağırlık önerisi (gelişmiş versiyonda Markowitz optimizasyonu kullanılabilir)
    esit_agirlik = round(100 / n, 1) if n > 0 else 0
    agirlik_onerileri = {h["ticker"]: esit_agirlik for h in gecerli}

    # Risk uyarıları
    uyarilar = []
    if sektor_sayisi < 2:
        uyarilar.append("⚠️ Tek sektörde yoğunlaşma riski var. Farklı sektörler ekleyin.")
    if n < 3:
        uyarilar.append("⚠️ Portföy çok az hisseden oluşuyor. En az 5-8 hisse önerilir.")
    if n > 0:
        ort_uygunluk = toplam_uygunluk / n
        if ort_uygunluk < 50:
            uyarilar.append(f"⚠️ Portföyün risk profilinize uygunluğu düşük (ort: {ort_uygunluk:.0f}/100)")

    return {
        "portfoy_ozeti": {
            "hisse_sayisi": n,
            "sektor_sayisi": sektor_sayisi,
            "sektorler": list(sektorler),
            "cesitlendirme_skoru": cesitlendirme_skoru,
            "profil_uygunluk_ort": round(toplam_uygunluk / n, 1) if n > 0 else 0,
            "yatirimci": profil.ad,
            "risk_toleransi": profil.risk_toleransi
        },
        "hisseler": hisseler,
        "agirlik_onerileri": agirlik_onerileri,
        "uyarilar": uyarilar
    }


# ─────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """Sen deneyimli bir BIST araştırma analistisin. 
Bireysel yatırımcılara kişiselleştirilmiş, kapsamlı hisse araştırması yapıyorsun.

## Analiz Çerçeven

Tek hisse için:
1. Fiyat ve genel durum (get_stock_price)
2. Temel finansallar: F/K, ROE, büyüme (get_financials)
3. Teknik göstergeler: RSI, MACD, trend (get_technical_indicators)
4. Haber duyarlılığı (get_news_sentiment)
5. Sektör karşılaştırması (compare_sector_peers)
6. Profil uygunluğu — kullanıcı_id varsa (check_profile_fit)

Portföy için:
- portfolio_analysis tool'unu çalıştır
- Çeşitlendirme ve risk dağılımını yorumla

## Yanıt Formatı
- Net bir özet ile başla
- Güçlü yönler ve riskler ayrı ayrı
- Rakamları daima yorumla (sadece sayı verme)
- Profil uygunluğunu belirt
- Her yanıtın sonuna: "⚠️ Bu analiz yatırım tavsiyesi değildir."

## Dil
- Türkçe yanıt ver
- Teknik terimlerin açıklamasını parantez içinde ekle
- Anlaşılır, samimi bir ton kullan"""


# ─────────────────────────────────────────────
# AGENT DÖNGÜSÜ
# ─────────────────────────────────────────────

class BISTAgent:
    """BIST Araştırma Agent'ı — oturum bazlı konuşma geçmişi tutar."""

    def __init__(self, kullanici_id: str = None, verbose: bool = True):
        self.kullanici_id = kullanici_id
        self.verbose = verbose
        self.mesajlar = []
        self.sistem_prompt = SYSTEM_PROMPT

        # Kullanıcı profili varsa system prompt'a ekle
        if kullanici_id:
            profil = None
            for isim, p in ORNEK_PROFILLER.items():
                if p.kullanici_id == kullanici_id or isim == kullanici_id:
                    profil = p
                    break
            if profil:
                params = PROFIL_PARAMETRELERI[profil.risk_toleransi]
                self.sistem_prompt += f"""

## Aktif Kullanıcı Profili
- Ad: {profil.ad}
- Risk Toleransı: {profil.risk_toleransi} (Skor: {profil.risk_skoru}/100)
- Deneyim: {profil.deneyim}
- Yatırım Ufku: {profil.yatirim_ufku}
- Hedefler: {', '.join(profil.hedefler)}
- Max Tolere Edilebilir Kayıp: %{profil.maks_kayip_toleransi}
- Tercih Edilen Sektörler: {', '.join(profil.tercih_edilen_sektorler) or 'Belirtilmemiş'}
- Profil Özeti: {params['aciklama']}

Her hisse değerlendirmesinde bu profili göz önünde bulundur.
Kullanıcının ID'si: {kullanici_id}"""

    def sor(self, soru: str) -> str:
        """Kullanıcı sorusunu işler, tool'ları çalıştırır, yanıt döndürür."""

        self.mesajlar.append({"role": "user", "content": soru})

        if self.verbose:
            print(f"\n{'─'*55}")
            print(f"👤 {soru}")
            print(f"{'─'*55}")

        iteration = 0
        max_iterations = 12

        while iteration < max_iterations:
            iteration += 1

            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=4096,
                system=self.sistem_prompt,
                tools=TOOLS,
                messages=self.mesajlar
            )

            # Cevap tamamlandı
            if response.stop_reason == "end_turn":
                final = "".join(
                    block.text for block in response.content
                    if hasattr(block, "text")
                )
                self.mesajlar.append({"role": "assistant", "content": response.content})
                return final

            # Tool çağrısı
            if response.stop_reason == "tool_use":
                self.mesajlar.append({"role": "assistant", "content": response.content})

                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        if self.verbose:
                            print(f"  🔧 {block.name}({json.dumps(block.input, ensure_ascii=False)})")

                        sonuc = execute_tool(block.name, block.input)

                        if self.verbose:
                            print(f"  ✓ Veri alındı")

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": sonuc
                        })

                self.mesajlar.append({"role": "user", "content": tool_results})

        return "Agent maksimum adım sayısına ulaştı."

    def sifirla(self):
        """Konuşma geçmişini temizler."""
        self.mesajlar = []


# ─────────────────────────────────────────────
# DEMO
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*55)
    print("  BIST ARAŞTIRMA AGENT — Tam Entegrasyon")
    print("="*55)

    # ── Demo 1: Muhafazakâr yatırımcı, tek hisse ──
    print("\n\n📌 DEMO 1: Muhafazakâr Yatırımcı — AKBNK Analizi")
    agent_ahmet = BISTAgent(kullanici_id="ahmet_muhafazakar", verbose=True)
    yanit = agent_ahmet.sor("AKBNK hissesini profilime göre değerlendirir misin?")
    print(f"\n{yanit}")

    # ── Demo 2: Büyüme odaklı yatırımcı, portföy ──
    print("\n\n📌 DEMO 2: Büyüme Yatırımcısı — Portföy Analizi")
    agent_elif = BISTAgent(kullanici_id="elif_buyume", verbose=True)
    yanit2 = agent_elif.sor(
        "THYAO, EREGL, BIMAS, GARAN ve KCHOL hisselerinden "
        "oluşan portföyümü analiz et. Hangi ağırlıklar mantıklı?"
    )
    print(f"\n{yanit2}")

    # ── Demo 3: Çoklu sorgu (konuşma geçmişi) ──
    print("\n\n📌 DEMO 3: Çok Turlu Konuşma")
    agent_mert = BISTAgent(kullanici_id="mert_agresif", verbose=True)
    agent_mert.sor("THYAO ve PGSUS'u karşılaştır, hangisi daha iyi fırsat?")
    yanit3 = agent_mert.sor("THYAO'yu seçtim, hangi fiyat seviyesinde almalıyım?")
    print(f"\n{yanit3}")
