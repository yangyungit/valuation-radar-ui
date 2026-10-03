import math

import streamlit as st
import pandas as pd

import holdings_viz as hv
from api_client import fetch_dynasty_gold_leader
from gold_leader_viz import (
    INSIGHT_CSS, WINDOWS, build_sector_ribbon, norm_series, render_equity_chart,
    render_holding_cards, render_meta_captions, render_slot_segment_returns,
    render_stats_cards, render_time_window_slider, show_missing_warning, split_month_spans,
)

st.set_page_config(page_title="戴金龙头", layout="wide")
st.markdown(INSIGHT_CSS, unsafe_allow_html=True)

def render_copy_tab(gl: dict, dates, meta: dict, signal_month: str) -> None:
    rc = gl.get("ribbon_copy") or {}
    if not rc.get("available"):
        st.info("后端未返回 252 日照搬口径（`ribbon_copy`），可能是后端版本较旧。")
        return
    show_missing_warning(rc)
    eq = gl.get("equity", {})
    st.caption(
        "两个槽直接用 19 页王朝接力选仓层（C+D 共 25 只板块 ETF，**252 日动量**、资历接力进场、"
        "buffer 守擂）每月选出的两只 ETF，各买板块内龙头第 1 名，擂主保护同现行。"
        "带 19 页同一套差速器：两只 ETF 打分差 ≥1.0 时两个槽都买强势板块的前 2 名龙头，"
        "回落到 0.6 以下再分回两个板块"
        f"（展示窗口内 {rc.get('single_months', 0)} 个月单仓）。"
        "**不过** RS 差滞回、银牌名次死区，也**没有**跑输 SPY 转 BIL 的门。"
        "注意 19 页实验台默认是 504 日动量，这里用 252 日：504 日实测更差（同期 Calmar 1.00）。"
        f"D 组成分从 {rc.get('coverage_start', '')} 起才有，10Y 窗口下本口径从那时起算。"
    )

    st.markdown(f"##### 和现行同期对比（{rc['compare_from']} 起）")
    _same = rc.get("stats_same_period") or {}
    _cmp = []
    for _name, _k in (("现行（C 组金银牌）", "current"), ("252 日照搬王朝接力", "copy"),
                      ("252 日照搬（不开差速器）", "copy_plain")):
        _s = _same.get(_k)
        if not _s:
            continue
        _cmp.append({
            "口径": _name,
            "总收益": f"{_s.get('cum_return', 0) * 100:.0f}%",
            "CAGR": f"{_s.get('cagr', 0) * 100:.1f}%",
            "MaxDD": f"{_s.get('max_dd', 0) * 100:.1f}%",
            "Calmar": f"{_s.get('calmar', 0):.2f}",
            "换股次数": f"{_s.get('n_swaps', 0)}",
            "年化换手": f"{_s.get('ann_turnover', 0):.2f}",
            "累计成本": f"{_s.get('cum_cost', 0) * 100:.1f}%",
        })
    if _cmp:
        st.dataframe(pd.DataFrame(_cmp), use_container_width=True, hide_index=True)
    st.caption("统计按整个同期算，不跟随下方时间窗口滑块。")

    st.markdown(f"##### 截至 {signal_month} 信号的模拟持仓｜252 日照搬")
    render_holding_cards(
        (rc.get("current_holdings") or {}).get("slots", []),
        "选仓层当月无可用板块龙头",
    )

    win_lo, win_hi = render_time_window_slider(dates, "gl_copy")
    win_lo = max(win_lo, pd.Timestamp(rc["compare_from"]))

    st.markdown("##### 组合收益（起点归一为 1）")
    render_equity_chart(dates, eq, [
        ("ribbon_copy", "252 日照搬王朝接力", "#E84393", True),
        ("ribbon_copy_plain", "252 日照搬（不开差速器）", "#9B59B6", True),
        ("two_sector", "现行（C 组金银牌）", "#F39C12", True),
        ("spy", "SPY", "#3498DB", True),
    ], "gl_eq_copy", win_lo, win_hi)

    st.markdown("##### 统计卡（本口径，展示窗口全段）")
    _stats_rc = dict(rc.get("stats", {}))
    _rc_nav = norm_series(eq.get("ribbon_copy", []), dates)
    if not _rc_nav.empty:
        _stats_rc["r2"] = hv.compute_nav_kpi(_rc_nav).get("r2")
    render_stats_cards(_stats_rc)

    st.markdown("##### Slot 分段收益")
    rb_slots, rb_names, rb_months, rb_dim, _ = build_sector_ribbon(
        gl.get("ribbon_copy_timeline") or [], str(meta.get("display_start", ""))[:7])
    ribbons = hv.relay_ribbon_segments(
        rb_slots, rb_months, rb_names, rb_dim, "<br>未选中") if rb_months else None
    if not render_slot_segment_returns(
        rc.get("slot_equity") or [], rc.get("holdings_timeline") or [],
        dates, eq.get("spy", []), "gl_copy", win_lo, win_hi, set(),
        ribbons=ribbons, ribbon_labels=("槽A 板块", "槽B 板块"),
    ):
        st.caption("后端暂未返回 slot_equity。")
    else:
        st.caption("槽A / 槽B 顶部色带 = 选仓层当月给的两只 ETF。槽B 压暗 = 差速器单仓月，"
                   "两个槽都买槽A 板块的龙头。")

    st.markdown("##### 月度明细")
    _rows = [
        r for r in (gl.get("ribbon_copy_timeline") or [])
        if r.get("month", "") >= str(meta.get("display_start", ""))[:7]
    ]
    if _rows:
        _tbl = pd.DataFrame([{
            "月份": r.get("month"),
            "槽A 板块": r.get("sector_etf") or "—",
            "槽B 板块": r.get("silver_sector_etf") or r.get("sector_etf") or "—",
            "持仓": " + ".join(r.get("picks") or []),
            "擂主留任": "、".join(r.get("leader_held_over") or []),
            "数据缺失": "、".join(r.get("data_missing") or []),
        } for r in reversed(_rows)])
        st.dataframe(_tbl, use_container_width=True, hide_index=True, height=320)
    else:
        st.caption("后端暂未返回月度明细。")


with st.sidebar:
    if st.button("🔄 强制刷新"):
        fetch_dynasty_gold_leader.clear()
        st.rerun()

st.title("🏅 戴金龙头 (Gold Dynasty Leader)")
st.caption("C组戴金板块 → 板块内市值前3选5年超额 Top2；金牌板块 RS 领先银牌不足阈值时，第二个槽改从银牌板块选龙头 → 下月执行。上月持有的龙头只要落后新第 1 名不太多（按 5 年涨幅比值算，门槛见下方月度明细）就继续持有，减少板块内来回换手。与 12M 动量守擂不是一套方法，已从 C组双龙 拆出单独成页。")

_window = st.radio(
    "时间跨度",
    options=WINDOWS,
    index=WINDOWS.index("5Y"),
    horizontal=True,
    key="gl_window",
    help="月末快照：3Y/5Y/10Y 约对应 36/60/120 个格子",
)

st.caption(
    "**主线**：C组王朝接力图戴金板块 → 板块内市值前3、5年超额 Top2（上月持有的落后不多就留任）→ 下月执行。"
    "**诚实声明**：信号**不看未来**、可执行规则模拟；股票池=**逐月真实标普500成分**"
    "（PIT，Sharadar 数据含当年被剔除/退市/收购的公司），**已去生存者偏差**。"
)

_gl_c1, _gl_c2 = st.columns([1.1, 2.0])
with _gl_c1:
    _gl_rebal = st.toggle(
        "月度等权再平衡",
        value=True,
        key="gl_rebal",
        help="每月把两个槽位重新拉回50/50；关闭时各槽位独立复利。"
             "默认打开：这套口径的防抖参数是在开着再平衡的前提下寻优出来的。",
    )
with _gl_c2:
    st.caption(
        "固定持有 Top2；再平衡=每月卖一点涨多的槽位、补一点涨少的槽位，"
        "重新回到两个槽位各 50%。这套口径（含擂主保护、金牌回退防护）同一份 10Y 面板切三段的 Calmar，"
        "开着再平衡是 2.18/1.50/1.12，关掉是 1.58/1.56/1.14——关掉后 3Y 回撤从 −18.0% 扩到 −27.8%。"
    )

with st.expander("交易假设"):
    _gl_cost = st.slider(
        "单边成本 (bps)", 0, 50, 10, key="gl_cost",
        help="买/卖各算一次，扣在成交名义额上；影响回测净值和统计。",
    )
    _gl_rs_gap = st.slider(
        "RS 差进场阈",
        min_value=-5.0, max_value=40.0, value=5.0, step=0.5, key="gl_rs_gap",
        help="金牌板块 RS 领先银牌不到这个点数时，第二个槽改从银牌板块选龙头。"
             "调大=更常分两个板块；调到 0 以下≈两个槽都选同一金牌板块 Top2（不分板块）。",
    )
    _gl_rs_gap_exit = st.slider(
        "滞回退出阈（RS 差回到这个点数以上才合回一个板块）",
        min_value=0.0, max_value=45.0, value=10.0, step=0.5,
        key="gl_rs_gap_exit",
        help="拖到等于进场阈就没有滞回；调大=已经分开后更黏，减少阈值边界反复横跳。"
             "改前这套口径 5Y 的 29 次槽1换手里有 20 次来自这种横跳。",
    )
    _gl_silver_buf = st.slider(
        "银牌板块名次死区", 0, 6, 6, key="gl_silver_buf",
        help="0=关闭（每月改选 king_score 第 2 名）；N>0=上月的银牌板块只要今月名次还在前 N "
             "且 RS>0 就留任。关掉时银牌板块 5 年换 34 次、跨 8 个板块，零粘性。",
    )
    _gl_gold_revert = st.toggle(
        "金牌回退防护",
        value=True,
        key="gl_gold_revert",
        help="刚被换掉的老金牌（最近 12 个月连续当过 3 个月以上）又冲回第 1 名时，"
             "要连续 3 个月第 1 才换回去，期间留任现金牌（哪怕它当月 RS 跑输 SPY）、老金牌降成银牌。"
             "只管左列金牌；同样规则加到银牌上实测 3Y Calmar 从 1.83 掉到 1.31，所以不加。",
    )
    st.caption(
        "上面三个默认值 5.0 / 10.0 / 6 是 scripts/sweep_dd_silver_antiwhipsaw.py 在一份 "
        "10Y 面板上切 3Y/5Y/10Y 三段、504 组网格、按三段归一化 Calmar 的 maximin 选出来的。"
        "目标用 Calmar 而不是累计收益，因为累计收益里 2023-05 单月就贡献 +18.1%，"
        "拿它当目标等于对那一个月过拟合。"
    )

_gl = fetch_dynasty_gold_leader(
    window=_window, rebalance=_gl_rebal, cost_bps=float(_gl_cost),
    silver_rs_gap=float(_gl_rs_gap),
    silver_rs_gap_exit=float(_gl_rs_gap_exit),
    silver_buffer_n=int(_gl_silver_buf),
    gold_revert=bool(_gl_gold_revert),
)

if not _gl.get("success"):
    st.warning(f"⚠️ 戴金龙头回测暂不可用：{_gl.get('error', '未知错误')}")

if _gl.get("success"):
    _meta = _gl.get("meta", {})
    render_meta_captions(_meta, _window)

    _signal_as_of = str(_meta.get("signal_as_of", "") or "")
    _signal_month = _signal_as_of[:7] if _signal_as_of else "最近信号"
    _eq = _gl.get("equity", {})
    _dates = pd.to_datetime(_gl.get("dates", []), errors="coerce")
    _two = _gl.get("two_sector", {}) or {}
    _hold_gap = _two.get("leader_hold_gap")
    _hold_gap_txt = f"约 {math.exp(_hold_gap) - 1:.0%}" if isinstance(_hold_gap, (int, float)) else "门槛"

    _tab_cur, _tab_copy = st.tabs(["🥇 现行：C 组金银牌", "🔁 252 日照搬王朝接力"])
    with _tab_cur:
        if not _two.get("available"):
            st.info("后端未返回强弱切换口径（`two_sector`），可能是后端版本较旧。")
        else:
            show_missing_warning(_two)
            _rb_slots, _rb_names, _rb_months, _rb_dim, _rb_split = build_sector_ribbon(
                _gl.get("two_sector_timeline") or [], str(_meta.get("display_start", ""))[:7]
            )
            _split_n = _two.get("split_months", 0)
            _total_n = _two.get("total_months", 0)
            _gap = _two.get("silver_rs_gap", 5.0)
            _gap_exit = _two.get("silver_rs_gap_exit")
            _buf_n = _two.get("silver_buffer_n", 0) or 0
            _held_n = _two.get("held_over_months", 0) or 0
            st.caption(
                f"金牌板块 RS 领先银牌不到 **{_gap:g}** 个点时，第二个槽改从**银牌板块**选龙头；"
                f"领先够多时两个槽都选金牌板块 Top2。展示期内 **{_split_n}/{_total_n}** 个月真的分了两个板块。"
                "当月没有戴金板块时仍持 BIL，不因为有银牌板块就破例持股。"
            )
            _anti = []
            if _gap_exit is not None and _gap_exit > _gap:
                _anti.append(
                    f"滞回生效：没分开时 RS 差 < **{_gap:g}** 才分，已分开时要回到 "
                    f"**{_gap_exit:g}** 以上才合回"
                )
            else:
                _anti.append("滞回未生效（退出阈 = 进场阈），每月按同一个硬阈值判断")
            if _buf_n > 0:
                _anti.append(
                    f"银牌名次死区 N=**{_buf_n}**，展示期内 **{_held_n}** 个月的银牌板块是留任的"
                )
            else:
                _anti.append("银牌名次死区关闭，每月改选 king_score 第 2 名")
            if _two.get("gold_revert"):
                _anti.append(
                    f"金牌回退防护开启，展示期内 **{_two.get('gold_revert_months', 0)}** 个月"
                    "金牌是留任的（老金牌冲回第 1 未满 3 个月）"
                )
            else:
                _anti.append("金牌回退防护关闭，每月取 king_score 第 1 名当金牌")
            st.caption("｜".join(_anti))
            st.caption(
                "**别只看收益**：这套口径的超额里 2023-05 单月就贡献 +18.1%，收益比值一步"
                "从 0.98 跳到 1.158 之后再没回落，所以三个防抖参数是按 Calmar 而不是按累计"
                "收益寻优的。三段 Calmar 从 1.14/1.24/0.92 提到 1.36/1.48/1.12，同时换股"
                "次数从 31/39/72 降到 26/34/63（同一份 10Y 面板切三段实测，"
                "和上面按窗口分别拉的数字不是一个口径，短窗口不是长窗口的尾部切片）。"
            )

            st.markdown(f"##### 截至 {_signal_month} 信号的模拟持仓｜戴金龙头Top2")
            render_holding_cards(
                _two.get("current_holdings", {}).get("slots", []),
                "当月无 C 组戴金板块或无足够龙头候选",
            )

            _win_lo, _win_hi = render_time_window_slider(_dates, "gl_two")

            st.markdown("##### 组合收益（起点归一为 1）")
            _eq_plot = dict(_eq)
            for _row in (_two.get("slot_equity") or []):
                _eq_plot[f"slot{int(_row.get('slot', 0))}"] = _row.get("equity", [])
            render_equity_chart(_dates, _eq_plot, [
                ("two_sector", "戴金龙头Top2（强弱切换+擂主保护）", "#F39C12", True),
                ("spy", "SPY", "#3498DB", True),
                ("slot0", "左列 · 金牌槽", "rgba(243,156,18,0.55)", True, "dot"),
                ("slot1", "右列 · 银牌槽", "rgba(170,178,189,0.75)", True, "dot"),
            ], "gl_eq_two", _win_lo, _win_hi, split_month_spans(_rb_split, _win_lo, _win_hi))
            st.caption(
                "橙色竖条 = 那段时间真的分投了金银两个板块，没底色的月份两个槽都在金牌板块里。"
                "左列 / 右列是两个槽各自的净值，组合曲线 = 两条各占一半取平均；"
                "上方时间窗口同步套用到本图和下方 Slot 分段图"
            )

            st.markdown("##### 统计卡")
            _stats_two = dict(_two.get("stats", {}))
            _two_nav = norm_series(_eq.get("two_sector", []), _dates)
            if not _two_nav.empty:
                _stats_two["r2"] = hv.compute_nav_kpi(_two_nav).get("r2")
            render_stats_cards(_stats_two)
            st.caption("logR² = 净值曲线取对数后对时间做线性回归的拟合优度，越接近 1 越是匀速上涨、越低说明涨跌越颠簸。")

            st.markdown("##### Slot 分段收益")
            _ribbons = hv.relay_ribbon_segments(
                _rb_slots, _rb_months, _rb_names, _rb_dim, "<br>未选中"
            ) if _rb_months else None
            if _rb_months:
                st.caption(
                    "每张接力图顶部的色带是对应的板块：槽A 顶部 = 左列金牌板块，槽B 顶部 = 右列银牌板块。"
                    "**和本页回测完全同源**：C 组 11 个 SPDR 按 king_score 排名，第 1 名 = 金牌，"
                    "第 2 名带名次死区 = 银牌，月末出信号、下月第一个交易日执行。"
                    "**银牌压暗的段 = 那几个月银牌板块没被选中**，金牌 RS 领先够多，槽B 实际买的是"
                    "金牌板块的第 2 只龙头；银牌亮着才是真的分投金银。"
                    "灰段 = 当月没有戴金板块、持 BIL 空仓。"
                    "开着金牌回退防护时，被挡下的月份左列仍是原金牌，不一定是当月 king_score 第 1 名。"
                    "条带从第一个有戴金板块的月份画起——RS 要满 252 个交易日才有第一个值，"
                    "窗口起点往后约一年的月份查不到 king_score，回测那几个月也躺在 BIL 上，"
                    "但那是数据没热起来、不是判断出来的空仓，所以不画进条带。"
                )
            if not render_slot_segment_returns(
                _two.get("slot_equity") or [], _two.get("holdings_timeline") or [],
                _dates, _eq.get("spy", []), "gl_two", _win_lo, _win_hi, _rb_split,
                ribbons=_ribbons, ribbon_labels=("金牌", "银牌"),
            ):
                st.caption("后端暂未返回 slot_equity。")
            else:
                st.caption("橙色竖条含义同上：那几个月真的分投了金银两个板块。")

            st.markdown("##### 哪些月份走了银牌板块")
            _ts_rows = [
                r for r in (_gl.get("two_sector_timeline") or [])
                if r.get("month", "") >= str(_meta.get("display_start", ""))[:7]
            ]
            if _ts_rows:
                _tbl = pd.DataFrame([{
                    "月份": r.get("month"),
                    "金牌板块": r.get("sector_etf") or "—",
                    "银牌板块": r.get("silver_sector_etf") or "—",
                    "RS 差": r.get("rs_gap"),
                    "分两个板块": "是" if r.get("split_sectors") else "",
                    "持仓": " + ".join(r.get("picks") or []),
                    "擂主留任": "、".join(r.get("leader_held_over") or []),
                    "数据缺失": "、".join(r.get("data_missing") or []),
                } for r in reversed(_ts_rows)])
                st.dataframe(_tbl, use_container_width=True, hide_index=True, height=320)
                st.caption(f"擂主留任 = 硬排名本该换掉、但因落后第 1 名不到 {_hold_gap_txt} 继续持有的票。")
            else:
                st.caption("后端暂未返回月度明细。")

            st.markdown("##### 板块内龙头防抖对照")
            _plain = _gl.get("two_sector_plain", {}) or {}
            _lp = _gl.get("leader_pair", {}) or {}
            if not (_plain.get("available") or _lp.get("available")):
                st.caption("后端暂未返回板块内防抖对照。")
            else:
                st.caption(
                    "板块怎么选和上面完全一样，只改板块内选哪只龙头。领先幅度 = "
                    f"ln((100+前者5年涨幅)/(100+后者5年涨幅))。**现行**已含擂主保护（落后不到 {_hold_gap_txt} 留任）；"
                    "**无防抖**是改之前的旧主线，每月硬排名；"
                    f"**板块内对半**是第 1 名领先下一名不到 {_lp.get('gap', 0):.1%} 就两只各半仓。"
                    "门槛 2026-10-03 从约 16% 放宽到约 28%，为的是挡住 GOOGL→META→GOOGL 这类板块内来回切，"
                    "放宽后三段 Calmar 都不低于旧门槛、年化换手再低 5-10%。"
                )
                render_equity_chart(_dates, _eq, [
                    ("two_sector", "现行（擂主保护）", "#F39C12", True),
                    ("two_sector_plain", "无防抖（旧主线）", "#95A5A6", True),
                    ("leader_pair", "板块内对半", "#9B59B6", True),
                    ("spy", "SPY", "#3498DB", True),
                ], "gl_eq_leader", _win_lo, _win_hi)
                _cmp = []
                for _name, _s in (("现行（擂主保护）", _two.get("stats", {})),
                                  ("无防抖（旧主线）", _plain.get("stats", {})),
                                  ("板块内对半", _lp.get("stats", {}))):
                    if not _s:
                        continue
                    _cmp.append({
                        "口径": _name,
                        "总收益": f"{_s.get('cum_return', 0) * 100:.0f}%",
                        "CAGR": f"{_s.get('cagr', 0) * 100:.1f}%",
                        "MaxDD": f"{_s.get('max_dd', 0) * 100:.1f}%",
                        "Calmar": f"{_s.get('calmar', 0):.2f}",
                        "年化换手": f"{_s.get('ann_turnover', 0):.2f}",
                        "累计成本": f"{_s.get('cum_cost', 0) * 100:.1f}%",
                    })
                st.dataframe(pd.DataFrame(_cmp), use_container_width=True, hide_index=True)
                st.caption("板块内对半是 4 个半仓位，换股次数和 2 仓位口径不可比，这里只比年化换手。"
                           "统计按整个展示窗口算，不跟随上方时间窗口滑块。")
                _diff = []
                for _label, _v in (("无防抖（旧主线）", _plain), ("板块内对半", _lp)):
                    for _r in (_v.get("timeline") or []):
                        if _r.get("differs"):
                            _diff.append({"月份": _r.get("month"), "口径": _label,
                                          "现行持仓": _r.get("base_holdings"),
                                          "本口径持仓": _r.get("holdings")})
                if _diff:
                    st.markdown("###### 和现行持仓不一样的月份")
                    st.dataframe(pd.DataFrame(sorted(_diff, key=lambda r: r["月份"], reverse=True)),
                                 use_container_width=True, hide_index=True, height=320)
                    st.caption("「A/B」= 这个仓位两只各半。")

    with _tab_copy:
        render_copy_tab(_gl, _dates, _meta, _signal_month)
