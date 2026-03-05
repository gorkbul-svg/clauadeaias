"""
tahmin.py — Ensemble Fiyat Tahmin Modeli
LSTM + Prophet + ARIMA → Ağırlıklı ensemble
7 günlük fiyat tahmini üretir.
"""

import numpy as np
import warnings
warnings.filterwarnings("ignore")

from datetime import datetime, timedelta
import yfinance as yf


def bist_ticker(ticker: str) -> str:
    ticker = ticker.upper().strip()
    if not ticker.endswith(".IS"):
        ticker += ".IS"
    return ticker


def veri_getir(ticker: str, yil: int = 2) -> tuple:
    """Geçmiş fiyat verisini çek."""
    stock = yf.Ticker(bist_ticker(ticker))
    df = stock.history(period=f"{yil}y")
    if df.empty:
        raise ValueError(f"{ticker} için veri bulunamadı")
    df = df[["Close"]].dropna()
    df.index = df.index.tz_localize(None)
    return df


# ── ARIMA ────────────────────────────────────────────────
def arima_tahmin(df, gun: int = 7) -> np.ndarray:
    try:
        from statsmodels.tsa.arima.model import ARIMA
        model = ARIMA(df["Close"].values, order=(5, 1, 0))
        fit   = model.fit()
        return fit.forecast(steps=gun)
    except Exception as e:
        # ARIMA başarısız olursa son fiyatı kullan
        son = df["Close"].iloc[-1]
        return np.array([son] * gun)


# ── Prophet ───────────────────────────────────────────────
def prophet_tahmin(df, gun: int = 7) -> np.ndarray:
    try:
        from prophet import Prophet
        prophet_df = df.reset_index()[["Date", "Close"]].rename(
            columns={"Date": "ds", "Close": "y"}
        )
        model = Prophet(
            daily_seasonality=False,
            weekly_seasonality=True,
            yearly_seasonality=True,
            changepoint_prior_scale=0.05
        )
        model.fit(prophet_df)
        gelecek = model.make_future_dataframe(periods=gun)
        tahmin  = model.predict(gelecek)
        return tahmin["yhat"].iloc[-gun:].values
    except Exception:
        son = df["Close"].iloc[-1]
        return np.array([son] * gun)


# ── LSTM ──────────────────────────────────────────────────
def lstm_tahmin(df, gun: int = 7) -> np.ndarray:
    try:
        from sklearn.preprocessing import MinMaxScaler
        import tensorflow as tf

        pencere = 60
        veriler = df["Close"].values.reshape(-1, 1)

        scaler = MinMaxScaler()
        olcekli = scaler.fit_transform(veriler)

        X = []
        for i in range(pencere, len(olcekli)):
            X.append(olcekli[i-pencere:i, 0])
        X = np.array(X).reshape(-1, pencere, 1)

        model = tf.keras.Sequential([
            tf.keras.layers.LSTM(50, return_sequences=True, input_shape=(pencere, 1)),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.LSTM(50),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.Dense(1)
        ])
        model.compile(optimizer="adam", loss="mse")
        model.fit(X, olcekli[pencere:], epochs=20, batch_size=32, verbose=0)

        # 7 günlük tahmin
        son_pencere = olcekli[-pencere:].reshape(1, pencere, 1)
        tahminler = []
        for _ in range(gun):
            pred = model.predict(son_pencere, verbose=0)[0, 0]
            tahminler.append(pred)
            son_pencere = np.roll(son_pencere, -1, axis=1)
            son_pencere[0, -1, 0] = pred

        return scaler.inverse_transform(np.array(tahminler).reshape(-1, 1)).flatten()

    except Exception:
        # TensorFlow yoksa basit trend extrapolasyon
        son_30 = df["Close"].iloc[-30:].values
        trend  = np.polyfit(range(len(son_30)), son_30, 1)[0]
        son    = df["Close"].iloc[-1]
        return np.array([son + trend * (i + 1) for i in range(gun)])


# ── Ensemble ─────────────────────────────────────────────
def ensemble_tahmin(ticker: str, gun: int = 7) -> dict:
    """
    3 modelin ağırlıklı ortalamasını döndürür.
    Ağırlıklar: LSTM %40, Prophet %35, ARIMA %25
    """
    df = veri_getir(ticker)
    son_fiyat = float(df["Close"].iloc[-1])

    # 3 model paralel çalıştır
    print(f"[TAHMİN] {ticker} — ARIMA hesaplanıyor...")
    arima  = arima_tahmin(df, gun)

    print(f"[TAHMİN] {ticker} — Prophet hesaplanıyor...")
    prophet = prophet_tahmin(df, gun)

    print(f"[TAHMİN] {ticker} — LSTM hesaplanıyor...")
    lstm   = lstm_tahmin(df, gun)

    # Ağırlıklı ensemble
    W_LSTM, W_PROPHET, W_ARIMA = 0.40, 0.35, 0.25
    ensemble = W_LSTM * lstm + W_PROPHET * prophet + W_ARIMA * arima

    # Güven aralığı (modeller arası std)
    tum_tahminler = np.array([lstm, prophet, arima])
    std = np.std(tum_tahminler, axis=0)
    ust_band = ensemble + 1.5 * std
    alt_band  = ensemble - 1.5 * std

    # Tarih listesi (iş günleri)
    bugun = datetime.now()
    tarihler = []
    gun_sayac = 0
    while len(tarihler) < gun:
        bugun += timedelta(days=1)
        if bugun.weekday() < 5:  # Hafta içi
            tarihler.append(bugun.strftime("%Y-%m-%d"))
            gun_sayac += 1

    # Değişim hesapla
    son_tahmin = float(ensemble[-1])
    degisim_yuzde = round((son_tahmin - son_fiyat) / son_fiyat * 100, 2)
    yon = "▲ Yükseliş" if degisim_yuzde > 0 else "▼ Düşüş"

    # Model güven skoru (std'nin ortalaması / fiyat)
    guven = max(0, min(100, round(100 - (np.mean(std) / son_fiyat * 100 * 10), 0)))

    return {
        "ticker": ticker.upper(),
        "son_fiyat": round(son_fiyat, 2),
        "tahmin_gun": gun,
        "tarihler": tarihler,
        "tahmin": [round(float(x), 2) for x in ensemble],
        "ust_band": [round(float(x), 2) for x in ust_band],
        "alt_band": [round(float(x), 2) for x in alt_band],
        "lstm_tahmin": [round(float(x), 2) for x in lstm],
        "prophet_tahmin": [round(float(x), 2) for x in prophet],
        "arima_tahmin": [round(float(x), 2) for x in arima],
        "7_gun_hedef": round(son_tahmin, 2),
        "degisim_yuzde": degisim_yuzde,
        "yon": yon,
        "guven_skoru": guven,
        "uyari": "Bu tahmin yatırım tavsiyesi değildir. Geçmiş performans geleceği garanti etmez.",
        "model": "Ensemble (LSTM %40 + Prophet %35 + ARIMA %25)"
    }


if __name__ == "__main__":
    import json
    sonuc = ensemble_tahmin("THYAO", gun=7)
    print(json.dumps(sonuc, ensure_ascii=False, indent=2))
