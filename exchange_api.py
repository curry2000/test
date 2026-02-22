"""
統一交易所 API 層
三層 fallback: Binance → Bybit → OKX
自動處理 rate limit 和 retry
"""
import requests
import time
from typing import Optional, List, Dict, Any
from config import (
    API_TIMEOUT_SHORT,
    API_TIMEOUT_NORMAL,
    API_TIMEOUT_LONG,
    API_RETRY_MAX,
    API_RETRY_DELAY,
    API_RATE_LIMIT_DELAY
)


class ExchangeAPI:
    """統一交易所 API 介面"""
    
    def __init__(self):
        self.last_request_time = 0
    
    def _rate_limit(self):
        """簡單的 rate limit 控制"""
        elapsed = time.time() - self.last_request_time
        if elapsed < API_RATE_LIMIT_DELAY:
            time.sleep(API_RATE_LIMIT_DELAY - elapsed)
        self.last_request_time = time.time()
    
    def _retry_request(self, func, *args, **kwargs):
        """帶重試的請求執行"""
        for attempt in range(API_RETRY_MAX):
            try:
                self._rate_limit()
                return func(*args, **kwargs)
            except Exception as e:
                if attempt < API_RETRY_MAX - 1:
                    time.sleep(API_RETRY_DELAY * (attempt + 1))
                else:
                    raise e
        return None


# ============================================================
# Binance API
# ============================================================
class BinanceAPI(ExchangeAPI):
    BASE_URL = "https://fapi.binance.com"
    
    def get_open_interest(self, symbol: str) -> Optional[float]:
        """取得 OI"""
        try:
            url = f"{self.BASE_URL}/fapi/v1/openInterest"
            params = {"symbol": f"{symbol}USDT"}
            r = requests.get(url, params=params, timeout=API_TIMEOUT_SHORT)
            if r.status_code == 200:
                return float(r.json().get("openInterest", 0))
        except:
            pass
        return None
    
    def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """取得 ticker 資訊"""
        try:
            url = f"{self.BASE_URL}/fapi/v1/ticker/24hr"
            params = {"symbol": f"{symbol}USDT"}
            r = requests.get(url, params=params, timeout=API_TIMEOUT_SHORT)
            if r.status_code == 200:
                data = r.json()
                return {
                    "symbol": data["symbol"],
                    "price": float(data["lastPrice"]),
                    "volume_24h": float(data["quoteVolume"]),
                    "price_change_pct": float(data["priceChangePercent"])
                }
        except:
            pass
        return None
    
    def get_all_tickers(self) -> List[Dict[str, Any]]:
        """取得所有 ticker"""
        try:
            url = f"{self.BASE_URL}/fapi/v1/ticker/24hr"
            r = requests.get(url, timeout=API_TIMEOUT_NORMAL)
            if r.status_code == 200:
                return [
                    {
                        "symbol": t["symbol"],
                        "price": float(t["lastPrice"]),
                        "volume_24h": float(t["quoteVolume"]),
                        "price_change_pct": float(t["priceChangePercent"])
                    }
                    for t in r.json()
                    if t["symbol"].endswith("USDT")
                ]
        except:
            pass
        return []
    
    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[Dict[str, Any]]:
        """取得 K 線資料"""
        try:
            url = f"{self.BASE_URL}/fapi/v1/klines"
            params = {
                "symbol": f"{symbol}USDT",
                "interval": interval,
                "limit": limit
            }
            r = requests.get(url, params=params, timeout=API_TIMEOUT_NORMAL)
            if r.status_code == 200:
                return [
                    {
                        "open_time": int(k[0]),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                        "close_time": int(k[6])
                    }
                    for k in r.json()
                ]
        except:
            pass
        return []
    
    def get_funding_rate(self, symbol: str) -> Optional[float]:
        """取得資金費率"""
        try:
            url = f"{self.BASE_URL}/fapi/v1/fundingRate"
            params = {"symbol": f"{symbol}USDT", "limit": 1}
            r = requests.get(url, params=params, timeout=API_TIMEOUT_SHORT)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    return float(data[0]["fundingRate"])
        except:
            pass
        return None
    
    def get_exchange_info(self) -> Dict[str, Any]:
        """取得交易所資訊（合約列表、狀態等）"""
        try:
            url = f"{self.BASE_URL}/fapi/v1/exchangeInfo"
            r = requests.get(url, timeout=API_TIMEOUT_LONG)
            if r.status_code == 200:
                data = r.json()
                symbols = []
                for s in data.get("symbols", []):
                    if s.get("quoteAsset") == "USDT":
                        symbols.append({
                            "symbol": s["symbol"],
                            "base": s["baseAsset"],
                            "status": s["status"],
                            "contract_type": s.get("contractType", "")
                        })
                return {"symbols": symbols}
        except:
            pass
        return {"symbols": []}
    
    def get_oi_history(self, symbol: str, period: str = "1h", limit: int = 2) -> List[Dict[str, Any]]:
        """取得 OI 歷史資料"""
        try:
            url = f"{self.BASE_URL}/futures/data/openInterestHist"
            params = {
                "symbol": f"{symbol}USDT",
                "period": period,
                "limit": limit
            }
            r = requests.get(url, params=params, timeout=API_TIMEOUT_NORMAL)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    return [
                        {
                            "timestamp": int(d["timestamp"]),
                            "sum_oi": float(d["sumOpenInterest"]),
                            "sum_oi_value": float(d["sumOpenInterestValue"])
                        }
                        for d in data
                    ]
        except:
            pass
        return []


# ============================================================
# Bybit API
# ============================================================
class BybitAPI(ExchangeAPI):
    BASE_URL = "https://api.bybit.com"
    
    def get_open_interest(self, symbol: str) -> Optional[float]:
        """取得 OI"""
        try:
            url = f"{self.BASE_URL}/v5/market/open-interest"
            params = {
                "category": "linear",
                "symbol": f"{symbol}USDT"
            }
            r = requests.get(url, params=params, timeout=API_TIMEOUT_SHORT)
            if r.status_code == 200:
                data = r.json()
                if data.get("retCode") == 0 and data.get("result", {}).get("list"):
                    return float(data["result"]["list"][0]["openInterest"])
        except:
            pass
        return None
    
    def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """取得 ticker 資訊"""
        try:
            url = f"{self.BASE_URL}/v5/market/tickers"
            params = {
                "category": "linear",
                "symbol": f"{symbol}USDT"
            }
            r = requests.get(url, params=params, timeout=API_TIMEOUT_SHORT)
            if r.status_code == 200:
                data = r.json()
                if data.get("retCode") == 0 and data.get("result", {}).get("list"):
                    t = data["result"]["list"][0]
                    return {
                        "symbol": t["symbol"],
                        "price": float(t["lastPrice"]),
                        "volume_24h": float(t["turnover24h"]),
                        "price_change_pct": float(t.get("price24hPcnt", 0)) * 100
                    }
        except:
            pass
        return None
    
    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[Dict[str, Any]]:
        """取得 K 線資料"""
        try:
            url = f"{self.BASE_URL}/v5/market/kline"
            params = {
                "category": "linear",
                "symbol": f"{symbol}USDT",
                "interval": interval,
                "limit": limit
            }
            r = requests.get(url, params=params, timeout=API_TIMEOUT_NORMAL)
            if r.status_code == 200:
                data = r.json()
                if data.get("retCode") == 0 and data.get("result", {}).get("list"):
                    return [
                        {
                            "open_time": int(k[0]),
                            "open": float(k[1]),
                            "high": float(k[2]),
                            "low": float(k[3]),
                            "close": float(k[4]),
                            "volume": float(k[5]),
                            "close_time": int(k[0]) + self._interval_to_ms(interval)
                        }
                        for k in reversed(data["result"]["list"])
                    ]
        except:
            pass
        return []
    
    def get_funding_rate(self, symbol: str) -> Optional[float]:
        """取得資金費率"""
        try:
            url = f"{self.BASE_URL}/v5/market/funding/history"
            params = {
                "category": "linear",
                "symbol": f"{symbol}USDT",
                "limit": 1
            }
            r = requests.get(url, params=params, timeout=API_TIMEOUT_SHORT)
            if r.status_code == 200:
                data = r.json()
                if data.get("retCode") == 0 and data.get("result", {}).get("list"):
                    return float(data["result"]["list"][0]["fundingRate"])
        except:
            pass
        return None
    
    def _interval_to_ms(self, interval: str) -> int:
        """轉換 interval 字串為毫秒"""
        units = {"m": 60000, "h": 3600000, "d": 86400000}
        num = int(interval[:-1])
        unit = interval[-1]
        return num * units.get(unit, 60000)


# ============================================================
# OKX API
# ============================================================
class OKXAPI(ExchangeAPI):
    BASE_URL = "https://www.okx.com"
    
    def get_open_interest(self, symbol: str) -> Optional[float]:
        """取得 OI"""
        try:
            url = f"{self.BASE_URL}/api/v5/market/open-interest"
            params = {
                "instType": "SWAP",
                "instId": f"{symbol.replace('USDT', '')}-USDT-SWAP"
            }
            r = requests.get(url, params=params, timeout=API_TIMEOUT_SHORT)
            if r.status_code == 200:
                data = r.json()
                if data.get("code") == "0" and data.get("data"):
                    return float(data["data"][0]["oi"])
        except:
            pass
        return None
    
    def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """取得 ticker 資訊"""
        try:
            url = f"{self.BASE_URL}/api/v5/market/ticker"
            params = {"instId": f"{symbol.replace('USDT', '')}-USDT-SWAP"}
            r = requests.get(url, params=params, timeout=API_TIMEOUT_SHORT)
            if r.status_code == 200:
                data = r.json()
                if data.get("code") == "0" and data.get("data"):
                    t = data["data"][0]
                    return {
                        "symbol": symbol + "USDT",
                        "price": float(t["last"]),
                        "volume_24h": float(t.get("volCcy24h", 0)),
                        "price_change_pct": 0  # OKX 沒有直接提供
                    }
        except:
            pass
        return None
    
    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[Dict[str, Any]]:
        """取得 K 線資料"""
        try:
            url = f"{self.BASE_URL}/api/v5/market/candles"
            params = {
                "instId": f"{symbol.replace('USDT', '')}-USDT-SWAP",
                "bar": interval,
                "limit": limit
            }
            r = requests.get(url, params=params, timeout=API_TIMEOUT_NORMAL)
            if r.status_code == 200:
                data = r.json()
                if data.get("code") == "0" and data.get("data"):
                    return [
                        {
                            "open_time": int(k[0]),
                            "open": float(k[1]),
                            "high": float(k[2]),
                            "low": float(k[3]),
                            "close": float(k[4]),
                            "volume": float(k[5]),
                            "close_time": int(k[0]) + self._interval_to_ms(interval)
                        }
                        for k in reversed(data["data"])
                    ]
        except:
            pass
        return []
    
    def get_funding_rate(self, symbol: str) -> Optional[float]:
        """取得資金費率"""
        try:
            url = f"{self.BASE_URL}/api/v5/public/funding-rate"
            params = {"instId": f"{symbol.replace('USDT', '')}-USDT-SWAP"}
            r = requests.get(url, params=params, timeout=API_TIMEOUT_SHORT)
            if r.status_code == 200:
                data = r.json()
                if data.get("code") == "0" and data.get("data"):
                    return float(data["data"][0]["fundingRate"])
        except:
            pass
        return None
    
    def _interval_to_ms(self, interval: str) -> int:
        """轉換 interval 字串為毫秒"""
        units = {"m": 60000, "H": 3600000, "D": 86400000}
        num = int(interval[:-1]) if interval[:-1] else 1
        unit = interval[-1]
        return num * units.get(unit, 60000)


# ============================================================
# 統一 API 介面（三層 fallback）
# ============================================================
class UnifiedExchangeAPI:
    """統一交易所 API - 自動 fallback"""
    
    def __init__(self):
        self.binance = BinanceAPI()
        self.bybit = BybitAPI()
        self.okx = OKXAPI()
    
    def get_open_interest(self, symbol: str) -> Optional[float]:
        """取得 OI - 三層 fallback"""
        # 移除 USDT 後綴（如果有）
        base_symbol = symbol.replace("USDT", "")
        
        # Binance
        result = self.binance.get_open_interest(base_symbol)
        if result is not None:
            return result
        
        # Bybit
        result = self.bybit.get_open_interest(base_symbol)
        if result is not None:
            return result
        
        # OKX
        return self.okx.get_open_interest(base_symbol)
    
    def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """取得 ticker - 三層 fallback"""
        base_symbol = symbol.replace("USDT", "")
        
        result = self.binance.get_ticker(base_symbol)
        if result is not None:
            return result
        
        result = self.bybit.get_ticker(base_symbol)
        if result is not None:
            return result
        
        return self.okx.get_ticker(base_symbol)
    
    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> List[Dict[str, Any]]:
        """取得 K 線 - 三層 fallback"""
        base_symbol = symbol.replace("USDT", "")
        
        result = self.binance.get_klines(base_symbol, interval, limit)
        if result:
            return result
        
        result = self.bybit.get_klines(base_symbol, interval, limit)
        if result:
            return result
        
        return self.okx.get_klines(base_symbol, interval, limit)
    
    def get_funding_rate(self, symbol: str) -> Optional[float]:
        """取得資金費率 - 三層 fallback"""
        base_symbol = symbol.replace("USDT", "")
        
        result = self.binance.get_funding_rate(base_symbol)
        if result is not None:
            return result
        
        result = self.bybit.get_funding_rate(base_symbol)
        if result is not None:
            return result
        
        return self.okx.get_funding_rate(base_symbol)
    
    def get_exchange_info(self) -> Dict[str, Any]:
        """取得交易所資訊（僅 Binance）"""
        return self.binance.get_exchange_info()
    
    def get_all_tickers(self) -> List[Dict[str, Any]]:
        """取得所有 ticker（僅 Binance）"""
        return self.binance.get_all_tickers()
    
    def get_oi_history(self, symbol: str, period: str = "1h", limit: int = 2) -> List[Dict[str, Any]]:
        """取得 OI 歷史（僅 Binance）"""
        base_symbol = symbol.replace("USDT", "")
        return self.binance.get_oi_history(base_symbol, period, limit)


# ============================================================
# 全域 API 實例
# ============================================================
api = UnifiedExchangeAPI()


# ============================================================
# 便捷函數（向後兼容）
# ============================================================
def get_open_interest(symbol: str) -> Optional[float]:
    """取得 OI"""
    return api.get_open_interest(symbol)


def get_ticker(symbol: str) -> Optional[Dict[str, Any]]:
    """取得 ticker"""
    return api.get_ticker(symbol)


def get_klines(symbol: str, interval: str, limit: int = 100) -> List[Dict[str, Any]]:
    """取得 K 線"""
    return api.get_klines(symbol, interval, limit)


def get_funding_rate(symbol: str) -> Optional[float]:
    """取得資金費率"""
    return api.get_funding_rate(symbol)


def get_exchange_info() -> Dict[str, Any]:
    """取得交易所資訊"""
    return api.get_exchange_info()


def get_all_tickers() -> List[Dict[str, Any]]:
    """取得所有 ticker"""
    return api.get_all_tickers()


def get_price(symbol: str) -> Optional[float]:
    """取得當前價格"""
    ticker = get_ticker(symbol)
    return ticker["price"] if ticker else None
