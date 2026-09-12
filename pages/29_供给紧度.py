import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_client import (
    clear_tightness_caches,
    fetch_enso,
    fetch_tightness_alerts,
    fetch_tightness_carriers,
    fetch_tightness_events,
    fetch_tightness_hitrate,
    fetch_tightness_history,
    fetch_tightness_latest,
)

st.set_page_config(page_title="供给紧度", layout="wide", page_icon="🛢️")
st.title("🛢️ 供给紧度")
st.caption(
    "供给两三年内改不了的品类，遇上一周内能改变需求的事件，才出非线性行情。"
    "这页回答「现在这个品类的垫子有多厚」。"
    "**判读以期限结构为主、价格分位为辅**：分位高只说明贵，近月对远月倒挂才说明缺。"
    "品类清单、卡在哪、响应时间在 obsidian 的《供给刚性清单》里，这页只管每天变的读数。"
    "报警胜率是全历史回放算的，期限结构类报警（翻转倒挂等三种）算不了——已到期合约拉不到，没有胜率列。"
)

# 倒挂超过这个数算现货紧张，与 system/scripts/tightness_scan.py 同口径
TIGHT_PREM = 0.05
TIGHT_Q = 0.85
# 跟自己的历史比：当前溢价站上自身 80 分位算「比平时紧」，跌破 20 分位算「比平时松」
SELF_TIGHT, SELF_LOOSE = 0.80, 0.20
# 天然气有强季节性（冬季合约天然贵过夏季），近月溢价要跟往年同月比才有意义
SEASONAL = {"美国天然气"}
# 时间序列和报警流水都是一次拉全量再本地切，够大就行
_MAX_DAYS = 100000

with st.sidebar:
    if st.button("🔄 强制刷新紧度数据"):
        clear_tightness_caches()
        st.rerun()

latest = fetch_tightness_latest()
if not latest.get("success"):
    st.error(f"⚠️ 紧度数据暂不可用：{latest.get('error', '未知错误')}")
    st.stop()

rows = latest.get("data") or []
# 每个品类 prem 的自身中位 / p20 / p80 / 当前分位，后端按历史快照算
baselines = latest.get("baselines") or {}
if not rows:
    st.warning("⚠️ 还没有任何快照。先跑 `system/scripts/tightness_scan.py`。")
    st.stop()

df = pd.DataFrame(rows)
st.caption(f"数据日期 **{latest.get('snap_date')}**，{len(df)} 个品类。每天 7:40 由 `tightness_scan.py` 写入。")

carriers_resp = fetch_tightness_carriers()
rigid = carriers_resp.get("data") or {}
kinds = carriers_resp.get("kinds") or {}
markets = carriers_resp.get("markets") or {}
gaps = carriers_resp.get("gaps") or {}
drivers = gaps.get("drivers") or []
active_drivers = [d for d in drivers if d.get("active")]
enso_latest = fetch_enso().get("latest") or {}
# (品类, 报警类型) -> 历史胜率行，system/scripts/alert_hitrate.py 离线回放全历史算的
HITRATE_MIN_N = 5
hitrate_map = {(r["category"], r["kind"]): r for r in fetch_tightness_hitrate().get("data") or []}
# 紧度表的「品类」列有两种来源：有期货的走 tight_cats 反查（如「小麦」→ key「谷物」），
# 没期货的代理行「品类」本身就是 RIGID 的 key（如「VLCC 原油油轮运费」）
cat_to_key: dict[str, str] = {}
carrier_map: dict[str, list[str]] = {}
for _key, _info in rigid.items():
    _tcs = _info.get("tight_cats") or []
    if _tcs:
        for _tc in _tcs:
            cat_to_key[_tc] = _key
            carrier_map[_tc] = _info.get("carriers") or []
    else:
        cat_to_key[_key] = _key
        carrier_map[_key] = _info.get("carriers") or []


def _detour(cat: str, field: str = "detour") -> str:
    return (rigid.get(cat_to_key.get(cat, "")) or {}).get(field) or ""


def _active_driver_cell(cat: str) -> str:
    """这个品类当前有没有间歇性驱动在发作（如厄尔尼诺）。区别于绕不绕得掉——
    驱动是外部条件在打，不是这个品类自己的供给结构变了。"""
    key = cat_to_key.get(cat, cat)
    names = [d["driver"] for d in active_drivers if key in (d.get("hits") or [])]
    return " · ".join(names) if names else "—"


def _hitrate_cell(cat: str, kind: str) -> str:
    """这类报警历史上准不准：命中率（样本数，中位收益，闭眼买对照）。样本 < 5 条不给数。"""
    r = hitrate_map.get((cat, kind))
    if not r or r["n"] < HITRATE_MIN_N or r.get("win_t120") is None:
        return "样本不足"
    prefix = "⚠️ " if r["win_t120"] < 0.5 else ""
    return (f"{prefix}{r['win_t120']:.0%}（{r['n']} 条，"
            f"中位 {r['med_t120']:+.1%}，闭眼买 {r['base_t120']:+.1%}）")


def _metric_row(sub: pd.DataFrame) -> None:
    for chunk in [sub.iloc[i:i + 6] for i in range(0, len(sub), 6)]:
        for col, (_, r) in zip(st.columns(len(chunk)), chunk.iterrows()):
            delta = None if pd.isna(r["prem_prev"]) else f"{(r['prem'] - r['prem_prev']) * 100:+.1f}pp"
            name = r["category"] + ("（季节性）" if r["category"] in SEASONAL else "")
            why = _detour(r["category"], "detour_why")
            col.metric(name, f"{r['prem']:+.1%}", delta,
                       help=(why + "\n\n" if why else "") + "括号里是相对一个月前的变化")


# ── 1. 当前处在倒挂的品类 ──
back = df[df["prem"].notna() & (df["prem"] > 0)].sort_values("prem", ascending=False)
st.markdown("## 现在谁在倒挂")
if back.empty:
    st.info("当前没有任何品类处在倒挂，全部 contango。事件打进来也容易被库存吸收掉。")
else:
    st.markdown(
        f"{len(back)} 个品类近月贵过远月——市场在为「立刻拿到货」付溢价。"
        f"溢价 > {TIGHT_PREM:.0%} 算现货紧张。"
    )
    # 倒挂本身不区分这次是真少了还是只是改道，并排摆着会看成一回事。易绕的品类
    # 就算倒挂通常也是短线：俄乌开战小麦第 11 天、原油第 12 天就见顶
    _tag = back["category"].map(lambda c: _detour(c))
    for _want, _title, _note in [
        ("绕不掉", "绕不掉的在倒挂", "产能真的少了或没有第二家可买，补不上来，倒挂能持续"),
        ("易绕", "易绕的在倒挂", "产能多半没消失只是改道，这种倒挂常常两周就见顶——"
                             "真想买去买承担绕路成本的那一环"),
    ]:
        _sub = back[_tag == _want]
        if not _sub.empty:
            st.markdown(f"**{_title}** —— {_note}")
            _metric_row(_sub)
    _rest = back[~_tag.isin(["绕不掉", "易绕"])]
    if not _rest.empty:
        st.markdown("**其余在倒挂** —— 绕不绕得掉要看这次事件具体怎么走，得自己判一次")
        _metric_row(_rest)

# ── 2. 主表 ──
st.markdown("## 紧度读数")
tbl = df.copy()
tbl["_sort"] = tbl["prem"].fillna(-9)
tbl = tbl.sort_values(["_sort", "q5"], ascending=False)
def _carrier_cell(cat: str) -> str:
    tickers = carrier_map.get(cat) or []
    cell = " · ".join(tickers[:3])
    return cell + "…" if len(tickers) > 3 else cell


def _prem_cell(row) -> str:
    if pd.isna(row["prem"]):
        return "无期货" if row.get("source") == "proxy" else "—"
    return f"{row['prem']:+.1%}"


def _self_cell(cat: str) -> str:
    """跟自己的历史比紧不紧。绝对溢价只说明是油品还是金属，说明不了现在紧不紧。"""
    b = baselines.get(cat)
    if not b:
        return "样本不足"
    q = b["self_q"]
    tag = "比平时紧" if q >= SELF_TIGHT else "比平时松" if q <= SELF_LOOSE else "接近常态"
    return f"{tag}（{q:.0%}）"


show = pd.DataFrame({
    "品类": tbl["category"],
    "最新": tbl["price"].map(lambda v: f"{v:,.2f}" if pd.notna(v) else "—"),
    "近月溢价": tbl.apply(_prem_cell, axis=1),
    "比自己": tbl["category"].map(_self_cell),
    "一月前溢价": tbl["prem_prev"].map(lambda v: "—" if pd.isna(v) else f"{v:+.1%}"),
    "5 年分位": tbl["q5"].map(lambda v: "—" if pd.isna(v) else f"{v:.0%}"),
    "一月前分位": tbl["q5_prev"].map(lambda v: "—" if pd.isna(v) else f"{v:.0%}"),
    "近一月": tbl["r1m"].map(lambda v: "—" if pd.isna(v) else f"{v:+.0%}"),
    "近一年": tbl["r1y"].map(lambda v: "—" if pd.isna(v) else f"{v:+.0%}"),
    "绕不绕得掉": tbl["category"].map(lambda c: _detour(c) or "未登记"),
    "在发作的驱动": tbl["category"].map(_active_driver_cell),
    "判读": tbl["verdict"],
    "载体": tbl["category"].map(_carrier_cell),
})
st.dataframe(show, hide_index=True, use_container_width=True)
st.caption(
    f"**「近月溢价」和「比自己」看的是两件事**：绝对溢价高低主要由品种决定——油品天然 backwardation、"
    f"金属天然 contango，所以汽油常年在 {TIGHT_PREM:.0%} 以上、黄金从没到过，"
    "这个高低本身说明不了现在缺不缺。「比自己」拿当前溢价在这个品类自己历史里的分位说话，"
    f"站上 {SELF_TIGHT:.0%} 叫比平时紧，跌破 {SELF_LOOSE:.0%} 叫比平时松。"
)
st.caption(
    "**「绕不绕得掉」回答的是这次到底少没少**：制裁、禁运、出口配额断的是「谁在卖」，产能还在，"
    "换个买家就行，标易绕；矿关了、树病死了、厂永久关停，或者压根没有第二家能供，标绕不掉。"
    "标签只覆盖「是不是真少了」「有没有替代」这两问——**「绕路成本落在谁头上」每次事件都不一样，"
    "这里不给答案**，得对着当次事件自己判一次。判据全文在 obsidian 的《供给刚性清单》第三节。"
)
st.caption(
    "天然气的期限结构不可信——冬季合约天然贵过夏季，它的近月溢价要跟往年同月比才有意义，"
    "不能直接当宽松读。原油和金属没有这个问题。"
    "运费、铀、稀土没有期货合约，这里显示的是主载体的代理读数，不是现货紧度。"
)

# ── 3. 时间序列：md 看不到的那部分 ──
st.markdown("## 变紧的过程")
st.markdown(
    "笔记里只有今天这一行读数，看不出是在变紧还是变松。"
    "**对常年在零线一侧的品类（油品一直倒挂、金属一直 contango），看的是有没有站上自己的 80 分位线**；"
    "对会来回穿越的品类，穿越零线是最强的信号——从 contango 翻成倒挂，说明市场从「愿意囤」变成「等不及」。"
)
cats = latest.get("categories") or sorted(df["category"].tolist())
_default = back["category"].iloc[0] if not back.empty else cats[0]
c1, c2 = st.columns([3, 1])
cat = c1.selectbox("品类", cats, index=cats.index(_default) if _default in cats else 0)

# 一次拉全量再本地切片：快照回填只有半年，选 250 / 500 会和 125 拿到完全一样的
# 数据，看着像回看没生效。档位按这个品类实际有多少天裁，超出的不给选
hist = fetch_tightness_history(cat, _MAX_DAYS)
h_all = pd.DataFrame(hist.get("data") or [])
if h_all.empty:
    c2.selectbox("回看", ["—"], disabled=True)
    st.warning(f"⚠️ {cat} 还没有历史快照")
else:
    n = len(h_all)
    opts = [d for d in (60, 125, 250) if d < n] + [n]
    days = c2.selectbox(
        "回看", opts, index=len(opts) - 1,
        format_func=lambda d: f"全部 {d} 个交易日" if d == n else f"{d} 个交易日",
    )
    h = h_all.tail(days).copy()
    h["snap_date"] = pd.to_datetime(h["snap_date"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=h["snap_date"], y=h["prem"] * 100, name="近月溢价 %",
        line=dict(color="#FFD700", width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>近月溢价 %{y:.1f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=h["snap_date"], y=h["q5"] * 100, name="5 年价格分位 %", yaxis="y2",
        line=dict(color="#4C9BE8", width=2, dash="dot"),
        hovertemplate="%{x|%Y-%m-%d}<br>分位 %{y:.0f}%<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color="#888", width=1))
    # 固定 5% 线对油品永远在下方、对金属永远在上方，看不出变化。画这个品类自己的
    # 中位和 80 分位，才看得出「现在是不是比自己平时紧」
    _b = baselines.get(cat)
    if _b:
        fig.add_hline(y=_b["median"] * 100, line=dict(color="#888", width=1, dash="dot"),
                      annotation_text=f"自身中位 {_b['median']:+.1%}", annotation_position="bottom left")
        fig.add_hline(y=_b["p80"] * 100, line=dict(color="#E74C3C", width=1, dash="dash"),
                      annotation_text=f"自身 {SELF_TIGHT:.0%} 分位 {_b['p80']:+.1%}",
                      annotation_position="top left")
    else:
        fig.add_hline(y=TIGHT_PREM * 100, line=dict(color="#E74C3C", width=1, dash="dash"),
                      annotation_text=f"现货紧张线 {TIGHT_PREM:.0%}", annotation_position="top left")
    fig.update_layout(
        height=440, hovermode="x unified", template="plotly_dark",
        margin=dict(l=10, r=10, t=30, b=10),
        yaxis=dict(title="近月溢价 %（正 = 倒挂 = 缺货）", zeroline=False),
        yaxis2=dict(title="5 年价格分位 %", overlaying="y", side="right",
                    range=[0, 100], showgrid=False),
        legend=dict(orientation="h", y=1.12, x=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    last, first = h.iloc[-1], h.iloc[0]
    bits = []
    if pd.notna(last["prem"]) and pd.notna(first["prem"]):
        bits.append(f"近月溢价从 {first['prem']:+.1%} 走到 {last['prem']:+.1%}")
    if pd.notna(last["q5"]) and pd.notna(first["q5"]):
        bits.append(f"5 年分位从 {first['q5']:.0%} 到 {last['q5']:.0%}")
    if pd.notna(last["far_code"]):
        bits.append(f"当前远月合约 `{last['far_code']}`")
    if bits:
        st.caption(f"{first['snap_date']:%Y-%m-%d} 至 {last['snap_date']:%Y-%m-%d}：" + "；".join(bits) + "。")
    st.caption(
        f"快照从 {pd.to_datetime(h_all['snap_date'].iloc[0]):%Y-%m-%d} 起记，"
        f"{cat} 共 {n} 个交易日，再往前没有数据。"
    )
    if cat in SEASONAL:
        st.warning("天然气的近月溢价带强季节性，横向比零线意义有限，要跟往年同月比。")

# ── 4. 这个品类能买什么 ──
st.markdown("## 这个品类能买什么")
rigid_key = cat_to_key.get(cat)
info = rigid.get(rigid_key) or {}
if not info:
    st.info(f"{cat} 还没有登记到载体清单里。")
else:
    st.markdown(
        f"**商品** {info.get('commodity', '—')} ｜ **环节** {info.get('stage') or '非实物'} ｜ "
        f"**响应时间** {info.get('respond', '—')} ｜ **绕不绕得掉** {info.get('detour', '—')}"
    )
    st.caption(f"卡在哪：{info.get('stuck', '—')}")
    if info.get("detour_why"):
        st.caption(f"为什么这么判：{info['detour_why']}")
    if info.get("indicator"):
        st.caption(f"真紧度指标：{info['indicator']}")
    cat_row = tbl[tbl["category"] == cat]
    if not cat_row.empty and cat_row.iloc[0].get("source") == "proxy":
        st.warning(cat_row.iloc[0]["verdict"])
    carrier_rows = []
    for t in info.get("carriers") or []:
        m = markets.get(t, "美国")
        carrier_rows.append({
            "载体": t,
            "市场": m if m == "美国" else f"🌐 {m}",
            "类型": kinds.get(t, "股票/股票ETF"),
        })
    st.dataframe(pd.DataFrame(carrier_rows), hide_index=True, use_container_width=True)

# ── 5. 历史上这个品类遇到过什么 ──
st.markdown("## 历史上这个品类遇到过什么")
ev = fetch_tightness_events(rigid_key) if rigid_key else {"events": [], "perf": []}
events = ev.get("events") or []
perf = pd.DataFrame(ev.get("perf") or [])
if not events:
    st.info("这个品类还没有回测过的事件")
else:
    for e in events:
        e_perf = perf[perf["event_id"] == e["event_id"]] if not perf.empty else perf
        st.markdown(f"### {e['name']}（{e['event_date']}）— 卡的是「{e['stage_hit']}」")
        st.caption(e.get("stage_note", ""))
        if not e_perf.empty:
            baseline = e_perf["ex_t60"].mean()
            st.markdown(f"这次全买等权 T+60 超额 **{baseline:+.1%}**")
            detail = e_perf.sort_values("ex_t60", ascending=False)
            st.dataframe(
                pd.DataFrame({
                    "载体": detail["ticker"],
                    "类型": detail["kind"],
                    "T+60 超额": detail["ex_t60"].map(lambda v: "—" if pd.isna(v) else f"{v:+.1%}"),
                    "T+120 超额": detail["ex_t120"].map(lambda v: "—" if pd.isna(v) else f"{v:+.1%}"),
                }),
                hide_index=True, use_container_width=True,
            )

# ── 6. 报警流水 ──
st.markdown("## 报警流水")
st.markdown("报警建在紧度变化上，不是建在价格涨跌上——价格异动是结果，紧度异动才是提前量。同一品类同一类型 30 天内只报一次。")
al = fetch_tightness_alerts(_MAX_DAYS)
arows = al.get("data") or []
# 报警只从建表那天起有，选 365 和选 180 拿到的是同一批，档位按实际跨度裁
_span = (pd.Timestamp.today().normalize() - pd.to_datetime(arows[-1]["alert_date"])).days if arows else 0
_aopts = [d for d in (30, 90, 180) if d < _span] + [_span or 30]
adays = st.selectbox("回看天数", _aopts, index=min(1, len(_aopts) - 1), key="alert_days",
                     format_func=lambda d: f"全部 {d} 天" if d == _span else f"{d} 天")
arows = [a for a in arows
         if a["alert_date"] >= (pd.Timestamp.today().normalize() - pd.Timedelta(days=adays)).strftime("%Y-%m-%d")]
if not arows:
    st.info(f"最近 {adays} 天没有紧度异动。")
else:
    adf = pd.DataFrame(arows)
    st.dataframe(
        pd.DataFrame({
            "日期": adf["alert_date"], "品类": adf["category"],
            "类型": adf["kind"], "说明": adf["text"],
            "这类历史准不准": adf.apply(lambda r: _hitrate_cell(r["category"], r["kind"]), axis=1),
        }),
        hide_index=True, use_container_width=True, height=min(520, 40 + 36 * len(adf)),
    )
    st.caption("标了「回填」的是建表时用同一套规则从历史价格重算出来的，当时并没有真的推过 Discord。")
    st.caption(
        "「这类历史准不准」是全历史回放算的：命中 = T+120 绝对收益 > 0，"
        "「闭眼买」对照组是同品类任意一天买入持有 120 天的收益中位数。"
        "样本不足 5 条不给数，期限结构类报警（翻转倒挂等）算不了胜率。"
    )

# ── 7. 清单自己的洞 ──
st.markdown("## 清单自己的洞")
st.caption("漏一格会在这里显示成一行空白，而不是等到有东西涨了 47 倍才发现。")

st.markdown("**商品缺哪些环节**")
st.caption(
    "环节按商品类型定制，不是所有商品都套六环——农产品只有采和加工，海运只有运和设备，"
    "黄金只有采。所以这里列出来的空格都是真缺，不会再出现「可可缺设备」这种可可根本没有的环节。"
)
missing = gaps.get("missing_stages") or []
if missing:
    st.dataframe(
        pd.DataFrame({
            "商品": [m["commodity"] for m in missing],
            "这个商品有哪几环": [" · ".join(m.get("applies") or []) for m in missing],
            "已有环节": [" · ".join(m["has"]) for m in missing],
            "缺的环节": [" · ".join(m["missing"]) for m in missing],
        }),
        hide_index=True, use_container_width=True,
    )
else:
    st.info("每个商品适用的环节都有品类覆盖。")

st.markdown("**现在有哪些驱动在发作**")
st.caption(
    "间歇性驱动和上面的共用瓶颈不是一回事：船台常年卡着，厄尔尼诺只在外部条件成立时才发作。"
)
if not drivers:
    st.info("暂无登记的间歇性驱动。")
else:
    for d in drivers:
        roni, oni = d.get("roni"), enso_latest.get("oni")
        hits = d.get("hits") or []
        if d.get("active"):
            st.warning(
                f"**{d['driver']}正在发作** —— RONI {roni:+.2f}"
                + (f"（ONI {oni:+.2f}）" if oni is not None else "")
                + f"，{d.get('band', '—')}{d.get('phase', '')}相位，"
                f"同时打中 {len(hits)} 个品类：{' · '.join(hits)}。"
                "**厄尔尼诺不是做多信号**，主理人实测 T+12 月糖价中位 −4%，"
                "它只说明这几个品类进入了高波动窗口，而且这不是几注，是同一注下几遍。"
            )
        else:
            st.caption(f"{d['driver']}未发作（当前 RONI {roni:+.2f}）。")

st.markdown("**共用瓶颈：哪几个品类其实是同一注**")
st.caption(
    "同一个根因卡着多个品类时，分别买这几个品类不是分散几注，是同一注下几遍。"
    "商品维度会把它们拆开——船台卡着的四个品类分属原油、成品油、干散货、天然气，看着像四注。"
)
shared = gaps.get("shared_bottlenecks") or []
if shared:
    for s in [x for x in shared if len(x["categories"]) > 1]:
        tail = (f"瓶颈本身的载体是 {' · '.join(s['carriers'][:4])}（`{s['own_category']}`）"
                if s.get("carriers") else "瓶颈本身还没有独立品类，只能通过这几个品类间接下注")
        st.warning(
            f"**{s['entity']}** 卡着 {len(s['categories'])} 个品类："
            f"{' · '.join(s['categories'])}——分属 {len(s['commodities'])} 个商品"
            f"（{' · '.join(s['commodities'])}）。这不是 {len(s['categories'])} 注，"
            f"是同一注下 {len(s['categories'])} 遍。{tail}"
        )
    st.dataframe(
        pd.DataFrame({
            "瓶颈": [s["entity"] for s in shared],
            "卡着的品类": [" · ".join(s["categories"]) for s in shared],
            "跨几个品类": [len(s["categories"]) for s in shared],
            "分属商品": [" · ".join(s["commodities"]) for s in shared],
            "是不是同一注": ["是" if len(s["categories"]) > 1 else "只卡 1 个，不算"
                        for s in shared],
            "瓶颈自己的品类": [s.get("own_category") or "—" for s in shared],
        }),
        hide_index=True, use_container_width=True,
    )
else:
    st.info("没有任何根因同时卡着多个品类。")

st.markdown("**根因写下来了但不是品类**")
orphans = gaps.get("orphan_entities") or []
if orphans:
    st.dataframe(
        pd.DataFrame({
            "根因实体": [o["entity"] for o in orphans],
            "它导致了哪些品类": [" · ".join(o["caused"]) for o in orphans],
        }),
        hide_index=True, use_container_width=True,
    )
else:
    st.info("笔记里提到的根因实体都已经单独成为品类。")

st.markdown("**只能买股票 / 买不到的品类**")
no_shelter = gaps.get("no_shelter") or []
absent = gaps.get("absent_commodities") or []
gap_rows = [
    {"品类/商品": n["category"], "情况": "只能买股票（无期货/无实物信托）",
     "说明": " · ".join(n.get("markets") or [])}
    for n in no_shelter
] + [
    {"品类/商品": a["commodity"], "情况": "买不到（无品类）", "说明": a["why"]}
    for a in absent
]
if gap_rows:
    st.dataframe(pd.DataFrame(gap_rows), hide_index=True, use_container_width=True)
else:
    st.info("没有品类处在「只能买股票」或「买不到」状态。")
