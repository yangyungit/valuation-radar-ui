"""长坡 ROIC：资本回报率已经稳了很多年、现金是真的、还在慢慢长的公司，买了拿着。

和 page 16（ROIC 稳定）同一母题的另一条路——那页按 ROIC 高低排名、Top1 接力换手（进攻腿）；
这页不排名、不换手、没有 MA 卖出，只给候选池 + 留档回测，剩下的交给 11 题和人。
筛选、回测全在 valuation-radar/scripts/build_long_slope_roic.py，这页只负责展示。
"""

import pandas as pd
import streamlit as st

from api_client import fetch_long_slope_roic
from cn_names import cn_name_map

st.set_page_config(page_title="长坡ROIC", layout="wide", page_icon="🏔️")

st.title("🏔️ 长坡 ROIC（持有池，不换手）")

with st.sidebar:
    if st.button("🔄 强制刷新"):
        fetch_long_slope_roic.clear()
        st.rerun()
    hide_flag = st.checkbox("隐藏估值打标的", value=False)

res = fetch_long_slope_roic()
if not res.get("success"):
    st.error(f"⚠️ 后端拿不到数据：{res.get('error')}")
    st.stop()

rule, cur, bt = res["rule"], res["current"], res["backtest"]
s = bt["summary"]

st.caption(
    f"**筛法**（每周随 Sharadar 更新重算）：税前 ROIC {rule['roic_lo']:.0%}–{rule['roic_hi']:.0%} / "
    f"连续 ≥{rule['streak_min']} 个财年 ROIC ≥{rule['roic_pass']:.0%} / 近 5 年 ROIC 标准差 <{rule['roic_std5_max']*100:.0f}pp / "
    f"近 3 年营收年化 {rule['rev_g3_lo']:.0%}–{rule['rev_g3_hi']:.0%} / 近 5 年 FCF ÷ 净利润 ≥{rule['fcf_conv5_min']} / "
    f"市值 ≥${rule['mcap_min']/1e9:.0f}B / 非金融地产。"
    "**为什么这么选**：1998–2025 的年报里，ROIC ≥18% 的公司十年后还达标的只有 29%；"
    "已连续 9 年以上的能到 50%，刚达标 1 年的只有 21%；高度过了 35% 对持久性没增量信息，"
    "营收增速 >40% 和负增长的都最不持久，FCF 转化率不到七成的十年年化只有 5.4%、29% 亏钱。"
    f"**留档回测**（{bt['first_year']}–{bt['last_year']} 每年筛一次、次年 6 月末等权买、持 {bt['hold_years']} 年）："
    f"年均 {s['n_per_year']:.0f} 只，十年年化中位 {s['med']:.1%}，跑赢 SPY {s['beat']:.0%}，十年后亏钱 {s['loss']:.0%}"
    f"（SPY 同期 {s['spy']:.1%}）。**它给的是少踩雷，不是超额**——牛市跑不赢市值加权的 SPY，但十年亏钱概率只有全体高 ROIC 公司的一半。"
    "**估值只打标不剔除**：组内 EV/EBIT 最便宜 1/4 的十年亏钱率是其他档的 2.5 倍（好公司打折多半是市场闻到了什么），"
    "比自己 5 年中位贵 1.4 倍以上的也明显差；中间价位怎么买差不到 1.5 个点。"
)

flagged = [r for r in cur if r.get("flag")]
quizzed = [r for r in cur if r.get("quiz")]
c1, c2, c3, c4 = st.columns(4)
c1.metric("当前池", f"{len(cur)} 只")
c2.metric("估值打标", f"{len(flagged)} 只")
c3.metric("11 题已答", f"{len(quizzed)} 只")
c4.metric("数据截至", res["as_of"])

# ---- 当前候选池 ----
st.subheader("当前候选池（按连续达标年数排）")
cn = cn_name_map([r["ticker"] for r in cur])
rows = []
for r in cur:
    if hide_flag and r.get("flag"):
        continue
    q = r.get("quiz") or {}
    quiz_txt = ""
    if q:
        quiz_txt = f"{q.get('verdict', '')} {q.get('score', '')}分"
        if q.get("human"):
            quiz_txt += f" · 人:{q['human']}"
    rows.append({
        "代码": r["ticker"] + (" (ADR)" if r.get("adr") else ""),
        "公司": f"{cn.get(r['ticker']) or r['name']}",
        "行业": r["industry"],
        "连续年数": r["streak"],
        "ROIC": r["roic"] * 100,
        "5年中位": r["roic_med5"] * 100,
        "5年波动pp": r["roic_std5"] * 100,
        "营收3年增速": r["rev_g3"] * 100,
        "FCF转化": r["fcf_conv5"],
        "市值$B": r["mcap"] / 1e9,
        "EV/EBIT": r.get("evebit"),
        "组内分位": None if r.get("evebit_pct") is None else r["evebit_pct"] * 100,
        "相对自身5年": r.get("evebit_rel"),
        "FCF/EV": None if r.get("fcf_ev") is None else r["fcf_ev"] * 100,
        "估值提示": r.get("flag") or "",
        "11题": quiz_txt,
    })
df = pd.DataFrame(rows)


def _flag_color(v):
    return "color:#E74C3C" if isinstance(v, str) and v else ""


def _quiz_color(v):
    if not isinstance(v, str):
        return ""
    if v.startswith("好"):
        return "color:#2ECC71"
    if v.startswith("烂"):
        return "color:#E74C3C"
    return ""


st.dataframe(
    df.style
      .format({"ROIC": "{:.0f}%", "5年中位": "{:.0f}%", "5年波动pp": "{:.1f}", "营收3年增速": "{:+.0f}%",
               "FCF转化": "{:.2f}", "市值$B": "{:.1f}", "EV/EBIT": "{:.1f}", "组内分位": "{:.0f}%",
               "相对自身5年": "{:.2f}x", "FCF/EV": "{:.1f}%"}, na_rep="—")
      .map(_flag_color, subset=["估值提示"])
      .map(_quiz_color, subset=["11题"]),
    hide_index=True, use_container_width=True, height=min(60 + 36 * len(df), 1400),
)
st.caption(
    "ROIC 是 Sharadar 税前口径（EBIT ÷ 平均投入资本），芒格说的 18% 更像税后，对应税前约 24%。"
    "「连续年数」是最新财年往前数、ROIC ≥18% 一年没断的年数（回购到负资本且 EBIT 为正的算过）。"
    "「组内分位」是 EV/EBIT 在当前池里的百分位（越低越便宜）；「相对自身 5 年」是现在的 EV/EBIT ÷ 自己过去 60 个月中位。"
    "「FCF/EV」是近 5 个财年平均自由现金流 ÷ 当前企业价值（市值 + 负债 − 现金），即整家买下来每年吐多少现金；"
    "没扣股权激励，和 EV/EBIT 对着看：EV/EBIT 便宜但 FCF/EV 偏低，说明利润没变成现金。"
    "「11 题」来自 biz_quiz.db：机器按 拼合 > opus > cheap 取第一个答满的，A=2 B=1，≥16 好 ≤6 烂；没答过的留空。"
)

# ---- 留档回测 ----
st.subheader(f"留档回测：每年筛一次、等权持 {bt['hold_years']} 年")
cc = pd.DataFrame(bt["cohorts"])
cc_show = pd.DataFrame({
    "筛选年": cc.yr, "买入": cc.yr + 1, "只数": cc.n,
    "年化中位": cc.med * 100, "年化均值": cc["mean"] * 100,
    "跑赢SPY": cc.beat * 100, "十年亏钱": cc.loss * 100, "SPY年化": cc.spy * 100,
    "中位−SPY": (cc.med - cc.spy) * 100,
})
col_a, col_b = st.columns([3, 2])
with col_a:
    st.dataframe(
        cc_show.style
          .format({"年化中位": "{:.1f}%", "年化均值": "{:.1f}%", "跑赢SPY": "{:.0f}%", "十年亏钱": "{:.0f}%",
                   "SPY年化": "{:.1f}%", "中位−SPY": "{:+.1f}%"})
          .map(lambda v: "color:#2ECC71" if isinstance(v, (int, float)) and v > 0
               else ("color:#E74C3C" if isinstance(v, (int, float)) and v < 0 else ""), subset=["中位−SPY"]),
        hide_index=True, use_container_width=True,
    )
with col_b:
    vq = pd.DataFrame(bt["valuation_quartiles"])
    st.markdown("##### 按买入时组内 EV/EBIT 分位")
    st.dataframe(
        pd.DataFrame({"档": vq.bucket, "样本": vq.n, "年化中位": vq.med * 100,
                      "跑赢SPY": vq.beat * 100, "十年亏钱": vq.loss * 100})
          .style.format({"年化中位": "{:.1f}%", "跑赢SPY": "{:.0f}%", "十年亏钱": "{:.0f}%"}),
        hide_index=True, use_container_width=True,
    )
    st.caption("最便宜那档年化最低、亏钱最多；中间和最贵两档差不多。便宜组里的大赢家几乎全是 2008–09 买的——有效的便宜是「大盘跌」，不是「个股跌」。")

st.caption(
    "买入 = 筛选年次年 6 月末复权价，退市票用最后可得价格（之后按零收益），没算滑点（十年一次买入可忽略）。"
    "2014–2015 两批持有到 2024–2025，正好撞上市值加权 SPY 被几只巨头拉着跑的年份，等权的几十只「无聊公司」结构上追不上；"
    "2003–2010 那几批持有到 2013–2020 大多是赢的。这是基准选的时段问题，不是筛子问题。"
    "**用法**：这是候选池不是买入信号——池里仍有六成跑不赢 SPY，哪些能赢数字分不出来，那是 11 题该干的活；"
    "选中了买了别动，卖的触发是生意变了（ROIC 结构性掉下去、营收停滞、份额丢），不是股价跑输。"
)
