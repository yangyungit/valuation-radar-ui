"""yfinance 浏览器指纹会话工具（前端）

2026-04 起 Yahoo Finance 升级 Crumb v2 反爬机制，对云服务商 IP（Render /
Streamlit Cloud 等）全面封禁，默认 `requests.Session()` 会拿到
`HTTP 401 Invalid Crumb`。

解决方案：用 curl_cffi 的浏览器 TLS/HTTP2 指纹伪装 Chrome，绕过反爬。
所有 `yf.download(...)` / `yf.Ticker(t)` 传入 `session=new_yf_session()`。

若 curl_cffi 未安装或失效，降级为 None（yfinance 内部自建默认 Session，
行为等价于旧代码）。

2026-07-11 起改为每次调用新建 session（不再用模块级全局单例）：curl_cffi
的 libcurl 绑定非线程安全，Streamlit 多用户并发共享同一个 session 会触发
curl handle 内部状态冲突，导致进程 Segmentation fault（见
https://github.com/lexiforest/curl_cffi/issues/128）。新建开销很小，换线程安全。

与后端 valuation-radar/_yf_session.py 保持同构——两仓独立部署但策略一致。
"""


def new_yf_session():
    try:
        from curl_cffi import requests as _curl_requests
        return _curl_requests.Session(impersonate="chrome")
    except Exception:
        return None
