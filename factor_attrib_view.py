"""超额收益拆解渲染层：SPY + QMJ（质量）+ UMD（动量）月频回归。
只做展示，计算在后端 `factor_attrib.py`；本模块负责拼请求、画表和图。
调用方传入净值 dict，`render_factor_attribution` 处理缓存 key、地区切换和失败兜底。
"""
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_client import fetch_factor_attribution

_REGION = {"美国": "USA", "全球": "Global"}
_PARTS = [("market", "市场暴露", "#95A5A6"), ("qmj", "质量 QMJ", "#2ECC71"),
          ("umd", "动量 UMD", "#3498DB"), ("alpha", "选股 α", "#F1C40F")]


def _payload(navs: dict) -> str:
    out = {}
    for name, s in navs.items():
        s = s.astype(float).dropna()
        out[name] = {d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()}
    return json.dumps(out, sort_keys=True)


def _fmt_pct(x) -> str:
    if x is None:
        return "—"
    return f"{x * 100:+.1f}%"


def _fmt_beta(x) -> str:
    if x is None:
        return "—"
    return f"{x:.2f}"


def _fmt_t(x) -> str:
    if x is None:
        return "—"
    mark = " ✅" if abs(x) >= 2.0 else ""
    return f"{x:.1f}{mark}"


def render_factor_attribution(navs: dict, kp: str) -> None:
    st.markdown("### 🧪 超额拆解（SPY + 质量 + 动量）")
    sel = st.radio("因子口径", list(_REGION), horizontal=True, key=f"{kp}_fa_region")
    resp = fetch_factor_attribution(_payload(navs), _REGION[sel])
    if not resp.get("success"):
        st.warning(f"⚠️ 因子拆解不可用：{resp.get('error')}")
        return

    results = resp.get("results", {})

    # ── 结果表 ──
    rows = []
    for name, r in results.items():
        if r.get("error"):
            rows.append({
                "曲线": name, "月数": r.get("n"), "区间": r.get("error"),
                "年化超额": "—", "选股α": "—", "t(α)": "—",
                "β SPY": "—", "β QMJ": "—", "t(QMJ)": "—",
                "β UMD": "—", "t(UMD)": "—", "R²": "—",
            })
            continue
        contrib = r.get("contrib", {})
        rows.append({
            "曲线": name, "月数": r.get("n"), "区间": f"{r.get('start')}~{r.get('end')}",
            "年化超额": _fmt_pct(r.get("excess_ann")),
            "选股α": _fmt_pct(contrib.get("alpha")), "t(α)": _fmt_t(r.get("t_alpha")),
            "β SPY": _fmt_beta(r.get("beta_spy")),
            "β QMJ": _fmt_beta(r.get("beta_qmj")), "t(QMJ)": _fmt_t(r.get("t_qmj")),
            "β UMD": _fmt_beta(r.get("beta_umd")), "t(UMD)": _fmt_t(r.get("t_umd")),
            "R²": f"{r.get('r2'):.2f}" if r.get("r2") is not None else "—",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── 拆解条形图 ──
    names = [n for n, r in results.items() if not r.get("error")]
    if names:
        fig = go.Figure()
        for key, label, color in _PARTS:
            fig.add_trace(go.Bar(
                x=names, y=[results[n].get("contrib", {}).get(key, 0) * 100 for n in names],
                name=label, marker_color=color,
            ))
        fig.add_trace(go.Scatter(
            x=names, y=[results[n].get("excess_ann", 0) * 100 for n in names],
            mode="markers", marker_symbol="diamond", marker_size=12,
            marker_color="#E74C3C", name="年化超额",
        ))
        fig.update_layout(
            barmode="relative", height=380, yaxis_title="年化 %",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(30,30,30,0.6)",
            font=dict(color="#ccc", size=13), showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0),
        )
        st.plotly_chart(fig, use_container_width=True, key=f"{kp}_fa_bar")

    # ── 滚动图 ──
    has_rolling = any(results[n].get("rolling", {}).get("dates") for n in names)
    if not has_rolling:
        st.caption("样本不足 36 个月，不画滚动。")
    else:
        _roll_specs = [
            ("alpha_ann", "滚动 36 月 α（年化 %）", 100.0),
            ("beta_qmj", "滚动 β QMJ", 1.0),
            ("beta_umd", "滚动 β UMD", 1.0),
        ]
        cols = st.columns(3)
        for i, (field, title, scale) in enumerate(_roll_specs):
            with cols[i]:
                fig_r = go.Figure()
                for n in names:
                    roll = results[n].get("rolling", {})
                    dates = roll.get("dates") or []
                    if not dates:
                        continue
                    vals = pd.Series(roll.get(field), index=pd.to_datetime(dates)).astype(float).dropna()
                    fig_r.add_trace(go.Scatter(x=vals.index, y=vals.values * scale, mode="lines", name=n))
                fig_r.update_layout(
                    title=title, height=300,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(30,30,30,0.6)",
                    font=dict(color="#ccc", size=13), showlegend=True,
                )
                st.plotly_chart(fig_r, use_container_width=True, key=f"{kp}_fa_roll_{i}")

    st.caption("月频回归：超额 = 市场暴露 + β·QMJ + β·UMD + α。")
    st.caption("|t|≥2 标 ✅；拆解是算术年化，和总收益超额口径不同。")
    st.caption(f"因子截至 {resp.get('factor_asof')}，AQR 每月中旬更新。")
