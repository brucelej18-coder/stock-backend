from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import yfinance as yf
import json
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, date

app = FastAPI(title="미장 AI 관제탑 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

DATA_FILE = "stocks_data.json"

class StockCreate(BaseModel):
    ticker: str
    is_holding: bool = False
    avg_price: Optional[float] = None
    quantity: float = 0.0

class StockUpdate(BaseModel):
    is_holding: bool
    avg_price: Optional[float] = None
    quantity: float = 0.0

def load_data() -> List[Dict[str, Any]]:
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw_list = json.load(f)
            cleaned_list = []
            for item in raw_list:
                if isinstance(item, str):
                    cleaned_list.append({
                        "ticker": item.strip().upper(),
                        "is_holding": False,
                        "avg_price": None,
                        "quantity": 0.0,
                    })
                elif isinstance(item, dict):
                    cleaned_list.append({
                        "ticker": str(item.get("ticker", "")).strip().upper(),
                        "is_holding": bool(item.get("is_holding", False)),
                        "avg_price": item.get("avg_price"),
                        "quantity": float(item.get("quantity", 0.0) or 0.0),
                    })
            return cleaned_list
    except Exception:
        return []

def save_data(data: List[Dict[str, Any]]):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_usd_krw_rate() -> float:
    try:
        url = "https://open.er-api.com/v6/latest/USD"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            return float(res.json().get("rates", {}).get("KRW", 1350.0))
    except Exception:
        pass
    return 1350.0

def get_earnings_info(stock_obj) -> Dict[str, Any]:
    default_earnings = {
        "earnings_date": None,
        "earnings_dday": None,
        "is_earnings_near": False,
    }
    try:
        cal = stock_obj.calendar
        target_dt = None
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                if isinstance(ed, list) and len(ed) > 0:
                    target_dt = ed[0]
                else:
                    target_dt = ed
        elif isinstance(cal, pd.DataFrame) and not cal.empty:
            if "Earnings Date" in cal.index:
                val = cal.loc["Earnings Date"].iloc[0]
                target_dt = val

        if target_dt is not None:
            if isinstance(target_dt, (pd.Timestamp, datetime)):
                ed_date = target_dt.date()
            elif isinstance(target_dt, date):
                ed_date = target_dt
            else:
                ed_date = datetime.strptime(str(target_dt)[:10], "%Y-%m-%d").date()

            today = date.today()
            diff_days = (ed_date - today).days

            if diff_days >= 0:
                return {
                    "earnings_date": ed_date.strftime("%m/%d"),
                    "earnings_dday": diff_days,
                    "is_earnings_near": diff_days <= 10,
                }
    except Exception:
        pass
    return default_earnings

def calculate_target_prices(df: pd.DataFrame, avg_price: Optional[float], current_price: float) -> Dict[str, Any]:
    """
    내 평단가(avg_price)와 차트 지지/저항선을 바탕으로
    맞춤형 목표 익절가, 최적 추가매수가, 손절 방어선을 계산합니다.
    """
    close = df["Close"].dropna()
    high = df["High"].dropna()
    low = df["Low"].dropna()

    ma20 = float(close.rolling(window=20, min_periods=1).mean().iloc[-1]) if len(close) >= 1 else current_price
    recent_high_1m = float(high.iloc[-20:].max()) if len(high) >= 20 else current_price * 1.1
    recent_low_1m = float(low.iloc[-20:].min()) if len(low) >= 20 else current_price * 0.9

    # 1. 최적 추가매수/눌림목 지지가격 (20일선 부근 또는 1개월 저점 반등선)
    buy_target = round(ma20 * 0.995, 2)
    if buy_target > current_price * 0.99:
        buy_target = round(current_price * 0.97, 2)  # 현재가 대비 -3% 눌림 대기선

    # 2. 목표 익절가 계산
    if avg_price and avg_price > 0:
        # 내 평단가가 있을 경우: 평단 기준 +15% 또는 최근 전고점 중 더 유리한 가격
        target_profit_price = round(max(avg_price * 1.15, recent_high_1m, current_price * 1.08), 2)
        # 내 평단가 기준 목표 수익률
        target_profit_rate = round(((target_profit_price - avg_price) / avg_price) * 100.0, 1)

        # 내 평단가 기준 손절 방어선 (-8% 또는 최근 지지선)
        stop_loss_price = round(min(avg_price * 0.92, recent_low_1m), 2)
        stop_loss_rate = round(((stop_loss_price - avg_price) / avg_price) * 100.0, 1)
        is_user_custom = True
    else:
        # 관심 종목: 현재가 기준 +10% 또는 전고점
        target_profit_price = round(max(recent_high_1m, current_price * 1.10), 2)
        target_profit_rate = round(((target_profit_price - current_price) / current_price) * 100.0, 1)

        stop_loss_price = round(min(recent_low_1m, current_price * 0.92), 2)
        stop_loss_rate = round(((stop_loss_price - current_price) / current_price) * 100.0, 1)
        is_user_custom = False

    return {
        "buy_target_price": buy_target,
        "take_profit_price": target_profit_price,
        "take_profit_rate": target_profit_rate,
        "stop_loss_price": stop_loss_price,
        "stop_loss_rate": stop_loss_rate,
        "is_user_custom": is_user_custom,
    }

def analyze_chart_pattern(df: pd.DataFrame, news_sentiment: int) -> Dict[str, Any]:
    default_result = {
        "chart_score": 50,
        "chart_status": "중립 횡보",
        "pattern_label": "데이터 분석 중",
        "action_guide": "충분한 거래 데이터가 쌓일 때까지 관망 권고",
        "is_golden_cross": False,
        "is_pullback": False,
        "is_momentum_exhausted": False,
        "rsi": 50.0,
        "vol_ratio": 100.0,
    }

    if df is None or len(df) < 15:
        return default_result

    try:
        close = df["Close"].dropna()
        volume = df["Volume"].dropna()
        if len(close) < 15:
            return default_result

        ma5 = close.rolling(window=5, min_periods=1).mean()
        ma20 = close.rolling(window=20, min_periods=1).mean()
        ma60 = close.rolling(window=min(60, len(close)), min_periods=1).mean()

        cur_close = float(close.iloc[-1])
        cur_ma5 = float(ma5.iloc[-1])
        cur_ma20 = float(ma20.iloc[-1])
        cur_ma60 = float(ma60.iloc[-1])

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14, min_periods=14).mean()
        avg_loss = loss.rolling(window=14, min_periods=14).mean()

        rsi = 50.0
        if not avg_loss.empty and float(avg_loss.iloc[-1]) > 0:
            rs = float(avg_gain.iloc[-1]) / float(avg_loss.iloc[-1])
            rsi = float(100.0 - (100.0 / (1.0 + rs)))
        elif not avg_gain.empty and float(avg_gain.iloc[-1]) > 0:
            rsi = 100.0

        prev_rsi_max = 50.0
        if len(close) >= 20:
            rs_hist = []
            for idx in range(-5, 0):
                g = avg_gain.iloc[idx]
                l = avg_loss.iloc[idx]
                r = (100.0 - (100.0 / (1.0 + (g / l)))) if l > 0 else 50.0
                rs_hist.append(r)
            prev_rsi_max = max(rs_hist) if rs_hist else rsi

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()

        is_golden_cross = False
        if len(macd) >= 2:
            prev_macd, prev_sig = float(macd.iloc[-2]), float(signal.iloc[-2])
            cur_macd, cur_sig = float(macd.iloc[-1]), float(signal.iloc[-1])
            if prev_macd <= prev_sig and cur_macd > cur_sig:
                is_golden_cross = True

        is_aligned_bull = (cur_ma5 >= cur_ma20) and (cur_ma20 >= cur_ma60)
        dist_to_ma20 = abs(cur_close - cur_ma20) / (cur_ma20 if cur_ma20 > 0 else 1.0)
        is_pullback = is_aligned_bull and (dist_to_ma20 <= 0.03) and (cur_close >= cur_ma20 * 0.97)

        if len(volume) >= 6:
            avg_vol5 = float(volume.iloc[-6:-1].mean())
        else:
            avg_vol5 = float(volume.mean()) if len(volume) > 0 else 1.0
        cur_vol = float(volume.iloc[-1]) if len(volume) > 0 else 1.0
        vol_ratio = (cur_vol / avg_vol5 * 100.0) if avg_vol5 > 0 else 100.0

        is_momentum_exhausted = False
        if (rsi >= 68.0 or prev_rsi_max >= 72.0) and (rsi < prev_rsi_max - 2.0):
            is_momentum_exhausted = True

        score = 50
        if is_aligned_bull:
            score += 20
        elif cur_close < cur_ma20 < cur_ma60:
            score -= 20

        if cur_close > cur_ma20:
            score += 10
        else:
            score -= 10

        if is_golden_cross:
            score += 15

        if is_pullback:
            score += 15

        if is_momentum_exhausted:
            score -= 15
        elif rsi >= 75:
            score -= 10
        elif rsi <= 35:
            score += 10

        score = max(10, min(95, score))

        if is_momentum_exhausted:
            chart_status = "모멘텀 소진 경고"
            pattern_label = "⚠️ 호재 선반영 (분할 익절 권고)"
            action_guide = "상승 모멘텀이 소진되는 구간입니다. 무리한 추가 매수를 멈추고 20~30% 분할 익절을 고려하세요."
        elif score >= 80:
            chart_status = "강력 상승 정배열"
            if is_pullback:
                pattern_label = "🎯 20선 눌림목 반등 타점"
                action_guide = "정배열 상승 중 건전한 조정 구간. 적극 추가 매수 유효"
            elif is_golden_cross:
                pattern_label = "⚡ MACD 골든크로스 발생"
                action_guide = "단기 상승 변곡점 돌파. 비중 확대 또는 신규 진입 적기"
            else:
                pattern_label = "🔥 달리는 말 (강한 추세)"
                action_guide = "추세가 강력합니다. 꺾이기 전까지 흔들림 없이 홀딩"
        elif score >= 60:
            chart_status = "상승 추세 유지"
            pattern_label = "상승 우상향 차트"
            action_guide = "기존 물량 홀딩 유지. 무리한 불타기보다는 관망"
        elif score >= 40:
            chart_status = "박스권 횡보"
            if rsi >= 70:
                pattern_label = "⚠️ 단기 과열 (과매수 구간)"
                action_guide = "상승 피로 누적 상태. 호재 소멸 시 분할 익절 고려"
            else:
                pattern_label = "방향성 탐색 구간"
                action_guide = "20일선 안착 여부를 확인하며 관망"
        else:
            chart_status = "하락 역배열 경고"
            pattern_label = "🔻 지지선 이탈 하락세"
            action_guide = "추세가 꺾였습니다. 신규 매수 금지 및 리스크 관리(손절/비중축소)"

        return {
            "chart_score": int(score),
            "chart_status": chart_status,
            "pattern_label": pattern_label,
            "action_guide": action_guide,
            "is_golden_cross": is_golden_cross,
            "is_pullback": is_pullback,
            "is_momentum_exhausted": is_momentum_exhausted,
            "rsi": round(rsi, 1),
            "vol_ratio": round(vol_ratio, 1),
        }
    except Exception:
        return default_result

@app.get("/api/exchange-rate")
def get_rate():
    return {"rate": get_usd_krw_rate()}

@app.get("/api/stocks")
def get_stocks():
    items = load_data()
    usd_krw = get_usd_krw_rate()
    results = []

    for item in items:
        if isinstance(item, dict):
            ticker = str(item.get("ticker", "")).strip().upper()
            is_holding = bool(item.get("is_holding", False))
            avg_price = item.get("avg_price")
            quantity = float(item.get("quantity", 0.0) or 0.0)
        else:
            ticker = str(item).strip().upper()
            is_holding = False
            avg_price = None
            quantity = 0.0

        if not ticker:
            continue

        try:
            stock_obj = yf.Ticker(ticker)
            hist = stock_obj.history(period="3mo")

            if hist is None or hist.empty:
                continue

            current_price = float(hist["Close"].iloc[-1])
            ma20 = float(hist["Close"].rolling(window=20, min_periods=1).mean().iloc[-1]) if len(hist) >= 1 else current_price

            # 맞춤형 가격 라인 산출 (내 평단가 반영)
            avg_p_float = float(avg_price) if (avg_price and float(avg_price) > 0) else None
            price_targets = calculate_target_prices(hist, avg_p_float, current_price)

            # 뉴스 파싱
            headlines = []
            try:
                raw_news = stock_obj.news or []
                for n in raw_news[:3]:
                    if isinstance(n, dict):
                        t = n.get("title")
                        if not t and "content" in n and isinstance(n["content"], dict):
                            t = n["content"].get("title")
                        if t:
                            headlines.append(str(t))
            except Exception:
                pass

            earnings_info = get_earnings_info(stock_obj)
            chart_analysis = analyze_chart_pattern(hist, len(headlines))

            profit_rate = 0.0
            total_eval_usd = current_price * quantity
            total_eval_krw = int(total_eval_usd * usd_krw)
            profit_loss_krw = 0

            if is_holding and avg_p_float and quantity > 0:
                profit_rate = round(((current_price - avg_p_float) / avg_p_float) * 100.0, 2)
                profit_loss_krw = int((current_price - avg_p_float) * quantity * usd_krw)

            c_score = chart_analysis["chart_score"]

            results.append({
                "ticker": ticker,
                "current_price": round(current_price, 2),
                "ma20": round(ma20, 2),
                "is_holding": is_holding,
                "avg_price": avg_price,
                "quantity": quantity,
                "profit_rate": profit_rate,
                "total_eval_usd": round(total_eval_usd, 2),
                "total_eval_krw": total_eval_krw,
                "profit_loss_krw": profit_loss_krw,
                "exchange_rate": usd_krw,
                "status": "SELL" if chart_analysis["is_momentum_exhausted"] or c_score <= 35 else ("BUY" if c_score >= 80 else "HOLD"),
                "advice": chart_analysis["action_guide"],
                "chart_score": c_score,
                "chart_status": chart_analysis["chart_status"],
                "pattern_label": chart_analysis["pattern_label"],
                "is_pullback": chart_analysis["is_pullback"],
                "is_golden_cross": chart_analysis["is_golden_cross"],
                "is_momentum_exhausted": chart_analysis["is_momentum_exhausted"],
                "earnings_date": earnings_info["earnings_date"],
                "earnings_dday": earnings_info["earnings_dday"],
                "is_earnings_near": earnings_info["is_earnings_near"],
                # 🎯 내 평단가 연동 정밀 매수/익절/손절가
                "buy_target_price": price_targets["buy_target_price"],
                "take_profit_price": price_targets["take_profit_price"],
                "take_profit_rate": price_targets["take_profit_rate"],
                "stop_loss_price": price_targets["stop_loss_price"],
                "stop_loss_rate": price_targets["stop_loss_rate"],
                "is_user_custom": price_targets["is_user_custom"],
                "rsi": chart_analysis["rsi"],
                "volume_ratio": chart_analysis["vol_ratio"],
                "is_volume_surge": chart_analysis["vol_ratio"] >= 180.0,
                "sentiment_label": "긍정" if c_score >= 65 else ("주의" if c_score <= 40 else "중립"),
                "sentiment_score": (c_score - 50) // 10,
                "headlines": headlines,
            })
        except Exception:
            continue

    return results

@app.post("/api/stocks")
def add_stock(stock: StockCreate):
    items = load_data()
    ticker = stock.ticker.strip().upper()

    for it in items:
        cur_t = it.get("ticker", "") if isinstance(it, dict) else str(it)
        if cur_t.upper() == ticker:
            raise HTTPException(status_code=400, detail="이미 등록된 종목입니다.")

    items.append({
        "ticker": ticker,
        "is_holding": stock.is_holding,
        "avg_price": stock.avg_price,
        "quantity": stock.quantity,
    })
    save_data(items)
    return {"message": f"{ticker} 등록 완료"}

@app.put("/api/stocks/{ticker}")
def update_stock(ticker: str, stock: StockUpdate):
    items = load_data()
    target_ticker = ticker.strip().upper()
    found = False

    for it in items:
        cur_t = it.get("ticker", "") if isinstance(it, dict) else str(it)
        if cur_t.upper() == target_ticker:
            if isinstance(it, dict):
                it["is_holding"] = stock.is_holding
                it["avg_price"] = stock.avg_price
                it["quantity"] = stock.quantity
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail="해당 종목을 찾을 수 없습니다.")

    save_data(items)
    return {"message": f"{target_ticker} 수정 완료"}

@app.delete("/api/stocks/{ticker}")
def delete_stock(ticker: str):
    items = load_data()
    target_ticker = ticker.strip().upper()
    new_items = []
    for it in items:
        cur_t = it.get("ticker", "") if isinstance(it, dict) else str(it)
        if cur_t.upper() != target_ticker:
            new_items.append(it)

    if len(items) == len(new_items):
        raise HTTPException(status_code=404, detail="해당 종목을 찾을 수 없습니다.")

    save_data(new_items)
    return {"message": f"{target_ticker} 삭제 완료"}

@app.get("/api/stocks/{ticker}/chart")
def get_chart_data(ticker: str):
    try:
        stock = yf.Ticker(ticker.upper())
        hist = stock.history(period="1mo")
        if hist is None or hist.empty:
            return []

        candles = []
        for index, row in hist.iterrows():
            candles.append({
                "date": index.strftime("%m/%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })
        return candles
    except Exception:
        return []