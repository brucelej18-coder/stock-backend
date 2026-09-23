import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import yfinance as yf
import pandas as pd
import numpy as np
import urllib.request
import urllib.parse

app = FastAPI(title="Stock Watchtower AI Strategy Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "stocks_data.json")

DEFAULT_STOCKS = [
    {"ticker": "VRT", "is_holding": True, "avg_price": 243.44, "quantity": 0.082439},
    {"ticker": "AVGO", "is_holding": True, "avg_price": 348.93, "quantity": 0.136757},
    {"ticker": "GOOGL", "is_holding": True, "avg_price": 350.13, "quantity": 0.274143},
    {"ticker": "AAPL", "is_holding": True, "avg_price": 308.57, "quantity": 0.337598},
    {"ticker": "SPYG", "is_holding": True, "avg_price": 118.3, "quantity": 1.304608}
]

def load_stocks():
    if not os.path.exists(DATA_FILE):
        save_stocks(DEFAULT_STOCKS)
        return DEFAULT_STOCKS
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list) or len(data) == 0:
                return DEFAULT_STOCKS
            return data
    except Exception:
        return DEFAULT_STOCKS

def save_stocks(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving stocks: {e}")

class StockItem(BaseModel):
    ticker: str
    is_holding: bool
    avg_price: Optional[float] = None
    quantity: Optional[float] = 0.0

def translate_to_korean(text: str) -> str:
    """영문 뉴스를 한국어로 간이 번역하는 안전 함수"""
    if not text:
        return ""
    try:
        url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&q=" + urllib.parse.quote(text)
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            translated = "".join([part[0] for part in data[0] if part[0]])
            return translated
    except Exception:
        return text

def fetch_safe_news(ticker: str):
    news_items = []
    try:
        t = yf.Ticker(ticker)
        raw_news = getattr(t, "news", []) or []
        for n in raw_news[:2]:
            title = n.get("title") or (n.get("content", {}).get("title") if isinstance(n.get("content"), dict) else "")
            publisher = n.get("publisher") or (n.get("content", {}).get("provider", {}).get("displayName") if isinstance(n.get("content"), dict) else "MarketNews")
            link = n.get("link") or (n.get("content", {}).get("canonicalUrl", {}).get("url") if isinstance(n.get("content"), dict) else "")
            if title:
                ko_title = translate_to_korean(str(title))
                news_items.append({
                    "title": ko_title,
                    "publisher": str(publisher or "MarketNews"),
                    "link": str(link or f"https://finance.yahoo.com/quote/{ticker}")
                })
    except Exception as e:
        print(f"News fetch error for {ticker}: {e}")

    if not news_items:
        news_items = [
            {"title": f"{ticker} 기술적 수급 분석 및 AI 매매 가격대 산출 완료", "publisher": "Stock Watchtower AI", "link": f"https://finance.yahoo.com/quote/{ticker}"}
        ]
    return news_items

def calculate_ai_strategy(close_series, high_series, low_series, current_price, avg_price, is_holding):
    ma20 = float(close_series.rolling(window=min(20, len(close_series))).mean().iloc[-1])
    std20 = float(close_series.rolling(window=min(20, len(close_series))).std().iloc[-1])
    
    bb_upper = ma20 + (std20 * 2.0)
    bb_lower = ma20 - (std20 * 2.0)
    
    recent_high = float(high_series.tail(20).max())
    recent_low = float(low_series.tail(20).min())
    
    tr = pd.concat([
        high_series - low_series,
        (high_series - close_series.shift(1)).abs(),
        (low_series - close_series.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = float(tr.rolling(window=14).mean().iloc[-1]) if len(tr) >= 14 else (current_price * 0.03)

    resistance = max(bb_upper, recent_high)
    if resistance <= current_price:
        target_sell = round(current_price + (atr * 1.8), 2)
    else:
        target_sell = round(resistance, 2)

    if current_price > ma20:
        target_buy = round(ma20, 2)
    else:
        target_buy = round(max(bb_lower, recent_low), 2)

    support = min(ma20, bb_lower)
    ai_stop_loss = round(support - (atr * 0.8), 2)
    if ai_stop_loss >= current_price or (current_price - ai_stop_loss) > (current_price * 0.12):
        ai_stop_loss = round(current_price - (atr * 1.5), 2)

    return target_sell, target_buy, ai_stop_loss

def analyze_ticker_full(item: dict, exchange_rate: float):
    raw_ticker = str(item.get("ticker", "VRT")).upper().strip()
    ticker = "GOOGL" if raw_ticker == "GOOGLE" else raw_ticker
    
    is_holding = bool(item.get("is_holding", True))
    avg_price = float(item["avg_price"]) if item.get("avg_price") is not None else None
    quantity = float(item.get("quantity", 0.0) or 0.0)

    news_items = fetch_safe_news(ticker)
    candles = []

    try:
        df = yf.download(ticker, period="1mo", interval="1d", progress=False)
        if df is None or len(df) < 5:
            raise ValueError("데이터 부족")

        if isinstance(df.columns, pd.MultiIndex):
            close_s = df["Close"][ticker].dropna()
            open_s = df["Open"][ticker].dropna()
            high_s = df["High"][ticker].dropna()
            low_s = df["Low"][ticker].dropna()
        else:
            close_s = df["Close"].dropna()
            open_s = df["Open"].dropna()
            high_s = df["High"].dropna()
            low_s = df["Low"].dropna()

        current_price = float(close_s.iloc[-1])

        # 최근 15개 봉의 양봉/음봉 캔들 데이터 추출 [Open, High, Low, Close]
        recent_df = pd.DataFrame({'Open': open_s, 'High': high_s, 'Low': low_s, 'Close': close_s}).tail(15)
        for _, row in recent_df.iterrows():
            candles.append({
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2)
            })

        ma5 = float(close_s.rolling(window=min(5, len(close_s))).mean().iloc[-1])
        ma20 = float(close_s.rolling(window=min(20, len(close_s))).mean().iloc[-1])
        ma60 = float(close_s.rolling(window=min(60, len(close_s))).mean().iloc[-1]) if len(close_s) >= 60 else ma20

        delta = close_s.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(min(14, len(close_s))).mean().iloc[-1]
        avg_loss = loss.rolling(min(14, len(close_s))).mean().iloc[-1]
        rsi = 50.0
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi = float(100 - (100 / (1 + rs)))

        ema12 = close_s.ewm(span=12, adjust=False).mean()
        ema26 = close_s.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd = float(macd_line.iloc[-1])
        macd_sig = float(signal_line.iloc[-1])

        score = 50
        if current_price > ma20: score += 12
        if ma5 > ma20: score += 8
        if current_price > ma60: score += 5
        if 40 <= rsi <= 60: score += 10
        elif rsi < 30: score += 15
        elif rsi > 70: score -= 15
        if macd > macd_sig: score += 10
        if macd > 0: score += 5
        ai_score = int(min(max(score, 15), 98))

        target_sell, target_buy, stop_loss = calculate_ai_strategy(
            close_s, high_s, low_s, current_price, avg_price, is_holding
        )

    except Exception as e:
        print(f"Fallback for {ticker}: {e}")
        current_price = avg_price if (avg_price and avg_price > 0) else 100.0
        candles = [{"open": current_price, "high": current_price, "low": current_price, "close": current_price}] * 10
        ma5 = ma20 = ma60 = current_price
        rsi = 50.0
        macd = 0.0
        ai_score = 65
        target_sell = round(current_price * 1.07, 2)
        target_buy = round(current_price * 0.96, 2)
        stop_loss = round(current_price * 0.93, 2)

    profit_rate = 0.0
    profit_krw = 0
    eval_krw = int(current_price * quantity * exchange_rate) if (quantity and quantity > 0) else 0

    if avg_price and avg_price > 0:
        profit_rate = round(((current_price - avg_price) / avg_price) * 100, 2)
        profit_krw = int((current_price - avg_price) * quantity * exchange_rate)

    return {
        "ticker": ticker,
        "is_holding": is_holding,
        "avg_price": avg_price,
        "quantity": quantity,
        "current_price": round(current_price, 2),
        "ai_score": ai_score,
        "rsi": round(rsi, 1),
        "macd": round(macd, 2),
        "ma5": round(ma5, 2),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
        "target_sell": target_sell,
        "target_buy": target_buy,
        "stop_loss": stop_loss,
        "profit_rate": profit_rate,
        "profit_krw": profit_krw,
        "eval_krw": eval_krw,
        "candles": candles,
        "news": news_items,
        "exchange_rate": exchange_rate
    }

@app.get("/")
def root():
    return {"status": "ok", "message": "Stock Watchtower Engine Running"}

@app.get("/api/stocks")
def get_stocks():
    stocks = load_stocks()
    rate = 1350.0
    try:
        usd_df = yf.download("KRW=X", period="1d", progress=False)
        if usd_df is not None and not usd_df.empty:
            if isinstance(usd_df.columns, pd.MultiIndex):
                rate = float(usd_df["Close"].iloc[-1].values[0])
            else:
                rate = float(usd_df["Close"].iloc[-1])
    except Exception:
        pass

    return [analyze_ticker_full(s, rate) for s in stocks]

@app.post("/api/stocks")
def add_stock(item: StockItem):
    stocks = load_stocks()
    ticker_up = item.ticker.upper().strip()
    if ticker_up == "GOOGLE":
        ticker_up = "GOOGL"

    for s in stocks:
        if s.get("ticker", "").upper() == ticker_up:
            raise HTTPException(status_code=400, detail="이미 등록된 종목입니다.")

    stocks.append({
        "ticker": ticker_up,
        "is_holding": item.is_holding,
        "avg_price": item.avg_price,
        "quantity": item.quantity
    })
    save_stocks(stocks)
    return {"status": "success", "message": f"{ticker_up} 등록 완료"}

@app.delete("/api/stocks/{ticker}")
def delete_stock(ticker: str):
    stocks = load_stocks()
    ticker_up = ticker.upper().strip()
    if ticker_up == "GOOGLE":
        ticker_up = "GOOGL"

    new_stocks = [s for s in stocks if s.get("ticker", "").upper() != ticker_up]
    if len(new_stocks) == len(stocks):
        raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다.")
    save_stocks(new_stocks)
    return {"status": "success", "message": f"{ticker_up} 삭제 완료"}