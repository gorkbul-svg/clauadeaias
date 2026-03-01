"""
BIST Hisse Araştırma Agent
--------------------------
Claude Tool Use API kullanarak bireysel yatırımcılara
BIST hisseleri hakkında araştırma yapan akıllı bir agent.

Mimari:
  Kullanıcı → Agent → Tools (mock/gerçek API) → Claude Analizi → Sonuç

Gereksinimler:
  pip install anthropic
  export ANTHROPIC_API_KEY="your_key"
"""

import json
import os
from datetime import datetime
from anthropic import Anthropic

client = Anthropic()

# ============================================================
# TOOLS — Agent'ın kullanabileceği araçlar
# Gerçek üretimde bu fonksiyonlar Borsa İstanbul API'si,
# Yahoo Finance, veya IS Yatırım/Eczacıbaşı gibi 
# veri sağlayıcılarına bağlanır.
# ============================================================

TOOLS = [
    {
        "name": "get_stock_price",
        "description": (
            "Bir BIST hissesinin anlık fiyat bilgisini getirir. "
            "Fiyat, günlük değişim, hacim ve 52 haftalık aralık döndürür."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "BIST hisse kodu (örn: THYAO, AKBNK, EREGL)"
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_financials",
        "description": (
            "Hissenin temel finansal verilerini getirir: "
            "F/K oranı, PD/DD, ROE, net kar marjı, borç/özsermaye gibi metrikler."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "BIST hisse kodu"
                },
                "period": {
                    "type": "string",
                    "enum": ["son_ceyrek", "yillik"],
                    "description": "Analiz dönemi"
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_news_sentiment",
        "description": (
            "Hisse ile ilgili son haberleri ve genel piyasa duyarlılığını getirir. "
            "Pozitif/negatif/nötr skor ve özet haber başlıkları döndürür."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "BIST hisse kodu"
                },
                "days": {
                    "type": "integer",
                    "description": "Kaç günlük haber analiz edilsin (varsayılan: 7)",
                    "default": 7
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_technical_indicators",
        "description": (
            "Teknik analiz göstergelerini hesaplar: "
            "RSI, MACD, Hareketli Ortalamalar (MA20, MA50, MA200), Bollinger Bantları."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "BIST hisse kodu"
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "compare_sector_peers",
        "description": (
            "Hisseyi sektörünün benzer şirketleriyle karşılaştırır. "
            "Sektör ortalaması ve rakip şirketlerin temel metrikleri döndürür."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "BIST hisse kodu"
                }
            },
            "required": ["ticker"]
        }
    }
]


# ============================================================
# MOCK DATA — Gerçek API entegrasyonu yapılana kadar
# ============================================================

MOCK_DATA = {
    "THYAO": {
        "price": {
            "ticker": "THYAO",
            "sirket": "Türk Hava Yolları",
            "fiyat": 287.50,
            "degisim_yuzde": +2.3,
            "hacim": "185.4M TL",
            "haftalik_dusuk_52": 198.20,
            "haftalik_yuksek_52": 312.80,
            "tarih": datetime.now().strftime("%d.%m.%Y %H:%M")
        },
        "financials": {
            "FK_orani": 7.2,
            "PD_DD": 1.8,
            "ROE_yuzde": 28.4,
            "net_kar_marji_yuzde": 12.1,
            "borc_ozsermaye": 0.9,
            "son_donem_kar_buyume_yuzde": +45.2,
            "donem": "2024 Yıllık"
        },
        "news": {
            "sentiment_skoru": 0.65,
            "sentiment_label": "Pozitif",
            "haberler": [
                "THY yolcu sayısında rekor kırdı — +18% YoY büyüme",
                "Yeni Avrupa rotaları açıklandı, filo genişliyor",
                "Jet yakıt maliyetleri hafifçe geriledi"
            ],
            "analiz_donemi_gun": 7
        },
        "technical": {
            "RSI_14": 58.3,
            "MACD": "Pozitif (Al sinyali)",
            "MA20": 275.40,
            "MA50": 261.80,
            "MA200": 238.50,
            "bollinger_ust": 305.20,
            "bollinger_alt": 245.60,
            "trend": "Yükseliş"
        },
        "peers": {
            "sektor": "Havacılık & Ulaşım",
            "sektor_ort_FK": 9.1,
            "rakipler": [
                {"ticker": "PGSUS", "sirket": "Pegasus", "FK": 11.2, "ROE": 22.1},
                {"ticker": "HAVAS", "sirket": "Havaş", "FK": 15.4, "ROE": 18.3}
            ]
        }
    },
    "AKBNK": {
        "price": {
            "ticker": "AKBNK",
            "sirket": "Akbank",
            "fiyat": 54.30,
            "degisim_yuzde": -0.8,
            "hacim": "412.7M TL",
            "haftalik_dusuk_52": 38.90,
            "haftalik_yuksek_52": 62.10,
            "tarih": datetime.now().strftime("%d.%m.%Y %H:%M")
        },
        "financials": {
            "FK_orani": 4.1,
            "PD_DD": 0.9,
            "ROE_yuzde": 34.2,
            "net_kar_marji_yuzde": 28.5,
            "borc_ozsermaye": 8.2,
            "son_donem_kar_buyume_yuzde": +12.8,
            "donem": "2024 Yıllık"
        },
        "news": {
            "sentiment_skoru": 0.45,
            "sentiment_label": "Nötr",
            "haberler": [
                "Merkez Bankası faiz kararı bekleniyor",
                "Akbank kredi büyümesi beklentileri karşıladı",
                "Bankacılık sektöründe NPL oranları izleniyor"
            ],
            "analiz_donemi_gun": 7
        },
        "technical": {
            "RSI_14": 45.1,
            "MACD": "Nötr (Yatay)",
            "MA20": 55.80,
            "MA50": 51.20,
            "MA200": 47.30,
            "bollinger_ust": 61.40,
            "bollinger_alt": 47.20,
            "trend": "Yatay"
        },
        "peers": {
            "sektor": "Bankacılık",
            "sektor_ort_FK": 5.2,
            "rakipler": [
                {"ticker": "GARAN", "sirket": "Garanti BBVA", "FK": 4.8, "ROE": 31.5},
                {"ticker": "ISCTR", "sirket": "İş Bankası", "FK": 3.9, "ROE": 29.8}
            ]
        }
    }
}

def get_mock_data(ticker: str, data_type: str) -> dict:
    """Mock veri döndürür. Üretimde gerçek API çağrısı yapılır."""
    ticker = ticker.upper()
    
    if ticker not in MOCK_DATA:
        # Bilinmeyen hisse için varsayılan veri üret
        return {
            "hata": f"{ticker} için veri bulunamadı.",
            "desteklenen_hisseler": list(MOCK_DATA.keys()),
            "not": "Gerçek entegrasyonda tüm BIST hisseleri desteklenir."
        }
    
    return MOCK_DATA[ticker].get(data_type, {"hata": "Veri bulunamadı"})


# ============================================================
# TOOL EXECUTOR — Hangi tool çağrıldıysa çalıştır
# ============================================================

def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Tool çağrısını işler ve sonucu JSON string olarak döndürür."""
    
    ticker = tool_input.get("ticker", "").upper()
    
    if tool_name == "get_stock_price":
        result = get_mock_data(ticker, "price")
    
    elif tool_name == "get_financials":
        result = get_mock_data(ticker, "financials")
    
    elif tool_name == "get_news_sentiment":
        result = get_mock_data(ticker, "news")
    
    elif tool_name == "get_technical_indicators":
        result = get_mock_data(ticker, "technical")
    
    elif tool_name == "compare_sector_peers":
        result = get_mock_data(ticker, "peers")
    
    else:
        result = {"hata": f"Bilinmeyen tool: {tool_name}"}
    
    return json.dumps(result, ensure_ascii=False, indent=2)


# ============================================================
# AGENT DÖNGÜSÜ — Claude ile ReAct döngüsü
# ============================================================

SYSTEM_PROMPT = """Sen BIST uzmanı bir yatırım araştırma asistanısın. 
Bireysel yatırımcılara Borsa İstanbul'daki hisseler hakkında kapsamlı, 
anlaşılır ve tarafsız araştırma yapıyorsun.

Analiz yaparken şu adımları takip et:
1. Önce hisse fiyatını ve genel durumunu kontrol et
2. Temel finansal verileri incele (F/K, ROE, büyüme)
3. Haberleri ve piyasa duyarlılığını değerlendir
4. Teknik göstergelere bak
5. Sektör rakipleriyle karşılaştır
6. Tüm verileri sentezleyerek net bir özet sun

ÖNEMLI UYARILAR:
- Her zaman "Bu bir yatırım tavsiyesi değildir" ibaresini ekle
- Riskleri açıkça belirt
- Yatırımcının kendi araştırmasını yapmasını teşvik et
- Türkçe yanıt ver, teknik terimleri açıkla"""

def run_agent(user_query: str, verbose: bool = True) -> str:
    """
    Ana agent döngüsü.
    Claude, araştırma tamamlanana kadar tool'ları kullanmaya devam eder.
    """
    messages = [{"role": "user", "content": user_query}]
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"🤖 BIST Araştırma Agent Başlatıldı")
        print(f"📝 Sorgu: {user_query}")
        print(f"{'='*60}\n")
    
    iteration = 0
    max_iterations = 10  # Sonsuz döngü koruması
    
    while iteration < max_iterations:
        iteration += 1
        
        if verbose:
            print(f"🔄 Iterasyon {iteration} — Claude'a istek gönderiliyor...")
        
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages
        )
        
        if verbose:
            print(f"   Stop reason: {response.stop_reason}")
        
        # Claude tamamladı, tool kullanmıyor
        if response.stop_reason == "end_turn":
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text
            
            if verbose:
                print(f"\n✅ Analiz tamamlandı!\n")
            
            return final_text
        
        # Claude tool çağırıyor
        if response.stop_reason == "tool_use":
            # Önce assistant mesajını ekle
            messages.append({"role": "assistant", "content": response.content})
            
            # Her tool çağrısını işle
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    if verbose:
                        print(f"   🔧 Tool çağrısı: {block.name}({block.input})")
                    
                    result = execute_tool(block.name, block.input)
                    
                    if verbose:
                        print(f"   ✓ Sonuç alındı ({len(result)} karakter)")
                    
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })
            
            # Tool sonuçlarını mesajlara ekle
            messages.append({"role": "user", "content": tool_results})
        
        else:
            # Beklenmedik durum
            break
    
    return "Agent maksimum iterasyon limitine ulaştı."


# ============================================================
# ÖRNEK KULLANIM
# ============================================================

if __name__ == "__main__":
    print("\n" + "🚀 "*20)
    print("BIST HİSSE ARAŞTIRMA AGENT")
    print("Claude Tool Use API ile Güçlendirilmiş")
    print("🚀 "*20 + "\n")
    
    # --- Örnek 1: Tek hisse kapsamlı analiz ---
    sonuc = run_agent(
        "THYAO hissesini kapsamlı olarak analiz et. "
        "Almak için uygun mu? Riskler neler?",
        verbose=True
    )
    print("\n" + "="*60)
    print("📊 ANALİZ SONUCU:")
    print("="*60)
    print(sonuc)
    
    print("\n\n" + "-"*60 + "\n")
    
    # --- Örnek 2: Karşılaştırmalı soru ---
    sonuc2 = run_agent(
        "AKBNK mı daha iyi bir yatırım fırsatı sunuyor yoksa THYAO mı? "
        "Her ikisini de kısaca değerlendir.",
        verbose=True
    )
    print("\n" + "="*60)
    print("📊 KARŞILAŞTIRMA SONUCU:")
    print("="*60)
    print(sonuc2)
