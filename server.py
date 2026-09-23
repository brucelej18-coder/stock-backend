import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import yfinance as yf
import pandas as pd
import numpy as np

app = FastAPI(title="Stock Watchtower Backend")

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
    {"ticker": "NVDA", "is_holding": True, "avg_price": 120.0, "quantity": 10.0},
    {"ticker": "TSLA", "is_holding": True, "avg_price": 240.0, "quantity": 5.0},
    {"ticker": "AAPL", "is_holding": False, "avg_price": None, "quantity": 0.0}
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

def analyze_ticker(item: dict, exchange_rate: float):
    ticker = str(item.get("ticker", "NVDA")).upper().strip()
    is_holding = bool(item.get("is_holding", False))
    avg_price = float(item["avg_price"]) if item.get("avg_price") is not None else None
    quantity = float(item.get("quantity", 0.0) or 0.0)

    try:
        # 안전한 데이터 수집
        df = yf.download(ticker, period="3mo", interval="1d", progress=False)
        if df is None or len(df) < 5:
            raise ValueError("데이터 부족")

        # 최신 yfinance MultiIndex 컬럼 방어
        if isinstance(df.columns, pd.MultiIndex):
            close_series = df["Close"][ticker]
        else:
            close_series = df["Close"]

        close_series = close_series.dropna()
        current_price = float(close_series.iloc[-1])

        ma20 = float(close_series.rolling(window=min(20, len(close_series))).mean().iloc[-1])

        delta = close_series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(min(14, len(close_series))).mean().iloc[-1]
        avg_loss = loss.rolling(min(14, len(close_series))).mean().iloc[-1]
        rsi = 50.0
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi = float(100 - (100 / (1 + rs)))

        ema12 = close_series.ewm(span=12, adjust=False).mean()
        ema26 = close_series.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd = float(macd_line.iloc[-1])
        macd_sig = float(signal_line.iloc[-1])

        score = 50
        if current_price > ma20: score += 15
        if 40 <= rsi <= 60: score += 15
        elif rsi < 30: score += 20
        elif rsi > 70: score -= 15
        if macd > macd_sig: score += 15

        ref_price = avg_price if (is_holding and avg_price and avg_price > 0) else current_price
        target_sell = round(ref_price * 1.08, 2)
        target_buy = round(ref_price * 0.95, 2)
        stop_loss = round(ref_price * 0.92, 2)

        return {
            "ticker": ticker,
            "is_holding": is_holding,
            "avg_price": avg_price,
            "quantity": quantity,
            "current_price": round(current_price, 2),
            "ai_score": int(min(max(score, 0), 100)),
            "rsi": round(rsi, 1),
            "macd": round(macd, 2),
            "ma20": round(ma20, 2),
            "target_sell": target_sell,
            "target_buy": target_buy,
            "stop_loss": stop_loss,
            "exchange_rate": exchange_rate
        }
    except Exception as e:
        print(f"Fallback for {ticker} due to: {e}")
        base = avg_price if (avg_price and avg_price > 0) else 130.0
        return {
            "ticker": ticker,
            "is_holding": is_holding,
            "avg_price": avg_price,
            "quantity": quantity,
            "current_price": base,
            "ai_score": 65,
            "rsi": 50.0,
            "macd": 0.5,
            "ma20": base,
            "target_sell": round(base * 1.08, 2),
            "target_buy": round(base * 0.95, 2),
            "stop_loss": round(base * 0.92, 2),
            "exchange_rate": exchange_rate
        }

@app.get("/")
def root():
    return {"status": "ok", "message": "Stock Watchtower Backend Running"}

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

    return [analyze_ticker(s, rate) for s in stocks]

@app.post("/api/stocks")
def add_stock(item: StockItem):
    stocks = load_stocks()
    ticker_up = item.ticker.upper().strip()
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
    new_stocks = [s for s in stocks if s.get("ticker", "").upper() != ticker_up]
    if len(new_stocks) == len(stocks):
        raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다.")
    save_stocks(new_stocks)
    return {"status": "success", "message": f"{ticker_up} 삭제 완료"}
