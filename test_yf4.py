import yfinance as yf
hist = yf.Ticker("BTC-USD").history(period="5y")
print("BTC-USD rows:", len(hist))
print("BTC-USD start:", hist.index.min() if not hist.empty else "N/A")
