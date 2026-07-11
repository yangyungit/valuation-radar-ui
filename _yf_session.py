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


# ── 临时调试：排查 Streamlit Cloud Segmentation fault 触发点，定位到后删除 ──
def _install_yf_trace():
    import time
    import yfinance as _yf

    def _log(msg):
        print(f"[YF_TRACE {time.strftime('%H:%M:%S')}] {msg}", flush=True)

    _orig_download = _yf.download

    def _traced_download(*args, **kwargs):
        _tk = args[0] if args else kwargs.get("tickers")
        _log(f"download START tickers={_tk}")
        try:
            r = _orig_download(*args, **kwargs)
            _log(f"download DONE tickers={_tk}")
            return r
        except BaseException as e:
            _log(f"download EXC tickers={_tk} err={e!r}")
            raise

    _yf.download = _traced_download

    _TRACE_ATTRS = {"history", "info", "fast_info", "financials", "balance_sheet", "cashflow"}
    _orig_ticker = _yf.Ticker

    class _TracedTicker(_orig_ticker):
        def __getattribute__(self, name):
            if name in _TRACE_ATTRS:
                _tk = object.__getattribute__(self, "ticker")
                _log(f"{_tk}.{name} ACCESS_START")
            attr = super().__getattribute__(name)
            if name in _TRACE_ATTRS and callable(attr):
                def _wrapped(*a, **kw):
                    try:
                        r = attr(*a, **kw)
                        _log(f"{self.ticker}.{name} DONE")
                        return r
                    except BaseException as e:
                        _log(f"{self.ticker}.{name} EXC err={e!r}")
                        raise
                return _wrapped
            if name in _TRACE_ATTRS:
                _log(f"{self.ticker}.{name} ACCESS_DONE")
            return attr

    _yf.Ticker = _TracedTicker
    _log("yfinance trace installed")


try:
    _install_yf_trace()
except Exception as _e:
    print(f"[YF_TRACE] install failed: {_e!r}", flush=True)
