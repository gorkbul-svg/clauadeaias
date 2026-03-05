"""
alarm_checker.py — Fiyat Alarm Servisi
Her 5 dakikada aktif alarmları kontrol eder, tetiklenince e-posta gönderir.

Kullanım:
  python alarm_checker.py          # Tek seferlik kontrol
  python alarm_checker.py --loop   # Sürekli döngü (production)
"""

import time
import smtplib
import os
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from database import aktif_alarmlari_getir, alarm_tetiklendi_isle, init_db
from data.yahoo_finance import get_stock_price

# ── E-posta Ayarları (ortam değişkenleri) ────────────────
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")       # gönderici Gmail
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")   # Gmail App Password
FROM_EMAIL    = os.getenv("FROM_EMAIL", SMTP_USER)

KONTROL_ARALIGI = int(os.getenv("ALARM_CHECK_INTERVAL", "300"))  # 5 dakika

# ── E-posta Gönder ────────────────────────────────────────
def eposta_gonder(to_email: str, ad: str, ticker: str,
                  hedef_fiyat: float, gercek_fiyat: float, alarm_tipi: str):
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"⚠️  E-posta ayarı yok — alarm log'a yazıldı: {to_email} / {ticker}")
        return

    yon = "üzerine çıktı ▲" if alarm_tipi == "yukari" else "altına indi ▼"
    konu = f"🔔 {ticker} Fiyat Alarmı — {gercek_fiyat:.2f} ₺"

    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;background:#f4f1eb;padding:32px;border-radius:8px">
      <h2 style="color:#0a0f1e;margin-bottom:8px">🔔 Fiyat Alarmı Tetiklendi</h2>
      <p style="color:#6b7280;margin-bottom:24px">Merhaba {ad},</p>

      <div style="background:white;border-radius:8px;padding:20px;margin-bottom:20px">
        <div style="font-size:24px;font-weight:800;color:#0a0f1e">{ticker}</div>
        <div style="font-size:32px;font-weight:800;color:#1d4ed8;margin:8px 0">{gercek_fiyat:.2f} ₺</div>
        <div style="color:#6b7280">Hedef fiyatın ({hedef_fiyat:.2f} ₺) {yon}</div>
      </div>

      <a href="https://gorkbul-svg.github.io/clauadeaias/demo.html"
         style="display:block;background:#1d4ed8;color:white;text-align:center;
                padding:12px;border-radius:6px;text-decoration:none;font-weight:600">
        Hisseyi Analiz Et →
      </a>

      <p style="color:#9ca3af;font-size:11px;margin-top:20px;text-align:center">
        Bu alarm otomatik oluşturulmuştur. Yatırım tavsiyesi değildir.
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = konu
    msg["From"]    = FROM_EMAIL
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())
        print(f"✅ E-posta gönderildi: {to_email} / {ticker}")
    except Exception as e:
        print(f"❌ E-posta hatası: {e}")

# ── Alarm Kontrolü ────────────────────────────────────────
def alarmlari_kontrol_et():
    simdi = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{simdi}] Alarmlar kontrol ediliyor...")

    alarmlar = aktif_alarmlari_getir()
    if not alarmlar:
        print("  Aktif alarm yok.")
        return

    print(f"  {len(alarmlar)} aktif alarm bulundu.")

    for alarm in alarmlar:
        ticker        = alarm["ticker"]
        hedef_fiyat   = alarm["hedef_fiyat"]
        alarm_tipi    = alarm["alarm_tipi"]
        alarm_id      = alarm["id"]
        email         = alarm["email"]
        ad            = alarm["ad"] or "Yatırımcı"

        try:
            veri = get_stock_price(ticker)
            if "hata" in veri:
                print(f"  ⚠️  {ticker} fiyat alınamadı: {veri['hata']}")
                continue

            gercek_fiyat = veri["fiyat"]

            tetiklendi = (
                alarm_tipi == "yukari" and gercek_fiyat >= hedef_fiyat
            ) or (
                alarm_tipi == "asagi" and gercek_fiyat <= hedef_fiyat
            )

            if tetiklendi:
                print(f"  🔔 ALARM! {ticker}: {gercek_fiyat:.2f} ₺ (hedef: {hedef_fiyat:.2f} ₺)")
                alarm_tetiklendi_isle(alarm_id)
                eposta_gonder(email, ad, ticker, hedef_fiyat, gercek_fiyat, alarm_tipi)
            else:
                yon = "▲" if alarm_tipi == "yukari" else "▼"
                print(f"  ✓ {ticker}: {gercek_fiyat:.2f} ₺ | Hedef: {hedef_fiyat:.2f} ₺ {yon}")

        except Exception as e:
            print(f"  ❌ {ticker} hatası: {e}")

# ── Ana Döngü ─────────────────────────────────────────────
def main():
    init_db()

    if "--loop" in sys.argv:
        print(f"🔄 Alarm servisi başlatıldı (her {KONTROL_ARALIGI//60} dakikada kontrol)")
        while True:
            try:
                alarmlari_kontrol_et()
            except Exception as e:
                print(f"❌ Döngü hatası: {e}")
            time.sleep(KONTROL_ARALIGI)
    else:
        alarmlari_kontrol_et()

if __name__ == "__main__":
    main()
