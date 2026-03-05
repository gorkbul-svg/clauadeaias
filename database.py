"""
database.py — BIST Agent Veritabanı Katmanı
SQLite ile başla, PostgreSQL'e geçişe hazır yapı
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Veritabanı dosya yolu ─────────────────────────────────
DB_PATH = Path("bist_agent.db")

# ── Bağlantı ─────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # dict gibi erişim
    conn.execute("PRAGMA journal_mode=WAL")  # Performans
    conn.execute("PRAGMA foreign_keys=ON")   # FK kısıtlamaları
    return conn

# ── Tabloları Oluştur ─────────────────────────────────────
def init_db():
    conn = get_db()
    try:
        conn.executescript("""
            -- Kullanıcılar
            CREATE TABLE IF NOT EXISTS kullanicilar (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                google_id    TEXT UNIQUE NOT NULL,
                email        TEXT UNIQUE NOT NULL,
                ad           TEXT,
                fotograf_url TEXT,
                risk_profili TEXT DEFAULT 'buyume',
                olusturuldu  TEXT DEFAULT (datetime('now')),
                son_giris    TEXT
            );

            -- Watchlist
            CREATE TABLE IF NOT EXISTS watchlist (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                kullanici_id  INTEGER NOT NULL REFERENCES kullanicilar(id) ON DELETE CASCADE,
                ticker        TEXT NOT NULL,
                not_metni     TEXT,
                eklendi       TEXT DEFAULT (datetime('now')),
                UNIQUE(kullanici_id, ticker)
            );

            -- Fiyat Alarmları
            CREATE TABLE IF NOT EXISTS alarmlar (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                kullanici_id  INTEGER NOT NULL REFERENCES kullanicilar(id) ON DELETE CASCADE,
                ticker        TEXT NOT NULL,
                hedef_fiyat   REAL NOT NULL,
                alarm_tipi    TEXT NOT NULL CHECK(alarm_tipi IN ('yukari', 'asagi')),
                aktif         INTEGER DEFAULT 1,
                tetiklendi    INTEGER DEFAULT 0,
                olusturuldu   TEXT DEFAULT (datetime('now')),
                tetiklenme_zamani TEXT
            );

            -- Analiz Geçmişi
            CREATE TABLE IF NOT EXISTS analiz_gecmisi (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                kullanici_id  INTEGER REFERENCES kullanicilar(id) ON DELETE SET NULL,
                oturum_id     TEXT NOT NULL,
                soru          TEXT NOT NULL,
                yanit         TEXT NOT NULL,
                ticker        TEXT,
                olusturuldu   TEXT DEFAULT (datetime('now'))
            );

            -- Abonelikler
            CREATE TABLE IF NOT EXISTS abonelikler (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                kullanici_id    INTEGER NOT NULL REFERENCES kullanicilar(id) ON DELETE CASCADE,
                plan            TEXT DEFAULT 'ucretsiz' CHECK(plan IN ('ucretsiz','premium','kurumsal')),
                baslangic       TEXT DEFAULT (datetime('now')),
                bitis           TEXT,
                iyzico_token    TEXT,
                aktif           INTEGER DEFAULT 1
            );

            -- Kullanım sayacı
            CREATE TABLE IF NOT EXISTS kullanim_sayaci (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                kullanici_id    INTEGER NOT NULL REFERENCES kullanicilar(id) ON DELETE CASCADE,
                ay              TEXT NOT NULL,
                analiz_sayisi   INTEGER DEFAULT 0,
                UNIQUE(kullanici_id, ay)
            );

            -- API Anahtarları
            CREATE TABLE IF NOT EXISTS api_anahtarlari (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                kullanici_id    INTEGER NOT NULL REFERENCES kullanicilar(id) ON DELETE CASCADE,
                anahtar         TEXT UNIQUE NOT NULL,
                isim            TEXT,
                aktif           INTEGER DEFAULT 1,
                olusturuldu     TEXT DEFAULT (datetime('now')),
                son_kullanim    TEXT,
                kullanim_sayisi INTEGER DEFAULT 0
            );

            -- İndeksler
            CREATE INDEX IF NOT EXISTS idx_watchlist_kullanici ON watchlist(kullanici_id);
            CREATE INDEX IF NOT EXISTS idx_alarmlar_kullanici  ON alarmlar(kullanici_id);
            CREATE INDEX IF NOT EXISTS idx_alarmlar_aktif      ON alarmlar(aktif, tetiklendi);
            CREATE INDEX IF NOT EXISTS idx_gecmis_kullanici    ON analiz_gecmisi(kullanici_id);
            CREATE INDEX IF NOT EXISTS idx_gecmis_oturum       ON analiz_gecmisi(oturum_id);
        """)
        conn.commit()
        print("✅ Veritabanı başlatıldı")
    finally:
        conn.close()

# ══════════════════════════════════════════════════════════
# KULLANICI İŞLEMLERİ
# ══════════════════════════════════════════════════════════

def kullanici_bul_veya_olustur(google_id: str, email: str, ad: str, fotograf_url: str = None) -> dict:
    """Google OAuth sonrası kullanıcı bul veya oluştur."""
    conn = get_db()
    try:
        simdi = datetime.now().isoformat()

        # Mevcut kullanıcıyı güncelle
        conn.execute("""
            INSERT INTO kullanicilar (google_id, email, ad, fotograf_url, son_giris)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(google_id) DO UPDATE SET
                email        = excluded.email,
                ad           = excluded.ad,
                fotograf_url = excluded.fotograf_url,
                son_giris    = excluded.son_giris
        """, (google_id, email, ad, fotograf_url, simdi))
        conn.commit()

        kullanici = conn.execute(
            "SELECT * FROM kullanicilar WHERE google_id = ?", (google_id,)
        ).fetchone()
        return dict(kullanici)
    finally:
        conn.close()

def kullanici_getir(kullanici_id: int) -> Optional[dict]:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM kullanicilar WHERE id = ?", (kullanici_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def kullanici_risk_profili_guncelle(kullanici_id: int, risk_profili: str):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE kullanicilar SET risk_profili = ? WHERE id = ?",
            (risk_profili, kullanici_id)
        )
        conn.commit()
    finally:
        conn.close()

# ══════════════════════════════════════════════════════════
# WATCHLIST İŞLEMLERİ
# ══════════════════════════════════════════════════════════

def watchlist_getir(kullanici_id: int) -> list:
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT * FROM watchlist
            WHERE kullanici_id = ?
            ORDER BY eklendi DESC
        """, (kullanici_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def watchlist_ekle(kullanici_id: int, ticker: str, not_metni: str = None) -> dict:
    conn = get_db()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO watchlist (kullanici_id, ticker, not_metni)
            VALUES (?, ?, ?)
        """, (kullanici_id, ticker.upper(), not_metni))
        conn.commit()
        row = conn.execute("""
            SELECT * FROM watchlist
            WHERE kullanici_id = ? AND ticker = ?
        """, (kullanici_id, ticker.upper())).fetchone()
        return dict(row)
    finally:
        conn.close()

def watchlist_sil(kullanici_id: int, ticker: str) -> bool:
    conn = get_db()
    try:
        cursor = conn.execute("""
            DELETE FROM watchlist
            WHERE kullanici_id = ? AND ticker = ?
        """, (kullanici_id, ticker.upper()))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

# ══════════════════════════════════════════════════════════
# ALARM İŞLEMLERİ
# ══════════════════════════════════════════════════════════

def alarm_ekle(kullanici_id: int, ticker: str, hedef_fiyat: float, alarm_tipi: str) -> dict:
    """
    alarm_tipi: 'yukari' (fiyat hedefin üstüne çıkınca)
                'asagi'  (fiyat hedefin altına inince)
    """
    conn = get_db()
    try:
        cursor = conn.execute("""
            INSERT INTO alarmlar (kullanici_id, ticker, hedef_fiyat, alarm_tipi)
            VALUES (?, ?, ?, ?)
        """, (kullanici_id, ticker.upper(), hedef_fiyat, alarm_tipi))
        conn.commit()
        row = conn.execute(
            "SELECT * FROM alarmlar WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()

def alarm_listesi(kullanici_id: int) -> list:
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT * FROM alarmlar
            WHERE kullanici_id = ?
            ORDER BY olusturuldu DESC
        """, (kullanici_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def alarm_sil(alarm_id: int, kullanici_id: int) -> bool:
    conn = get_db()
    try:
        cursor = conn.execute("""
            DELETE FROM alarmlar
            WHERE id = ? AND kullanici_id = ?
        """, (alarm_id, kullanici_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def aktif_alarmlari_getir() -> list:
    """Tüm aktif, tetiklenmemiş alarmları getir (alarm checker için)."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT a.*, k.email, k.ad
            FROM alarmlar a
            JOIN kullanicilar k ON a.kullanici_id = k.id
            WHERE a.aktif = 1 AND a.tetiklendi = 0
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def alarm_tetiklendi_isle(alarm_id: int):
    """Alarm tetiklenince işaretle."""
    conn = get_db()
    try:
        conn.execute("""
            UPDATE alarmlar
            SET tetiklendi = 1,
                aktif = 0,
                tetiklenme_zamani = datetime('now')
            WHERE id = ?
        """, (alarm_id,))
        conn.commit()
    finally:
        conn.close()

# ══════════════════════════════════════════════════════════
# ANALİZ GEÇMİŞİ
# ══════════════════════════════════════════════════════════

def analiz_kaydet(oturum_id: str, soru: str, yanit: str,
                  kullanici_id: int = None, ticker: str = None):
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO analiz_gecmisi (kullanici_id, oturum_id, soru, yanit, ticker)
            VALUES (?, ?, ?, ?, ?)
        """, (kullanici_id, oturum_id, soru, yanit, ticker))
        conn.commit()
    finally:
        conn.close()

def analiz_gecmisi_getir(kullanici_id: int, limit: int = 20) -> list:
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, soru, ticker, olusturuldu
            FROM analiz_gecmisi
            WHERE kullanici_id = ?
            ORDER BY olusturuldu DESC
            LIMIT ?
        """, (kullanici_id, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def analiz_detay_getir(analiz_id: int, kullanici_id: int) -> Optional[dict]:
    conn = get_db()
    try:
        row = conn.execute("""
            SELECT * FROM analiz_gecmisi
            WHERE id = ? AND kullanici_id = ?
        """, (analiz_id, kullanici_id)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

# ── Başlatma ──────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print("Veritabanı şeması oluşturuldu:", DB_PATH)

# ══════════════════════════════════════════════════════════
# FREEMIUM & KULLANIM SAYACI
# ══════════════════════════════════════════════════════════

PLAN_LIMITLER = {
    "ucretsiz": 5,
    "premium":  999999,
    "kurumsal": 999999
}

def kullanim_kontrol(kullanici_id: int) -> dict:
    """Kullanıcının bu ayki kullanımını kontrol et."""
    conn = get_db()
    try:
        ay = datetime.now().strftime("%Y-%m")

        # Mevcut plan
        abonelik = conn.execute("""
            SELECT plan FROM abonelikler
            WHERE kullanici_id = ? AND aktif = 1
            ORDER BY id DESC LIMIT 1
        """, (kullanici_id,)).fetchone()
        plan = abonelik["plan"] if abonelik else "ucretsiz"
        limit = PLAN_LIMITLER.get(plan, 5)

        # Bu ayki kullanım
        sayac = conn.execute("""
            SELECT analiz_sayisi FROM kullanim_sayaci
            WHERE kullanici_id = ? AND ay = ?
        """, (kullanici_id, ay)).fetchone()
        kullanim = sayac["analiz_sayisi"] if sayac else 0

        return {
            "kullanici_id": kullanici_id,
            "plan": plan,
            "limit": limit,
            "kullanim": kullanim,
            "kalan": max(0, limit - kullanim),
            "izin_var": kullanim < limit,
            "ay": ay
        }
    finally:
        conn.close()

def kullanim_artir(kullanici_id: int) -> int:
    """Analiz sayacını 1 artır, yeni sayıyı döndür."""
    conn = get_db()
    try:
        ay = datetime.now().strftime("%Y-%m")
        conn.execute("""
            INSERT INTO kullanim_sayaci (kullanici_id, ay, analiz_sayisi)
            VALUES (?, ?, 1)
            ON CONFLICT(kullanici_id, ay) DO UPDATE SET
                analiz_sayisi = analiz_sayisi + 1
        """, (kullanici_id, ay))
        conn.commit()
        row = conn.execute("""
            SELECT analiz_sayisi FROM kullanim_sayaci
            WHERE kullanici_id = ? AND ay = ?
        """, (kullanici_id, ay)).fetchone()
        return row["analiz_sayisi"] if row else 1
    finally:
        conn.close()

def plan_guncelle(kullanici_id: int, plan: str, iyzico_token: str = None):
    """Kullanıcı planını güncelle."""
    conn = get_db()
    try:
        # Eski planı pasife al
        conn.execute("""
            UPDATE abonelikler SET aktif = 0
            WHERE kullanici_id = ?
        """, (kullanici_id,))

        # Yeni plan ekle
        bitis = None
        if plan == "premium":
            from datetime import timedelta
            bitis = (datetime.now() + timedelta(days=30)).isoformat()

        conn.execute("""
            INSERT INTO abonelikler (kullanici_id, plan, bitis, iyzico_token, aktif)
            VALUES (?, ?, ?, ?, 1)
        """, (kullanici_id, plan, bitis, iyzico_token))
        conn.commit()
    finally:
        conn.close()

# ══════════════════════════════════════════════════════════
# API ANAHTAR YÖNETİMİ
# ══════════════════════════════════════════════════════════

import secrets

def api_anahtar_olustur(kullanici_id: int, isim: str = "Varsayılan") -> dict:
    """Yeni API anahtarı oluştur."""
    conn = get_db()
    try:
        anahtar = "bist_" + secrets.token_urlsafe(32)
        conn.execute("""
            INSERT INTO api_anahtarlari (kullanici_id, anahtar, isim)
            VALUES (?, ?, ?)
        """, (kullanici_id, anahtar, isim))
        conn.commit()
        return {"anahtar": anahtar, "isim": isim, "kullanici_id": kullanici_id}
    finally:
        conn.close()

def api_anahtar_dogrula(anahtar: str) -> Optional[dict]:
    """API anahtarını doğrula ve kullanıcı bilgisini döndür."""
    conn = get_db()
    try:
        row = conn.execute("""
            SELECT a.*, k.email, k.ad
            FROM api_anahtarlari a
            JOIN kullanicilar k ON a.kullanici_id = k.id
            WHERE a.anahtar = ? AND a.aktif = 1
        """, (anahtar,)).fetchone()
        if row:
            # Son kullanım güncelle
            conn.execute("""
                UPDATE api_anahtarlari SET
                    son_kullanim = datetime('now'),
                    kullanim_sayisi = kullanim_sayisi + 1
                WHERE anahtar = ?
            """, (anahtar,))
            conn.commit()
            return dict(row)
        return None
    finally:
        conn.close()

def api_anahtarlari_listele(kullanici_id: int) -> list:
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, isim, anahtar, aktif, olusturuldu, son_kullanim, kullanim_sayisi
            FROM api_anahtarlari WHERE kullanici_id = ?
            ORDER BY olusturuldu DESC
        """, (kullanici_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
