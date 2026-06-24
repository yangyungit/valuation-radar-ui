import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from api_client import fetch_buyback_relay_timeseries
import holdings_viz as hv

st.set_page_config(page_title="回购股接力", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("👑 回购股接力图 (Buyback Relay)")
st.caption(
    "**池子**:回购股.md 第一、二节(教科书级 + 大型现金流机器,排除陷阱版),全美股。"
    "**排名**:每月末在池内做横截面排名,**king_score = 1.0×Z(RS_252d) + 0.8×Z(log10 ADV_63d)** —— "
    "动量(年化跑赢 SPY)+ 容量(美元成交额)两维,与板块王朝接力图同源。"
    "**🥇 金牌 = 当月 Top1 且 RS_252d > 0(跑赢 SPY,否则降灰)/🥈 银牌 = Top2**。"
    "下方持有**金+银两个仓位等权**,月末选仓、顺延 1 月执行(去 look-ahead)。"
)

with st.sidebar:
    if st.button("🔄 强制刷新回购股数据"):
        fetch_buyback_relay_timeseries.clear()
        st.rerun()

_WINDOWS = ["3Y", "5Y", "10Y"]
window = st.radio("时间跨度", _WINDOWS, index=1, horizontal=True, key="bb_window")

with st.spinner("📊 加载回购股接力数据..."):
    ts = fetch_buyback_relay_timeseries(window)

if not ts.get("success"):
    st.error(f"⚠️ 回购股接力数据暂不可用:{ts.get('error', '未知错误')}")
    st.stop()

_tickers = ts.get("tickers", {}) or {}
_dates = ts.get("dates", []) or []
if not _tickers or not _dates:
    st.warning("⚠️ 时序数据为空")
    st.stop()

_idx = pd.to_datetime(_dates, errors="coerce")
king = pd.DataFrame({tk: p.get("king_score", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
rs = pd.DataFrame({tk: p.get("rs", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
adv = pd.DataFrame({tk: p.get("adv_63d", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
name_map = {tk: p.get("name", tk) for tk, p in _tickers.items()}
grade_map = {tk: p.get("group", "") for tk, p in _tickers.items()}
asof = pd.to_datetime(ts.get("asof"), errors="coerce")

# ── 月末快照 + 横截面排名 ──
king_m = king.resample("ME").last()
rs_m = rs.resample("ME").last()
adv_m = adv.resample("ME").last()
if king_m.empty or len(king_m) < 2:
    st.warning("⚠️ 月末快照数据不足")
    st.stop()

rank_m = king_m.rank(axis=1, ascending=False, method="min")
# tier: 0=灰 2=银(Top2) 3=金(Top1 且 RS>0);Top1 但 RS≤0 → 降灰(熊市无王)
tier = pd.DataFrame(0, index=rank_m.index, columns=rank_m.columns, dtype=int)
tier[rank_m <= 2] = 2
tier = tier.mask((rank_m == 1) & (rs_m > 0), 3)
tier = tier.mask((rank_m == 1) & (rs_m <= 0), 0)

_last_month = tier.index[-1]
_month_in_progress = bool(pd.notna(asof) and _last_month.to_period("M").end_time.normalize() > asof.normalize())
_confirmed = tier.iloc[:-1] if _month_in_progress else tier

# 行排序:累计金 → 累计银
_gold_cnt = (_confirmed == 3).sum(axis=0)
_silver_cnt = (_confirmed == 2).sum(axis=0)
_ordered = (_gold_cnt * 10000 + _silver_cnt).sort_values(ascending=False).index.tolist()

# ── 接力热力图 ──
_tier_yx = tier[_ordered].T
_rank_yx = rank_m[_ordered].T
_rs_yx = rs_m[_ordered].T
_king_yx = king_m[_ordered].T
_ylabels = [f"{name_map.get(tk, tk)} ({tk})" for tk in _ordered]
_BADGE = {0: "⚪ 灰", 2: "🥈 银", 3: "🥇 金"}

_hover = []
for tk in _ordered:
    row = []
    for d in _tier_yx.columns:
        t = int(_tier_yx.loc[tk, d])
        rk = _rank_yx.loc[tk, d]
        rsv = _rs_yx.loc[tk, d]
        kv = _king_yx.loc[tk, d]
        _ip = "（进行中）" if (_month_in_progress and d == _last_month) else ""
        _rk_s = f"第 {int(rk)}" if pd.notna(rk) else "—"
        _kv_s = f"{kv:+.2f}" if pd.notna(kv) else "—"
        _rs_s = f"{rsv:+.2f}%" if pd.notna(rsv) else "—"
        row.append(
            f"<b>{name_map.get(tk, tk)} ({tk})</b><br>"
            f"{d.strftime('%Y-%m')}{_ip}<br>"
            f"{_BADGE[t]}<br>"
            f"排名 {_rk_s}<br>"
            f"king_score {_kv_s}<br>"
            f"RS_252d {_rs_s}"
        )
    _hover.append(row)

_xlabels = [
    (f"{d.strftime('%Y-%m')} (进行中)" if (_month_in_progress and d == _last_month) else d.strftime("%Y-%m"))
    for d in _tier_yx.columns
]

fig = go.Figure(data=go.Heatmap(
    z=_tier_yx.values,
    x=list(_tier_yx.columns),
    y=_ylabels,
    colorscale=[
        [0.0, "#2a2a2a"], [0.6, "#2a2a2a"],
        [0.6, "#c0c0c0"], [0.9, "#c0c0c0"],
        [0.9, "#FFD700"], [1.0, "#FFD700"],
    ],
    zmin=0, zmax=3,
    customdata=np.array(_hover, dtype=object),
    hovertemplate="%{customdata}<extra></extra>",
    showscale=False, xgap=1, ygap=1,
))
fig.update_layout(
    height=max(400, 24 * len(_ordered)),
    margin=dict(l=20, r=20, t=40, b=20),
    plot_bgcolor="#111111", paper_bgcolor="#111111",
    font=dict(color="#ddd"),
    xaxis=dict(showgrid=False, side="bottom", tickangle=-45),
    yaxis=dict(showgrid=False, autorange="reversed"),
    title=dict(text=f"{window} 月末回购股接力 · 按 king_score 排名 · {len(_ordered)} 只 · {len(_xlabels)} 月",
               font=dict(size=14), x=0.01, xanchor="left"),
)
st.plotly_chart(fig, use_container_width=True, key="bb_heatmap")

# ── 当前金/银 + 奖牌榜 ──
_last_col = _tier_yx[_last_month]
_gold_now = _last_col[_last_col == 3].index.tolist()
_silver_now = _last_col[_last_col == 2].index.tolist()
_gold_html = " ".join(f"<span class='tag-bull'>🥇 {name_map.get(t, t)} ({t})</span>" for t in _gold_now) \
    or "<span style='color:#888'>当前无金牌(无个股同时满足 Top1 + RS_252d &gt; 0)</span>"
_silver_html = " ".join(f"<span class='tag-bear'>🥈 {name_map.get(t, t)} ({t})</span>" for t in _silver_now) or "—"
_label = "当月领先(进行中·未定格)" if _month_in_progress else "当前在位"
st.markdown(f"""
<div class='insight-box'>
<div class='insight-title'>👑 回购股接力摘要 ({window} · {len(_xlabels)} 个月)</div>
<div style='margin-bottom:6px'>📍 {_label}({_last_month.strftime('%Y-%m')}): {_gold_html} &nbsp; {_silver_html}</div>
</div>
""", unsafe_allow_html=True)

# 奖牌榜表
_medal_rows = []
_conf_yx = _confirmed[_ordered].T
for tk in _ordered:
    trow = _conf_yx.loc[tk].values
    gold = int((trow == 3).sum())
    silver = int((trow == 2).sum())
    streak = cur = 0
    for v in trow:
        if v == 3:
            cur += 1
            streak = max(streak, cur)
        else:
            cur = 0
    gdates = _conf_yx.loc[tk].index[_conf_yx.loc[tk].values == 3]
    _medal_rows.append({
        "股票": name_map.get(tk, tk),
        "代码": tk,
        "档位": grade_map.get(tk, ""),
        "🥇 累计金牌(月)": gold,
        "🥈 累计银牌(月)": silver,
        "最长连续金": streak,
        "最近戴金月": gdates.max().strftime("%Y-%m") if len(gdates) else "—",
    })
_medal_df = pd.DataFrame(_medal_rows)
st.markdown("#### 🏅 奖牌榜(按累计金牌 → 银牌排序)")
st.dataframe(_medal_df, use_container_width=True, hide_index=True)

# ── Top2 持仓净值 ──
st.markdown("---")
st.markdown("### 📈 持有金 + 银两仓(等权)· 净值 vs SPY")
st.caption(
    "每月末按 king_score 选 Top2,顺延 1 月执行(去 look-ahead) · **守擂缓冲**:在任票掉到第 N 名以内不换,"
    "掉出才替换 · 日 1 开盘买入、等权、周线 NAV、yfinance 股息+拆股复权 · "
    "⚠️ 日线价格 yfinance 最长约 5 年,10Y 跨度的净值起点仍约 5 年前。"
)
_buf = int(st.number_input("守擂缓冲区 Top-N(≥2,越大越不换仓)", min_value=2, max_value=10, value=4, step=1, key="bb_buf"))

with st.spinner("加载个股日线、重建净值..."):
    _pool = list(_tickers.keys())
    _pc_daily = {}
    for tk in _pool:
        d = hv.fetch_daily_ohlcv(tk)
        if d is not None and not d.empty:
            _pc_daily[tk] = d
    _spy_daily = hv.fetch_daily_ohlcv("SPY")

# 月末决策篮子:king_score 降序 → build_basket_nav 内部按 top_n/buffer 取仓
_history = {}
for _ts, _row in king_m.iterrows():
    _r = _row.dropna().sort_values(ascending=False)
    if _r.empty:
        continue
    _history[_ts.strftime("%Y-%m")] = {
        "buyback": {"tickers": [{"ticker": tk} for tk in _r.index], "gate_status": "open", "gate_reason": ""}
    }

if not _history or _spy_daily is None or _spy_daily.empty or not _pc_daily:
    st.info("价格数据不足,无法重建净值。")
else:
    _res = hv.build_basket_nav(
        _history, "buyback", _pc_daily, _spy_daily,
        top_n=2, buffer_n=_buf, shift_months=1,
    )
    _nav = _res.get("nav", pd.Series(dtype=float))
    if _nav is None or _nav.empty:
        st.info("价格窗口内无足够数据生成净值曲线。")
    else:
        _spy_wk = hv.daily_to_weekly(_spy_daily)
        _kpi = hv.compute_nav_kpi(_nav)

        def _fmt(v, f=".2f"):
            try:
                if isinstance(v, float) and (v != v or abs(v) == float("inf")):
                    return "—"
                return f"{v:{f}}"
            except (TypeError, ValueError):
                return "—"

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("总收益", f"{_res.get('total_ret', 0):+.1f}%")
        c2.metric("最大回撤", f"-{_res.get('max_dd', 0):.1f}%")
        c3.metric("Calmar", _fmt(_kpi.get("calmar", float("nan"))))
        c4.metric("Sortino", _fmt(_kpi.get("sortino", float("nan"))))
        c5.metric("年换手", f"{_res.get('turnover_pct', 0):.0f}%")

        st.plotly_chart(
            hv.build_basket_fig(_nav, _spy_wk, "回购股 Top2 等权 vs SPY"),
            use_container_width=True, key="bb_nav",
        )

        # 每月实际持仓(执行月)
        _mh = _res.get("monthly_holdings", {}) or {}
        _pick_rows = []
        for _em in sorted(_mh):
            _held = [t for t in _mh[_em] if t]
            _pick_rows.append({
                "执行月(实际持有)": _em,
                "仓位1": f"{name_map.get(_held[0], _held[0])} ({_held[0]})" if len(_held) > 0 else "—",
                "仓位2": f"{name_map.get(_held[1], _held[1])} ({_held[1]})" if len(_held) > 1 else "—",
            })
        if _pick_rows:
            st.markdown("**每月实际持仓**(对照上方接力图核对)")
            st.dataframe(pd.DataFrame(_pick_rows).iloc[::-1], use_container_width=True, hide_index=True)
