import yfinance as yf
hist = yf.Ticker("AAPL").history(period="5y")
print("AAPL rows:", len(hist))
print("AAPL start:", hist.index.min() if not hist.empty else "N/A")
