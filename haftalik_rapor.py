"""
haftalik_rapor.py — Haftalık Portföy Raporu
Her Pazartesi sabahı watchlist'teki hisseleri analiz eder,
güzel bir HTML e-posta gönderir.

Kullanım:
    python haftalik_rapor.py            # Tek seferlik çalıştır
    python haftalik_rapor.py --loop     # Her Pazartesi 09:00'da çalıştır
"""

import os
import smtplib
import argparse
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from database import get_db
from data.yahoo_finance import get_stock_price, get_technical_indicators, get_financials

# ── Ortam Değişkenleri ────────────────────────────────────
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASSWORD", "")
RAPOR_INTERVAL = int(os.getenv("RAPOR_CHECK_INTERVAL", "3600"))  # saatte bir kontrol

# ── Veri Çekme ────────────────────────────────────────────

def watchlist_kullanicilari_getir():
    """Watchlist'i olan tüm kullanıcıları getir."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT DISTINCT k.id, k.email, k.ad
            FROM kullanicilar k
            JOIN watchlist w ON w.kullanici_id = k.id
            WHERE k.email IS NOT NULL
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def kullanici_watchlist_getir(kullanici_id: int):
    """Kullanıcının watchlist'ini getir."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT ticker, not_metni, eklendi
            FROM watchlist WHERE kullanici_id = ?
        """, (kullanici_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def hisse_haftalik_analiz(ticker: str) -> dict:
    """Hissenin haftalık verilerini çek."""
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker + ".IS")
        df = stock.history(period="5d")

        if df.empty:
            return {"ticker": ticker, "hata": "Veri yok"}

        haftalik_degisim = 0
        if len(df) >= 2:
            haftalik_degisim = round(
                (df["Close"].iloc[-1] - df["Close"].iloc[0]) / df["Close"].iloc[0] * 100, 2
            )

        fiyat  = get_stock_price(ticker)
        teknik = get_technical_indicators(ticker)

        return {
            "ticker": ticker,
            "sirket": fiyat.get("sirket", ticker),
            "son_fiyat": fiyat.get("fiyat", 0),
            "gunluk_degisim": fiyat.get("degisim_yuzde", 0),
            "haftalik_degisim": haftalik_degisim,
            "rsi": teknik.get("RSI_14", 0),
            "trend": teknik.get("trend", "—"),
            "ma50": teknik.get("MA50", 0),
        }
    except Exception as e:
        return {"ticker": ticker, "hata": str(e)}

# ── HTML E-posta Şablonu ──────────────────────────────────

def rapor_html_olustur(kullanici_ad: str, watchlist_verileri: list) -> str:
    tarih = datetime.now().strftime("%d %B %Y")
    hafta_basi = (datetime.now() - timedelta(days=7)).strftime("%d %B")

    # Özet istatistikler
    gecerli = [h for h in watchlist_verileri if "hata" not in h]
    yukselenler = [h for h in gecerli if h["haftalik_degisim"] > 0]
    dusenler    = [h for h in gecerli if h["haftalik_degisim"] < 0]
    en_iyi      = max(gecerli, key=lambda x: x["haftalik_degisim"], default=None)
    en_kotu     = min(gecerli, key=lambda x: x["haftalik_degisim"], default=None)

    hisse_satirlari = ""
    for h in gecerli:
        renk    = "#22c55e" if h["haftalik_degisim"] >= 0 else "#ef4444"
        ikon    = "▲" if h["haftalik_degisim"] >= 0 else "▼"
        rsi_renk = "#ef4444" if h["rsi"] > 70 else "#22c55e" if h["rsi"] < 30 else "#9ca3af"
        hisse_satirlari += f"""
        <tr>
          <td style="padding:12px 16px;font-weight:700;color:#f0f4ff">{h["ticker"]}</td>
          <td style="padding:12px 16px;color:#9ca3af;font-size:12px">{h["sirket"][:25]}</td>
          <td style="padding:12px 16px;font-weight:600;color:#f0f4ff">{h["son_fiyat"]:.2f} ₺</td>
          <td style="padding:12px 16px;color:{renk};font-weight:700">{ikon} {abs(h["haftalik_degisim"]):.2f}%</td>
          <td style="padding:12px 16px;color:{rsi_renk}">{h["rsi"]:.0f}</td>
          <td style="padding:12px 16px;color:#9ca3af;font-size:12px">{h["trend"]}</td>
        </tr>"""

    en_iyi_html = f"""
        <div style="background:#0a1628;border:1px solid #1a2a42;border-radius:8px;padding:14px;flex:1">
          <div style="font-size:10px;color:#4a5878;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px">Haftanın En İyisi</div>
          <div style="font-size:20px;font-weight:800;color:#22c55e">{en_iyi["ticker"]}</div>
          <div style="font-size:14px;color:#22c55e">▲ {en_iyi["haftalik_degisim"]:.2f}%</div>
        </div>""" if en_iyi else ""

    en_kotu_html = f"""
        <div style="background:#0a1628;border:1px solid #1a2a42;border-radius:8px;padding:14px;flex:1">
          <div style="font-size:10px;color:#4a5878;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px">Haftanın En Kötüsü</div>
          <div style="font-size:20px;font-weight:800;color:#ef4444">{en_kotu["ticker"]}</div>
          <div style="font-size:14px;color:#ef4444">▼ {abs(en_kotu["haftalik_degisim"]):.2f}%</div>
        </div>""" if en_kotu else ""

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#060a12;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <div style="max-width:620px;margin:0 auto;padding:24px 16px">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#0d1a2e,#0a1220);border:1px solid #1a2a42;border-radius:12px;padding:28px 28px 24px;margin-bottom:16px">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
        <div style="width:36px;height:36px;background:linear-gradient(135deg,#1d62f0,#0ea5e9);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px">📊</div>
        <div>
          <div style="font-size:13px;font-weight:700;color:#f0f4ff;letter-spacing:.04em">BIST ARAŞTIRMA AGENT</div>
          <div style="font-size:11px;color:#4a5878">Haftalık Portföy Raporu</div>
        </div>
      </div>
      <div style="font-size:22px;font-weight:800;color:#f0f4ff">Merhaba {kullanici_ad} 👋</div>
      <div style="font-size:13px;color:#6b82a8;margin-top:4px">{hafta_basi} – {tarih} haftasına ait watchlist özetin aşağıda.</div>
    </div>

    <!-- Özet Kartlar -->
    <div style="display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap">
      <div style="background:#0d1a2e;border:1px solid #1a2a42;border-radius:8px;padding:14px;flex:1;min-width:120px">
        <div style="font-size:10px;color:#4a5878;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px">Takip Edilen</div>
        <div style="font-size:24px;font-weight:800;color:#f0f4ff">{len(gecerli)}</div>
        <div style="font-size:11px;color:#4a5878">hisse</div>
      </div>
      <div style="background:#0d1a2e;border:1px solid rgba(34,197,94,.2);border-radius:8px;padding:14px;flex:1;min-width:120px">
        <div style="font-size:10px;color:#4a5878;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px">Yükselenler</div>
        <div style="font-size:24px;font-weight:800;color:#22c55e">{len(yukselenler)}</div>
        <div style="font-size:11px;color:#4a5878">hisse</div>
      </div>
      <div style="background:#0d1a2e;border:1px solid rgba(239,68,68,.2);border-radius:8px;padding:14px;flex:1;min-width:120px">
        <div style="font-size:10px;color:#4a5878;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px">Düşenler</div>
        <div style="font-size:24px;font-weight:800;color:#ef4444">{len(dusenler)}</div>
        <div style="font-size:11px;color:#4a5878">hisse</div>
      </div>
      {en_iyi_html}
      {en_kotu_html}
    </div>

    <!-- Hisse Tablosu -->
    <div style="background:#0d1a2e;border:1px solid #1a2a42;border-radius:12px;overflow:hidden;margin-bottom:16px">
      <div style="padding:14px 16px;border-bottom:1px solid #1a2a42">
        <span style="font-size:12px;font-weight:700;color:#f0f4ff;letter-spacing:.04em">WATCHLİST PERFORMANSI</span>
      </div>
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="background:#060a12">
            <th style="padding:10px 16px;text-align:left;font-size:10px;color:#4a5878;letter-spacing:.08em;text-transform:uppercase">Hisse</th>
            <th style="padding:10px 16px;text-align:left;font-size:10px;color:#4a5878;letter-spacing:.08em;text-transform:uppercase">Şirket</th>
            <th style="padding:10px 16px;text-align:left;font-size:10px;color:#4a5878;letter-spacing:.08em;text-transform:uppercase">Fiyat</th>
            <th style="padding:10px 16px;text-align:left;font-size:10px;color:#4a5878;letter-spacing:.08em;text-transform:uppercase">Haftalık</th>
            <th style="padding:10px 16px;text-align:left;font-size:10px;color:#4a5878;letter-spacing:.08em;text-transform:uppercase">RSI</th>
            <th style="padding:10px 16px;text-align:left;font-size:10px;color:#4a5878;letter-spacing:.08em;text-transform:uppercase">Trend</th>
          </tr>
        </thead>
        <tbody style="color:#f0f4ff">
          {hisse_satirlari}
        </tbody>
      </table>
    </div>

    <!-- CTA -->
    <div style="text-align:center;margin-bottom:16px">
      <a href="https://gorkbul-svg.github.io/clauadeaias/demo.html"
         style="display:inline-block;background:#1d62f0;color:white;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:600;font-size:13px">
        Detaylı Analiz için Platforma Git →
      </a>
    </div>

    <!-- Footer -->
    <div style="text-align:center;font-size:11px;color:#2d3a52;padding:12px">
      BIST Araştırma Agent · Bu e-posta yatırım tavsiyesi değildir.<br>
      <a href="#" style="color:#2d3a52">Abonelikten çık</a>
    </div>

  </div>
</body>
</html>"""

# ── E-posta Gönderme ──────────────────────────────────────

def rapor_gonder(email: str, ad: str, html: str) -> bool:
    if not SMTP_USER or not SMTP_PASS:
        print(f"[RAPOR] SMTP ayarı yok — {email} için rapor simüle edildi")
        return True
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"📊 Haftalık BIST Raporu — {datetime.now().strftime('%d %B %Y')}"
        msg["From"]    = f"BIST Agent <{SMTP_USER}>"
        msg["To"]      = email
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, email, msg.as_string())

        print(f"[RAPOR] ✓ {email} adresine gönderildi")
        return True
    except Exception as e:
        print(f"[RAPOR] ✗ {email} — Hata: {e}")
        return False

# ── Ana Döngü ─────────────────────────────────────────────

def raporlari_gonder():
    """Tüm kullanıcılara haftalık rapor gönder."""
    print(f"\n[RAPOR] {datetime.now().strftime('%d.%m.%Y %H:%M')} — Haftalık raporlar gönderiliyor...")
    kullanicilar = watchlist_kullanicilari_getir()
    print(f"[RAPOR] {len(kullanicilar)} kullanıcı bulundu")

    for kullanici in kullanicilar:
        try:
            watchlist = kullanici_watchlist_getir(kullanici["id"])
            if not watchlist:
                continue

            print(f"[RAPOR] {kullanici['email']} → {len(watchlist)} hisse analiz ediliyor...")
            veriler = [hisse_haftalik_analiz(item["ticker"]) for item in watchlist]
            html = rapor_html_olustur(kullanici["ad"] or "Yatırımcı", veriler)
            rapor_gonder(kullanici["email"], kullanici["ad"] or "", html)

        except Exception as e:
            print(f"[RAPOR] ✗ {kullanici['email']} — {e}")

def sonraki_pazartesi_saniye() -> float:
    """Bir sonraki Pazartesi 09:00'a kaç saniye kaldığını hesapla."""
    simdi = datetime.now()
    gun_fark = (7 - simdi.weekday()) % 7  # Pazartesi = 0
    if gun_fark == 0 and simdi.hour >= 9:
        gun_fark = 7
    hedef = simdi.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=gun_fark)
    return (hedef - simdi).total_seconds()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Her Pazartesi 09:00'da çalıştır")
    args = parser.parse_args()

    if args.loop:
        print("[RAPOR] Haftalık rapor servisi başlatıldı")
        while True:
            bekle = sonraki_pazartesi_saniye()
            print(f"[RAPOR] Sonraki çalışma: {bekle/3600:.1f} saat sonra")
            time.sleep(bekle)
            raporlari_gonder()
    else:
        raporlari_gonder()
