import sys
sys.path.append("/Users/zhanghao/.cursor/worktrees/valuation-radar/kbp")
import pandas as pd
import numpy as np

# Mocking enough to run the screener logic
from core_engine import AssetScreener
screener = AssetScreener()

# We can just load data for WMT, MSFT, NVDA, URA
import yfinance as yf
tickers = ["WMT", "MSFT", "NVDA", "URA", "SPY"]
data = yf.download(tickers, period="5y", progress=False)['Close']
data = data.ffill().dropna()

meta_data = {
    "WMT": {"mcap": 500e9},
    "MSFT": {"mcap": 3000e9},
    "NVDA": {"mcap": 2500e9},
    "URA": {"mcap": 1e9},
}

import my_stock_pool
pools = screener.screen(data, meta_data, {})
print("Screened Pools:", pools)

