import yfinance as yf
hist = yf.Ticker("BTC").history(period="5y")
print("BTC rows:", len(hist))
print("BTC start:", hist.index.min() if not hist.empty else "N/A")
