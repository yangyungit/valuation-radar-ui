import yfinance as yf
info = yf.Ticker("BTC").info
print("Name:", info.get('shortName', 'N/A'))
