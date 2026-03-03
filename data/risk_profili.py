"""
Adım 2: Kullanıcı Risk Profili Sistemi
---------------------------------------
Yatırımcının risk toleransını, deneyimini ve hedeflerini
belirleyerek kişiselleştirilmiş analiz sunar.

Risk profilleri:
    muhafazakar   → Düşük risk, temettü odaklı
    dengeli       → Orta risk, büyüme + temettü
    büyüme        → Orta-yüksek risk, büyüme odaklı
    agresif       → Yüksek risk, spekülatif
"""

from dataclasses import dataclass, field, asdict
from typing import Optional
import json
from pathlib import Path


# ─────────────────────────────────────────────
# VERİ YAPILARI
# ─────────────────────────────────────────────

@dataclass
class RiskProfili:
    """Yatırımcı risk profili"""

    # Kimlik
    kullanici_id: str
    ad: str

    # Risk toleransı: muhafazakar | dengeli | büyüme | agresif
    risk_toleransi: str = "dengeli"

    # Yatırım deneyimi: yeni_baslangiç | orta | deneyimli | uzman
    deneyim: str = "orta"

    # Yatırım ufku: kisa (0-1 yıl) | orta (1-3 yıl) | uzun (3+ yıl)
    yatirim_ufku: str = "orta"

    # Hedefler (çoklu seçim)
    hedefler: list = field(default_factory=lambda: ["büyüme"])

    # Finansal bilgiler
    portfoy_buyuklugu_try: Optional[float] = None
    aylik_tasarruf_try: Optional[float] = None
    acil_fon_ay: int = 3   # Kaç aylık acil fon var

    # Kişiselleştirme
    tercih_edilen_sektorler: list = field(default_factory=list)
    kacinilanlar: list = field(default_factory=list)

    # Hesaplanan skorlar (otomatik doldurulur)
    risk_skoru: int = 0          # 1-100
    maks_kayip_toleransi: float = 0.0  # % olarak max tolere edilebilir kayıp


# Risk profili parametreleri
PROFIL_PARAMETRELERI = {
    "muhafazakar": {
        "risk_skoru_aralik": (1, 30),
        "maks_kayip": 10.0,
        "tercih_edilen_metrikler": ["temettü_verimi", "FK_orani", "borc_ozsermaye"],
        "ideal_FK_max": 12,
        "aciklama": "Düşük risk, sermaye koruma öncelikli. Temettü ve mavi çip hisseler.",
        "uygun_hisse_profili": {
            "FK_max": 15,
            "borc_ozsermaye_max": 1.0,
            "temettü_min": 2.0,
            "RSI_aralik": (30, 60)
        }
    },
    "dengeli": {
        "risk_skoru_aralik": (31, 60),
        "maks_kayip": 25.0,
        "tercih_edilen_metrikler": ["FK_orani", "ROE_yuzde", "kar_buyume"],
        "ideal_FK_max": 20,
        "aciklama": "Orta risk. Büyüme ve temettüyü dengeler.",
        "uygun_hisse_profili": {
            "FK_max": 25,
            "borc_ozsermaye_max": 2.0,
            "temettü_min": 1.0,
            "RSI_aralik": (25, 70)
        }
    },
    "büyüme": {
        "risk_skoru_aralik": (61, 80),
        "maks_kayip": 40.0,
        "tercih_edilen_metrikler": ["kar_buyume", "gelir_buyume", "ROE_yuzde"],
        "ideal_FK_max": 35,
        "aciklama": "Büyüme odaklı. Yüksek büyüme potansiyeli olan şirketler.",
        "uygun_hisse_profili": {
            "FK_max": 40,
            "borc_ozsermaye_max": 3.0,
            "temettü_min": 0,
            "RSI_aralik": (20, 75)
        }
    },
    "agresif": {
        "risk_skoru_aralik": (81, 100),
        "maks_kayip": 60.0,
        "tercih_edilen_metrikler": ["momentum", "kar_buyume", "teknik_trend"],
        "ideal_FK_max": 999,
        "aciklama": "Yüksek risk-yüksek getiri. Spekülatif pozisyonlar mümkün.",
        "uygun_hisse_profili": {
            "FK_max": 999,
            "borc_ozsermaye_max": 999,
            "temettü_min": 0,
            "RSI_aralik": (10, 90)
        }
    }
}


# ─────────────────────────────────────────────
# RİSK SKORU HESAPLAMA
# ─────────────────────────────────────────────

def risk_skoru_hesapla(profil: RiskProfili) -> tuple[int, float]:
    """
    Cevaplara göre 1-100 arasında risk skoru hesaplar.
    Döndürür: (risk_skoru, maks_kayip_toleransi)
    """
    skor = 0

    # Risk toleransı (0-40 puan)
    tolerans_puan = {"muhafazakar": 5, "dengeli": 20, "büyüme": 32, "agresif": 40}
    skor += tolerans_puan.get(profil.risk_toleransi, 20)

    # Yatırım deneyimi (0-25 puan)
    deneyim_puan = {"yeni_baslangiç": 5, "orta": 12, "deneyimli": 20, "uzman": 25}
    skor += deneyim_puan.get(profil.deneyim, 12)

    # Yatırım ufku (0-20 puan)
    ufuk_puan = {"kisa": 5, "orta": 12, "uzun": 20}
    skor += ufuk_puan.get(profil.yatirim_ufku, 12)

    # Acil fon durumu (0-15 puan) — acil fon fazlaysa daha fazla risk alabilir
    if profil.acil_fon_ay >= 6:
        skor += 15
    elif profil.acil_fon_ay >= 3:
        skor += 8
    else:
        skor += 0

    skor = min(100, max(1, skor))

    # Risk skoruna göre max kayıp toleransı
    if skor <= 30:
        maks_kayip = 10.0
    elif skor <= 60:
        maks_kayip = 25.0
    elif skor <= 80:
        maks_kayip = 40.0
    else:
        maks_kayip = 60.0

    return skor, maks_kayip


# ─────────────────────────────────────────────
# PROFİL OLUŞTURMA
# ─────────────────────────────────────────────

def profil_olustur(
    kullanici_id: str,
    ad: str,
    risk_toleransi: str,
    deneyim: str,
    yatirim_ufku: str,
    hedefler: list,
    portfoy_try: Optional[float] = None,
    aylik_tasarruf: Optional[float] = None,
    acil_fon_ay: int = 3,
    tercih_edilen_sektorler: list = None,
    kacinilanlar: list = None
) -> RiskProfili:
    """Yeni yatırımcı profili oluşturur ve risk skorunu hesaplar."""

    profil = RiskProfili(
        kullanici_id=kullanici_id,
        ad=ad,
        risk_toleransi=risk_toleransi,
        deneyim=deneyim,
        yatirim_ufku=yatirim_ufku,
        hedefler=hedefler,
        portfoy_buyuklugu_try=portfoy_try,
        aylik_tasarruf_try=aylik_tasarruf,
        acil_fon_ay=acil_fon_ay,
        tercih_edilen_sektorler=tercih_edilen_sektorler or [],
        kacinilanlar=kacinilanlar or []
    )

    profil.risk_skoru, profil.maks_kayip_toleransi = risk_skoru_hesapla(profil)
    return profil


# ─────────────────────────────────────────────
# PROFILE GÖRE HİSSE DEĞERLENDİRMESİ
# ─────────────────────────────────────────────

def hisse_profile_uygunluk(
    profil: RiskProfili,
    finansallar: dict,
    teknik: dict
) -> dict:
    """
    Bir hissenin yatırımcı profiline ne kadar uygun olduğunu değerlendirir.
    
    Döndürür:
        uygunluk_skoru (0-100), seviye, gerekce, uyarilar
    """
    kriter = PROFIL_PARAMETRELERI[profil.risk_toleransi]["uygun_hisse_profili"]
    
    skor = 100
    uyarilar = []
    pozitifler = []

    # F/K kontrolü
    fk = finansallar.get("FK_orani", 0)
    if fk > 0:
        if fk <= kriter["FK_max"]:
            pozitifler.append(f"F/K oranı ({fk}) profile uygun")
        else:
            ceza = min(30, (fk - kriter["FK_max"]) * 2)
            skor -= ceza
            uyarilar.append(f"F/K oranı ({fk}) profil için yüksek (max {kriter['FK_max']})")

    # Borç/özsermaye kontrolü
    borc = finansallar.get("borc_ozsermaye", 0)
    if borc > kriter["borc_ozsermaye_max"]:
        skor -= 20
        uyarilar.append(f"Borç/özsermaye ({borc}) yüksek")
    else:
        pozitifler.append(f"Borç seviyesi yönetilebilir")

    # Temettü kontrolü (muhafazakâr için önemli)
    temettu = finansallar.get("temettü_verimi_yuzde", 0)
    if kriter["temettü_min"] > 0 and temettu < kriter["temettü_min"]:
        skor -= 15
        uyarilar.append(f"Temettü verimi ({temettu}%) beklentinin altında")
    elif temettu > kriter["temettü_min"]:
        pozitifler.append(f"Temettü verimi ({temettu}%) tatmin edici")

    # RSI kontrolü
    rsi = teknik.get("RSI_14", 50)
    rsi_min, rsi_max = kriter["RSI_aralik"]
    if not (rsi_min <= rsi <= rsi_max):
        skor -= 10
        uyarilar.append(f"RSI ({rsi}) tercih edilen aralık dışında ({rsi_min}-{rsi_max})")

    # ROE kontrolü
    roe = finansallar.get("ROE_yuzde", 0)
    if roe > 15:
        pozitifler.append(f"ROE ({roe}%) güçlü")
    elif roe > 0:
        skor -= 5
    else:
        skor -= 15
        uyarilar.append("Negatif özsermaye getirisi (ROE)")

    skor = max(0, min(100, skor))

    seviye = "Çok Uygun" if skor >= 80 else \
             "Uygun"    if skor >= 60 else \
             "Kısmen Uygun" if skor >= 40 else \
             "Dikkatli Ol" if skor >= 20 else "Uygun Değil"

    return {
        "uygunluk_skoru": skor,
        "seviye": seviye,
        "pozitifler": pozitifler,
        "uyarilar": uyarilar,
        "profil_ozeti": f"{profil.risk_toleransi.capitalize()} profil | Risk skoru: {profil.risk_skoru}/100"
    }


# ─────────────────────────────────────────────
# PROFIL KAYDET / YÜKLEss
# ─────────────────────────────────────────────

PROFIL_DIZIN = Path("data/kullanici_profilleri")

def profil_kaydet(profil: RiskProfili):
    """Profili JSON olarak kaydeder."""
    PROFIL_DIZIN.mkdir(parents=True, exist_ok=True)
    dosya = PROFIL_DIZIN / f"{profil.kullanici_id}.json"
    with open(dosya, "w", encoding="utf-8") as f:
        json.dump(asdict(profil), f, ensure_ascii=False, indent=2)
    return str(dosya)

def profil_yukle(kullanici_id: str) -> Optional[RiskProfili]:
    """Kaydedilmiş profili yükler."""
    dosya = PROFIL_DIZIN / f"{kullanici_id}.json"
    if not dosya.exists():
        return None
    with open(dosya, encoding="utf-8") as f:
        data = json.load(f)
    return RiskProfili(**data)


# ─────────────────────────────────────────────
# ÖRNEK PROFİLLER
# ─────────────────────────────────────────────

ORNEK_PROFILLER = {
    "ahmet_muhafazakar": profil_olustur(
        kullanici_id="u001",
        ad="Ahmet Yılmaz",
        risk_toleransi="muhafazakar",
        deneyim="orta",
        yatirim_ufku="uzun",
        hedefler=["temettü_geliri", "sermaye_koruma"],
        portfoy_try=500_000,
        aylik_tasarruf=5_000,
        acil_fon_ay=6,
        tercih_edilen_sektorler=["bankacılık", "perakende"],
        kacinilanlar=["kripto", "kaldıraçlı"]
    ),
    "elif_buyume": profil_olustur(
        kullanici_id="u002",
        ad="Elif Kaya",
        risk_toleransi="büyüme",
        deneyim="deneyimli",
        yatirim_ufku="uzun",
        hedefler=["sermaye_artisi", "büyüme"],
        portfoy_try=200_000,
        aylik_tasarruf=8_000,
        acil_fon_ay=4,
        tercih_edilen_sektorler=["havacılık", "teknoloji"],
        kacinilanlar=[]
    ),
    "mert_agresif": profil_olustur(
        kullanici_id="u003",
        ad="Mert Demir",
        risk_toleransi="agresif",
        deneyim="uzman",
        yatirim_ufku="kisa",
        hedefler=["kisa_vadeli_kazanc"],
        portfoy_try=100_000,
        aylik_tasarruf=15_000,
        acil_fon_ay=6,
        tercih_edilen_sektorler=[],
        kacinilanlar=[]
    )
}


if __name__ == "__main__":
    print("=== Risk Profili Sistemi Test ===\n")
    for isim, profil in ORNEK_PROFILLER.items():
        params = PROFIL_PARAMETRELERI[profil.risk_toleransi]
        print(f"👤 {profil.ad}")
        print(f"   Risk Toleransı : {profil.risk_toleransi}")
        print(f"   Risk Skoru     : {profil.risk_skoru}/100")
        print(f"   Max Kayıp      : %{profil.maks_kayip_toleransi}")
        print(f"   Açıklama       : {params['aciklama']}")
        print()
