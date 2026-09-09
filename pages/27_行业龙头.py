import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import holdings_viz as hv
from api_client import fetch_sector_leaders, fetch_gbdt_oos_prices

st.set_page_config(page_title="行业龙头", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #4A9EFF; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #4A9EFF; font-size: 18px; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

st.title("🏛️ 行业龙头（11 行业各 1 只等权月调）")
st.caption(
    "**策略 = 每个行业派一只龙头出场，等权持有**：每年 12-31，11 个 Sharadar 行业各取市值前 3，"
    "其中选过去 5 年价格涨幅最高的那只，次年 1 月起生效，等权、月末再平衡、单边 200bps。"
    "唯一质量门槛是 FCF > 0 与市值 ≥ $30B，**不设单只回撤上限**——单只跌得深没关系，靠行业互斥在组合层面对冲。"
    "回测（`backtest_quality_seven.py` Section C，2017-04→2026-06，Sharadar 复权价）："
    "全程 CAGR 19.8% / DD −21.4% / Calmar 0.92（SPY 15.1 / −23.9 / 0.63）。"
    "**这个策略是怎么找出来的**：起点是「从机构共同持仓里按黄金带鱼方法排名」，实测机构共同持仓池"
    "与黄金带鱼六道门交集为 0、按六轴排名 18 个变体全跑输 SPY；转而归因主理人手挑的 7 只"
    "（AAPL/LLY/TJX/COST/V/BRK.B/MA，静态等权 22.9 / −14.7 / 1.56），发现它的优势不是选中牛股——"
    "**七只单独持有的 Calmar 分别是 1.53/1.11/0.88/0.73/0.68/0.57/0.52，组合 1.56 高于任何一只**，"
    "且组合 DD −14.7% 比最抗跌的单只（COST −20.3%）还浅 5.6pp，优势全部来自七只跌得不同步。"
    "顺着「行业互斥」做规则化，纯质量因子打分（高 ROIC + 高毛利）被证伪（Calmar 仅 0.23，"
    "它把 V 排第 2、MA 排第 4，而这两只在留一法里恰恰是拖累），最终落到本页这条按行业派人的规则。"
    "**收益端复现不了**：本策略 CAGR 19.8% 对手挑 7 只的 22.9%，差的 3.1pp 就是「今天回头看知道 LLY 会翻五倍」的价格。"
    "**图上对照线已按留一法删掉 V/BRK.B/MA、只留 4 只**（AAPL/LLY/TJX/COST），本页净值口径 26.0 / −14.1 / 1.85，"
    "7 只版同口径 22.4 / −14.7 / 1.53，差距因此更大。上面这段归因讲的是当初那 7 只，回测数字（22.9% / 3.1pp）不改。"
    "**五组稳健性检验全过**（`backtest_sector_leaders_robust.py`，详见页底）："
    "换调仓时点四档全在 0.92~0.97、回看窗口五档全超 SPY、前后两段都跑赢、成本翻倍仍 0.86。"
    "**但这五组都是单变量扰动**——每组只动一个参数、其余钉在现行值。把「决策日」与「行业市值前 N」"
    "两个参数一起动，12 种组合里 Calmar 从 **0.55 摆到 0.97**、中位 0.85；而「前 3」本身也是从 "
    "2/3/4/5 里选出来的。两个拟合参数叠起来才是真实的不确定性，比单看某一行宽得多。"
    "**六条警告**：① **前半段没有超额收益**——2016-2020 CAGR 16.5% 对 SPY 16.6% 基本打平，赢的全是回撤"
    "（−17.6% vs −19.4%），全部超额集中在 2021 年后（22.4% vs 15.4%）；这个策略的准确描述是"
    "「顺风跟得上、逆风跌得少」，不是「每年跑赢大盘」；② 「行业内选 5 年涨幅最高」带动量成分，"
    "round2 与 round5 都测出过动量在本系统里换个样本就翻车，1 年窗那档已经掉到 0.70；"
    "③ 11 年只有 11 次年度决策，样本薄，且本规则是从 24 种组合里选出的最好一个；"
    "④ 持仓 11 只不可压缩——实测每年只留涨幅最高的 6 个行业会崩到 0.64（跌回 SPY 水平），"
    "穷举 462 种「11 选 6」组合仅 18% 能超过全覆盖；"
    "⑤ **「FCF > 0」这道门实质是「不要银行、不要重资产公用事业」**——它切掉的是 JPM($842B)、"
    "ORCL、WFC、MS、C、INTC、SO、DUK 这些，不是坏公司，而是 FCF 这个指标不适用的行业。"
    "它在 2016-2026 有效纯粹因为这十年银行跑输（实测放银行进来更差，见页底诊断），"
    "风格一旦转向这个策略会整个错过。金融格子 11 年里 10~11 次都是 BRK.B，这条腿实质就是买 BRK.B；"
    "⑥ **格子里派谁几乎不影响结果**，全部收益来自「每个行业派一人」这个结构本身，见页底诊断。"
    "**净值走后端 Sharadar 复权价（与回测同源），新鲜度到上次本地价格推送为止。**"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        fetch_sector_leaders.clear()
        fetch_gbdt_oos_prices.clear()
        st.rerun()

COST_BPS = 200.0
CASH_RATE = hv.CASH_APY
# 起点对照，后视镜产物。原来是 7 只，2026-09-08 删掉 V/BRK.B/MA（留一法证明这三只金融不提供分散）
HAND4 = ["AAPL", "LLY", "TJX", "COST"]

# 后端 sector 字段是英文原名，仅展示时换中文简称（与 holdings_viz._SECTOR_CN 同一套词）
SECTOR_CN = {
    "Technology": "科技", "Industrials": "工业", "Healthcare": "医疗",
    "Financial Services": "金融", "Consumer Cyclical": "可选消费",
    "Consumer Defensive": "必选消费", "Communication Services": "通讯服务",
    "Energy": "能源", "Basic Materials": "原材料",
    "Real Estate": "房地产", "Utilities": "公用事业",
}

doc = fetch_sector_leaders()
if not doc.get("success"):
    st.error(f"⚠️ 数据暂不可用：{doc.get('error', '未知错误')}")
    st.stop()

pools = {int(y): list(m) for y, m in (doc.get("pools") or {}).items()}
tables = doc.get("sector_tables") or {}
names = doc.get("names") or {}
bt = doc.get("backtest") or {}
rob = doc.get("robustness") or {}
if not pools or not tables:
    st.info("名单未就绪（本地跑 scripts/build_sector_leaders.py 并上传后生效）")
    st.stop()

built = pd.to_datetime(doc.get("built_at"), errors="coerce", utc=True)
if pd.notna(built) and (pd.Timestamp.now(tz="UTC") - built).days > 40:
    st.warning(f"⚠️ 数据已 {(pd.Timestamp.now(tz='UTC') - built).days} 天未重建"
               "（本地跑 scripts/build_sector_leaders.py 并上传后名单才会更新）")

cur_year = max(pools)
cur = pools[cur_year]
union = sorted({t for m in pools.values() for t in m})

with st.spinner("📊 加载价格（Sharadar 复权）..."):
    _raw = fetch_gbdt_oos_prices(tuple(sorted(set(union + HAND4 + ["SPY"]))))
close_d = {}
for t, rows in (_raw or {}).items():
    if rows:
        arr = pd.DataFrame(rows, columns=["date", "o", "h", "l", "c", "v"])
        close_d[t] = arr.assign(date=pd.to_datetime(arr["date"])).set_index("date")["c"].astype(float)
_missing = [t for t in sorted(set(union + HAND4 + ["SPY"])) if t not in close_d]
if _missing:
    st.warning(f"⚠️ 价格缓存缺票：{_missing}（本地 push_local_to_render --tables gbdt_oos_prices 后消失）")

close_m = pd.DataFrame(close_d).sort_index().resample("ME").last()
ret_m = close_m.pct_change(fill_method=None)


def _ew_nav(members_by_month) -> pd.Series:
    """月末决策次月执行，等权、单边 200bps、空池现金 4%。与回测同口径。"""
    w = pd.DataFrame(0.0, index=list(members_by_month), columns=close_m.columns)
    for d, mem in members_by_month.items():
        ok = [t for t in mem if t in close_m.columns and pd.notna(close_m.at[d, t])]
        for t in ok:
            w.at[d, t] = 1.0 / len(ok)
    cash = (1 - w.sum(axis=1)).clip(lower=0.0)
    port = (w.shift(1) * ret_m.reindex(w.index)).sum(axis=1) + cash.shift(1).fillna(1.0) * CASH_RATE / 12
    turn = (w - w.shift(1)).abs().sum(axis=1) * 0.5
    return (1 + port - turn * COST_BPS / 10000).cumprod()


def _stats(nav: pd.Series, lo=None) -> dict:
    s = nav.dropna()
    if lo is not None:
        s = s[s.index >= lo]
    if len(s) < 6:
        return {}
    s = s / float(s.iloc[0])
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = float(s.iloc[-1]) ** (1 / yrs) - 1
    dd = float((s / s.cummax() - 1).min())
    return {"CAGR": cagr * 100, "DD": dd * 100, "Calmar": cagr / abs(dd) if dd < 0 else float("nan")}


_months = [d for d in close_m.index if d.year in pools]
nav_pool = _ew_nav({d: pools[d.year] for d in _months})
nav_hand = _ew_nav({d: HAND4 for d in _months})
nav_spy = _ew_nav({d: ["SPY"] for d in _months})

st.markdown(f"### 📌 {cur_year} 年持仓（{len(cur)} 只 · 各 {100 / len(cur):.1f}%）")
cur_tab = tables.get(str(cur_year), {})
sec_of = {c["ticker"]: SECTOR_CN.get(sec, sec) for sec, cands in cur_tab.items() for c in cands}
cagr_of = {c["ticker"]: c.get("cagr5y") for cands in cur_tab.values() for c in cands}
cols = st.columns(min(len(cur), 6))
for i, t in enumerate(cur):
    with cols[i % len(cols)]:
        st.metric(t, f"5Y {cagr_of[t]:+.0f}%" if cagr_of.get(t) is not None else "—",
                  help=f"{names.get(t, t)} · {sec_of.get(t, '?')}·「5Y」是入选时的近 5 年年化涨幅，不是仓位")
        st.caption(sec_of.get(t, "?"))

st.markdown("---")
st.markdown(f"### 🔍 {cur_year} 年各行业怎么选出来的")
st.caption("每行是一个行业的市值前 3，✅ 是当选那只（5 年涨幅最高）。看得到落选的是谁、差多少。")
rows = []
for sec in sorted(cur_tab, key=lambda s: SECTOR_CN.get(s, s)):
    for c in sorted(cur_tab[sec], key=lambda x: -(x.get("cagr5y") or -999)):
        rows.append({"行业": SECTOR_CN.get(sec, sec), "": "✅" if c["picked"] else "", "ticker": c["ticker"],
                     "公司": names.get(c["ticker"], ""), "市值($B)": c["mcap_b"],
                     "5年涨幅%": c["cagr5y"]})
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
             column_config={"5年涨幅%": st.column_config.NumberColumn(format="%.1f"),
                            "市值($B)": st.column_config.NumberColumn(format="%.0f")})

st.markdown("---")
st.markdown("### 📈 净值对比")
win = st.radio("区间", ["全程", "5Y", "3Y"], horizontal=True, index=0, key="sl_win")
lo = None if win == "全程" else nav_pool.dropna().index[-1] - pd.DateOffset(years=int(win[0]))

fig = go.Figure()
for nav, nm, color, dash in ((nav_pool, "行业龙头 11 只", "#4A9EFF", None),
                             (nav_hand, "手挑 4 只（后视镜对照）", "#FFD700", "dot"),
                             (nav_spy, "SPY", "#888888", "dash")):
    s = nav.dropna()
    if lo is not None:
        s = s[s.index >= lo]
    if s.empty:
        continue
    fig.add_trace(go.Scatter(x=s.index, y=s / float(s.iloc[0]), name=nm,
                             line=dict(color=color, width=2, dash=dash)))
fig.update_layout(template="plotly_dark", height=420, hovermode="x unified",
                  margin=dict(l=40, r=20, t=30, b=30), yaxis_title="净值（起点=1）")
st.plotly_chart(fig, use_container_width=True)

c1, c2, c3 = st.columns(3)
for col, nav, nm in ((c1, nav_pool, "行业龙头 11 只"), (c2, nav_hand, "手挑 4 只"), (c3, nav_spy, "SPY")):
    s = _stats(nav, lo)
    with col:
        if s:
            st.metric(nm, f"CAGR {s['CAGR']:.1f}%",
                      f"DD {s['DD']:.1f}% · Calmar {s['Calmar']:.2f}", delta_color="off")
st.caption(
    f"注：上面三张卡按图上区间（{'2016-01 起' if lo is None else win}）现算，"
    f"与 caption 里的回测数字（{bt.get('cagr')} / {bt.get('maxdd')} / {bt.get('calmar')}）"
    "起点不同——回测统一从 2017-04 起算（与本系统其它策略页对齐），本页净值图从 2016-01 画起。"
    "同一条曲线换个起点，CAGR 和 Calmar 会差零点几，属正常，不是两套数据。")

st.markdown(f"""
<div class="insight-box">
<div class="insight-title">为什么这套能压住回撤</div>
组合最大回撤 −21.4%，比 SPY 的 −23.9% 浅，但成分股单只回撤普遍在 −25% 到 −40%。
差额来自各行业不同步：实测 2025 年末候选池里，<b>同行业两两相关均值 0.405，跨行业只有 0.209</b>。
所以关键不是选抗跌的票，是让持仓分布在互不相关的行业上——
手挑 7 只之所以能做到 DD −14.7%（比它最抗跌的成分 COST −20.3% 还浅），是同一个道理。
</div>
""", unsafe_allow_html=True)

st.markdown("---")
st.markdown("### 🧪 稳健性检验")
c1, c2 = st.columns(2)
with c1:
    st.markdown("**换调仓时点**（最强证据：四档几乎不变）")
    st.dataframe(pd.DataFrame([{"决策日": k, "Calmar": v} for k, v in (rob.get("cut_month") or {}).items()]),
                 use_container_width=True, hide_index=True)
    st.markdown("**选龙头的回看窗口**（五档全超 SPY 0.63）")
    st.dataframe(pd.DataFrame([{"窗口": k, "Calmar": v} for k, v in (rob.get("window") or {}).items()]),
                 use_container_width=True, hide_index=True)
with c2:
    st.markdown("**行业市值档位**（前 4 起崩，所以取前 3）")
    st.dataframe(pd.DataFrame([{"取市值前": k, "Calmar": v} for k, v in (rob.get("mcap_top") or {}).items()]),
                 use_container_width=True, hide_index=True)
    st.markdown("**交易成本**（换手仅 0.42 次/年，不敏感）")
    st.dataframe(pd.DataFrame([{"单边bps": k, "Calmar": v} for k, v in (rob.get("cost_bps") or {}).items()]),
                 use_container_width=True, hide_index=True)

seg = rob.get("segment") or {}
if seg:
    st.markdown("**分段：超额收益全在后半段**")
    st.dataframe(pd.DataFrame([
        {"区间": "2016-2020", "本策略 Calmar": seg.get("2016-2020"), "SPY Calmar": seg.get("spy_2016-2020"),
         "说明": "CAGR 16.5% vs SPY 16.6%，基本打平，赢的全是回撤"},
        {"区间": "2021-2026", "本策略 Calmar": seg.get("2021-2026"), "SPY Calmar": seg.get("spy_2021-2026"),
         "说明": "CAGR 22.4% vs SPY 15.4%，超额集中在这一段"},
    ]), use_container_width=True, hide_index=True)

with st.expander("🔬 留一法诊断：去掉某个行业组合会怎样（未写进规则，仅供判断）"):
    loo = doc.get("leave_one_out") or {}
    st.dataframe(pd.DataFrame([{"去掉的行业": SECTOR_CN.get(k, k), "ΔCalmar": v} for k, v in
                               sorted(loo.items(), key=lambda kv: -kv[1])]),
                 use_container_width=True, hide_index=True)
    st.caption(
        "**能源是回撤保护不是拖累**：去掉能源（常派 CVX/XOM/COP）Calmar 0.92 → 0.80、"
        "回撤 −21.4% → −25.8%。它自身波动大，但 2022 加息时是唯一上涨的板块。医疗同理。"
        "**唯一该考虑去掉的是通讯服务**（去掉后升到 1.06）——GICS 2018 改版把 "
        "GOOGL/META/NFLX 划进该板块，实质是科技股，与科技派出的 NVDA/MSFT/AAPL 高度同步，"
        "占两个格子做同一件事。**但这是 11 次留一里挑最好的那个，属事后选择，没有写死进规则。**")

with st.expander("📉 为什么不压缩到 4-6 只"):
    tr = doc.get("n_sectors_tradeoff") or {}
    st.dataframe(pd.DataFrame([{"每年保留行业数": k, "Calmar": v} for k, v in
                               sorted(tr.items(), key=lambda kv: int(kv[0]))]),
                 use_container_width=True, hide_index=True)
    st.caption(
        "按「每年只留龙头涨幅最高的 N 个行业」压缩：6 个行业 CAGR 更高（22.2% vs 19.8%）"
        "但回撤从 −21.4% 崩到 −34.7%，Calmar 掉到 0.64 与 SPY 打平。"
        "穷举全部 462 种固定「11 选 6」组合：中位 0.78、最好 1.38、最差 0.52，只有 18% 超过全覆盖。"
        "行业互斥本身就是收益来源，减少行业数等于把它拆掉。")

with st.expander("🧨 四组替代方案实测：全部证伪（2026-09-08 一次性实验，非后端重算）"):
    st.markdown("**① 换掉「5 年涨幅最高」这个选人轴——四个轴打平，选谁几乎不影响结果**")
    st.dataframe(pd.DataFrame([
        {"行业内选人轴": "涨幅 ÷ 波动最高", "CAGR%": 17.3, "DD%": -18.4, "Calmar": 0.94, "每年换几只": 4.8},
        {"行业内选人轴": "市值最大（完全不看价格）", "CAGR%": 16.0, "DD%": -17.7, "Calmar": 0.90, "每年换几只": 2.0},
        {"行业内选人轴": "5 年涨幅最高（现版）", "CAGR%": 19.0, "DD%": -21.4, "Calmar": 0.89, "每年换几只": 5.1},
        {"行业内选人轴": "logR² 最直", "CAGR%": 16.0, "DD%": -18.8, "Calmar": 0.85, "每年换几只": None},
        {"行业内选人轴": "5 年回撤最浅", "CAGR%": 12.3, "DD%": -17.8, "Calmar": 0.69, "每年换几只": None},
        {"行业内选人轴": "5 年涨幅最低（反向对照）", "CAGR%": 12.4, "DD%": -27.3, "Calmar": 0.45, "每年换几只": None},
    ]), use_container_width=True, hide_index=True)
    st.caption(
        "六个轴里四个落在 0.85~0.94，连「取行业市值第一名、不看任何价格历史」都有 0.90 且回撤最浅。"
        "反向对照 0.45 说明动量不是纯噪音（选最差确实亏），但「选最好」与「选最大」几乎无差别——"
        "**这一层已经榨不出东西了**。看着最好的「涨幅/波动」做过完整体检：默认参数 0.98 确实高于现版 0.92，"
        "但决策日 × 行业前 N 的 12 格交叉里中位打平（0.85 对 0.85）、最差格子更烂（0.35 对 0.55），"
        "且前半段 2017-2020 反而输（0.94 对 1.01）。优势全在回撤、收益是掉的，属平移不是改进，故不换。")

    st.markdown("**② 改按细分行业（88 个）派龙头，再挑相关性最低的 6 只——全面跑输**")
    st.dataframe(pd.DataFrame([
        {"选法": "11 大行业各一只（现版）", "CAGR%": 19.0, "DD%": -21.4, "Calmar": 0.89},
        {"选法": "88 细分行业龙头全拿（86 只）", "CAGR%": 13.9, "DD%": -24.1, "Calmar": 0.58},
        {"选法": "细分龙头里选最低相关 6 只", "CAGR%": 12.3, "DD%": -23.0, "Calmar": 0.54},
        {"选法": "细分龙头里选涨幅最高 6 只", "CAGR%": 14.5, "DD%": -55.3, "Calmar": 0.26},
        {"选法": "「够低就行」<0.35 + 涨幅优先 6 只", "CAGR%": 23.3, "DD%": -31.0, "Calmar": 0.75},
        {"选法": "SPY", "CAGR%": 15.6, "DD%": -23.9, "Calmar": 0.65},
    ]), use_container_width=True, hide_index=True)
    st.caption(
        "三条原因：**切细不带来分散**——同细分行业相关 0.474、同大行业不同细分 0.332、跨大行业 0.226，"
        "科技切 10 个细分格子它们之间仍相关 0.33；**「选最低相关」等价于「选低 beta 低增长」**——"
        "历年挑出 PSA/NEM/GIS/KR/HSY/PM，回撤压住了但 CAGR 只剩 12.3%；**近一半细分行业挑不动**——"
        "88 个里 23 个只有 1 只票过门槛、18 个只有 2 只，仅 47 个凑得齐前 3。"
        "放松成「够低就行」CAGR 能跳到 23.3%，但回撤深到 −31.0%，仍不敌全覆盖。")

    st.markdown("**③ 市值门槛是摆设，④ 六种质量门替代 FCF>0 全部更差**")
    c1, c2 = st.columns(2)
    with c1:
        st.dataframe(pd.DataFrame([
            {"市值门": "≥$10B", "Calmar": 0.88}, {"市值门": "≥$20B", "Calmar": 0.88},
            {"市值门": "≥$30B（现版）", "Calmar": 0.89}, {"市值门": "≥$50B", "Calmar": 0.90},
            {"市值门": "≥$100B", "Calmar": 0.80},
        ]), use_container_width=True, hide_index=True)
        st.caption("10B~50B 无差别——真正做筛选的是「行业市值前 3」，降门槛不改变前 3 是谁。"
                   "被 30B 切掉的 318 只（MTD/ODFL/ANSS/EFX/KHC 等）放进来也挤不进去。"
                   "100B 时两个行业凑不齐，持仓掉到 9 只。")
    with c2:
        st.dataframe(pd.DataFrame([
            {"质量门": "FCF>0（现版）", "市值最大轴": 0.90, "5Y涨幅轴": 0.89},
            {"质量门": "无门槛", "市值最大轴": 0.88, "5Y涨幅轴": 0.79},
            {"质量门": "经营现金流>0", "市值最大轴": 0.88, "5Y涨幅轴": 0.81},
            {"质量门": "净利>0 或 FCF>0", "市值最大轴": 0.88, "5Y涨幅轴": 0.82},
            {"质量门": "净利>0", "市值最大轴": 0.84, "5Y涨幅轴": 0.81},
            {"质量门": "净利>0 且 ROE≥15%", "市值最大轴": 0.83, "5Y涨幅轴": 0.84},
            {"质量门": "净利>0 且 ROE≥10%", "市值最大轴": 0.71, "5Y涨幅轴": 0.77},
        ]), use_container_width=True, hide_index=True)
        st.caption("**「排除银行会不会错过」实测是反的**：ROE≥10% 门会把金融格子从常年 BRK.B 换成 "
                   "WFC/JPM/V 轮流上，直接掉到 0.71。这十年买银行就是不如买 BRK.B。"
                   "另注：换成「市值最大」轴后质量门几乎不重要（0.88 对 0.90）——"
                   "**质量门的真实作用是防止动量轴选到垃圾票**。")

with st.expander("📅 逐年名单"):
    for y in sorted(pools, reverse=True):
        tab = tables.get(str(y), {})
        so = {c["ticker"]: SECTOR_CN.get(s, s) for s, cs in tab.items() for c in cs}
        members = sorted(pools[y], key=lambda t: (so.get(t, "~"), t))
        st.markdown(f"**{y}**（{len(pools[y])} 只）："
                    + "　".join(f"`{t}`<sub>{so.get(t, '?')}</sub>" for t in members),
                    unsafe_allow_html=True)

st.caption(f"数据构建于 {doc.get('built_at', '?')} · 规则：{(doc.get('rule') or {}).get('text', '')}")
