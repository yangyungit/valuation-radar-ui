path = "/Users/zhanghao/yangyun/Code_Projects/valuation-radar-ui/api_client.py"
with open(path, "r") as f:
    content = f.read()

content = content.replace(
    "data = yf.download(tickers, start=start_date, end=end_date, progress=False)['Close']",
    "data = yf.download(tickers, start=start_date, end=end_date, progress=False, threads=False)['Close']"
)

content = content.replace(
    "retry_data = yf.download(missing_tickers, start=start_date, end=end_date, progress=False)",
    "retry_data = yf.download(missing_tickers, start=start_date, end=end_date, progress=False, threads=False)"
)

with open(path, "w") as f:
    f.write(content)
