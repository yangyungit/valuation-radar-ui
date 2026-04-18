"""yfinance 浏览器指纹会话工具（前端）

2026-04 起 Yahoo Finance 升级 Crumb v2 反爬机制，对云服务商 IP（Render /
Streamlit Cloud 等）全面封禁，默认 `requests.Session()` 会拿到
`HTTP 401 Invalid Crumb`。

解决方案：用 curl_cffi 的浏览器 TLS/HTTP2 指纹伪装 Chrome，绕过反爬。
所有 `yf.download(...)` / `yf.Ticker(t)` 传入 `session=YF_SESSION`。

若 curl_cffi 未安装或失效，降级为 None（yfinance 内部自建默认 Session，
行为等价于旧代码）。

与后端 valuation-radar/_yf_session.py 保持同构——两仓独立部署但策略一致。
"""

try:
    from curl_cffi import requests as _curl_requests
    YF_SESSION = _curl_requests.Session(impersonate="chrome")
except Exception:
    YF_SESSION = None
