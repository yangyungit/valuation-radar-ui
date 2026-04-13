"""
B 组信念积累 + 冠军守擂引擎
Conviction Accumulation + Champion Defends Title
═══════════════════════════════════════════════════════════════════

传统「因子评分 → 排名 → 取 Top N」的结构性缺陷：
  标的分数聚集 → 边界噪声 → 每月重排 → 高换手低效率。
  越优化因子，标的越"合格"，排名越拥挤，换手越高 —— 这是 paradox。

本引擎的解决方案：

  ① 信念积累 (Conviction Accumulation)
     每个标的维护一个「信念值」C ∈ [0, 100]。
     因子得分高 → 信念持续累加；因子得分低 → 信念自然衰减。
     需要连续多月表现好才能积累到入选门槛 → 天然过滤闪现标的。

     更新公式：C(t) = C(t-1) × decay + FactorScore(t) × accum_rate
     稳态信念：C_ss = Score × accum_rate / (1 - decay)

  ② 在位者惯性 (Holder Inertia)
     RS120d 等高波动因子引入后，月间分数波动会导致碎片化换手。
     在位者使用 holder_decay_rate（> decay_rate），信念衰减更慢。
     效果：动量噪声不会轻易驱逐在位者，但持续走弱仍会被淘汰。

  ③ 冠军守擂 (Champion Defends Title)
     在位者只需「不跌破退出线」即可留任，无需每月重新证明自己。
     挑战者必须比在位者高出 CHALLENGE_MARGIN 才能替换。
     这消灭了边界噪声导致的无效换手。

  选拔规则：
     A. 在位者: conviction ≥ exit_threshold → 留任
     B. 空位 → conviction ≥ entry_threshold 中选最高者
     C. 满座挑战: challenger.conv > weakest_incumbent.conv + margin → 替换

依赖: 无外部依赖，纯 Python dict 操作。
"""

from __future__ import annotations

CONVICTION_B_CONFIG: dict = {
    "decay_rate":        0.75,   # 非在位者每月信念衰减系数
    "holder_decay_rate": 0.78,   # 在位者衰减系数（比标准 0.75 慢，但不高于 0.786 以保证走弱仍被淘汰）
    "accumulate_rate":   0.25,   # 因子分 → 信念的转化率
    "entry_threshold":   55.0,   # 入选门槛
    "exit_threshold":    35.0,   # 退出门槛（提高门槛，不允许低信念标的赖着不走）
    "challenge_margin":   8.0,   # 守擂优势（降低，让优质挑战者更容易上位）
    "max_conviction":   100.0,   # 信念值上限
    "top_n":               3,    # 持仓席位数
}

CONVICTION_A_CONFIG: dict = {
    "decay_rate":        0.78,   # 比 B 组更慢衰减 → 压舱石追求极低换手
    "holder_decay_rate": 0.80,   # 更强在位者惯性（上限: 30×0.22/(1-0.80)=33 < exit 35 ✓）
    "accumulate_rate":   0.22,   # 比 B 组更慢积累 → 需要更持久的好表现才能入选
    "entry_threshold":   55.0,   # 入选门槛（与 B 组相同）
    "exit_threshold":    35.0,   # 退出门槛（与 B 组相同）
    "challenge_margin":  10.0,   # 比 B 组更高守擂优势 → 压舱石应更难被挑战
    "max_conviction":   100.0,   # 信念值上限
    "top_n":               3,    # 持仓席位数
}

# Status constants
STATUS_DEFENDING  = "defending"    # 留任
STATUS_NEW_ENTRY  = "new_entry"    # 新晋入选（信念达标）
STATUS_CHALLENGED = "challenged"   # 挑战上位（击败在位者）
STATUS_COLD_START = "cold_start"   # 新兵（候选池不足时的兜底）
STATUS_DROPPED    = "dropped"      # 信念衰退退出

_STATUS_LABELS: dict = {
    STATUS_DEFENDING:  ("🛡️ 留任",   "#2ECC71"),
    STATUS_NEW_ENTRY:  ("🆕 新晋",   "#3498DB"),
    STATUS_CHALLENGED: ("⚔️ 挑战",   "#F39C12"),
    STATUS_COLD_START: ("🔰 新兵",   "#9B59B6"),
    STATUS_DROPPED:    ("📉 退出",   "#E74C3C"),
}


def get_status_label(status: str) -> tuple[str, str]:
    """返回 (中文标签, 颜色hex)。"""
    return _STATUS_LABELS.get(status, ("—", "#888"))


# ═══════════════════════════════════════════════════════════════════
#  信念更新
# ═══════════════════════════════════════════════════════════════════

def update_convictions(
    prev_state: dict[str, float],
    factor_scores: dict[str, float],
    current_holders: list[str] | None = None,
    config: dict | None = None,
) -> dict[str, float]:
    """
    更新所有标的的信念值。

    在位者使用 holder_decay_rate（慢衰减），非在位者使用 decay_rate（标准衰减）。
    这赋予当前持仓「惯性」——RS120d 等高波动因子的短期回调不会
    立刻侵蚀在位者信念，但持续走弱仍会被淘汰。

    Args:
        prev_state:      {ticker: conviction} 上月信念状态
        factor_scores:   {ticker: factor_score ∈ [0,100]} 本月因子得分
        current_holders: 当前在位 ticker 列表（享受慢衰减）
        config:          引擎参数 (默认 CONVICTION_B_CONFIG)

    Returns:
        {ticker: new_conviction} — 信念 < 0.5 的 ticker 会被清理
    """
    cfg = config or CONVICTION_B_CONFIG
    decay        = cfg["decay_rate"]
    holder_decay = cfg.get("holder_decay_rate", decay)
    accum        = cfg["accumulate_rate"]
    cap          = cfg["max_conviction"]
    holders      = set(current_holders or [])

    new_state: dict[str, float] = {}
    all_tickers = set(prev_state) | set(factor_scores)

    for tk in all_tickers:
        old_conv = prev_state.get(tk, 0.0)
        score    = factor_scores.get(tk, 0.0)

        d = holder_decay if tk in holders else decay
        new_conv = old_conv * d + score * accum
        new_conv = max(0.0, min(cap, new_conv))

        if new_conv >= 0.5:
            new_state[tk] = round(new_conv, 1)

    return new_state


# ═══════════════════════════════════════════════════════════════════
#  Top N 选拔（守擂制）
# ═══════════════════════════════════════════════════════════════════

def select_top_n(
    conviction_state: dict[str, float],
    current_holders: list[str],
    ticker_names: dict[str, str] | None = None,
    factor_scores: dict[str, float] | None = None,
    config: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    基于信念值 + 冠军守擂逻辑选出 Top N。

    Args:
        conviction_state: {ticker: conviction}
        current_holders:  上月 Top N ticker 列表
        ticker_names:     {ticker: 中文名}
        factor_scores:    {ticker: 本月因子得分} (用于记录展示)
        config:           引擎参数

    Returns:
        (selected, decisions)
        selected:  [{ticker, name, conviction, factor_score, status}, ...]
        decisions: [{ticker, action, detail}, ...]  每条决策的可追溯记录
    """
    cfg       = config or CONVICTION_B_CONFIG
    exit_th   = cfg["exit_threshold"]
    entry_th  = cfg["entry_threshold"]
    margin    = cfg["challenge_margin"]
    n         = cfg["top_n"]
    names     = ticker_names or {}
    scores    = factor_scores or {}

    decisions: list[dict] = []

    # ── Step 1: 在位者守擂 ──
    retained: list[str] = []
    for holder in current_holders:
        conv = conviction_state.get(holder, 0.0)
        if conv >= exit_th:
            retained.append(holder)
            decisions.append({
                "ticker": holder, "action": STATUS_DEFENDING,
                "detail": f"信念 {conv:.0f} >= 退出线 {exit_th:.0f}，留任",
            })
        else:
            decisions.append({
                "ticker": holder, "action": STATUS_DROPPED,
                "detail": f"信念 {conv:.0f} < 退出线 {exit_th:.0f}，退出",
            })

    # ── Step 2: 满座时的挑战赛 ──
    if len(retained) >= n:
        weakest     = min(retained, key=lambda t: conviction_state.get(t, 0.0))
        weakest_conv = conviction_state.get(weakest, 0.0)

        challengers = sorted(
            [t for t in conviction_state
             if t not in retained and conviction_state[t] >= entry_th],
            key=lambda t: conviction_state[t],
            reverse=True,
        )
        if challengers:
            best = challengers[0]
            best_conv = conviction_state[best]
            if best_conv > weakest_conv + margin:
                retained.remove(weakest)
                retained.append(best)
                decisions.append({
                    "ticker": best, "action": STATUS_CHALLENGED,
                    "detail": (f"信念 {best_conv:.0f} > "
                               f"{weakest} 信念 {weakest_conv:.0f} + "
                               f"守擂优势 {margin:.0f}，挑战上位"),
                })
                decisions.append({
                    "ticker": weakest, "action": STATUS_DROPPED,
                    "detail": f"被 {best} 挑战下位",
                })
        selected_tickers = retained[:n]

    else:
        # ── Step 3: 空位填补 ──
        open_seats = n - len(retained)
        eligible = sorted(
            [t for t in conviction_state
             if t not in retained and conviction_state[t] >= entry_th],
            key=lambda t: conviction_state[t],
            reverse=True,
        )
        for t in eligible[:open_seats]:
            retained.append(t)
            decisions.append({
                "ticker": t, "action": STATUS_NEW_ENTRY,
                "detail": f"信念 {conviction_state[t]:.0f} >= 入选线 {entry_th:.0f}，新晋入选",
            })
            open_seats -= 1

        # ── Step 4: 新兵兜底 ──
        if len(retained) < n:
            remaining = sorted(
                [t for t in conviction_state
                 if t not in retained and conviction_state[t] > 0],
                key=lambda t: conviction_state[t],
                reverse=True,
            )
            for t in remaining[: n - len(retained)]:
                retained.append(t)
                decisions.append({
                    "ticker": t, "action": STATUS_COLD_START,
                    "detail": f"信念 {conviction_state[t]:.0f}（候选池不足，新兵补位）",
                })

        selected_tickers = retained[:n]

    # ── 组装结果 ──
    selected: list[dict] = []
    for tk in selected_tickers:
        conv   = conviction_state.get(tk, 0.0)
        status = STATUS_COLD_START
        for d in decisions:
            if d["ticker"] == tk and d["action"] != STATUS_DROPPED:
                status = d["action"]
                break

        selected.append({
            "ticker": tk,
            "name": names.get(tk, tk),
            "conviction": round(conv, 1),
            "factor_score": round(scores.get(tk, 0.0), 1),
            "status": status,
        })

    selected.sort(key=lambda x: x["conviction"], reverse=True)
    return selected, decisions


# ═══════════════════════════════════════════════════════════════════
#  White-box 解释生成
# ═══════════════════════════════════════════════════════════════════

def explain_config_html(config: dict | None = None) -> str:
    """生成信念守擂制的白盒公式 HTML（用于 Streamlit unsafe_allow_html）。"""
    cfg = config or CONVICTION_B_CONFIG
    decay        = cfg["decay_rate"]
    holder_decay = cfg.get("holder_decay_rate", decay)
    accum        = cfg["accumulate_rate"]
    entry        = cfg["entry_threshold"]
    exit_th      = cfg["exit_threshold"]
    margin       = cfg["challenge_margin"]

    steady_70 = round(70 * accum / (1 - decay), 0)
    steady_50 = round(50 * accum / (1 - decay), 0)
    holder_steady_50 = round(50 * accum / (1 - holder_decay), 0)

    return f"""
    <div style='background:#1a1a1a; border-left:3px solid #F39C12;
         padding:14px; margin-bottom:16px; font-size:14px; color:#ccc; border-radius:4px;'>
    <b>🛡️ 信念守擂制 — 超越因子排名，消灭边界噪声换手</b><br><br>

    <span style='color:#aaa;'>
    传统「因子评分 → 取 Top 3」每月重排，分数接近的标的反复切换。<br>
    信念守擂制引入三层防护，将因子分数降级为<b>「信念积分的输入信号」</b>：
    </span><br><br>

    <b style='color:#F39C12;'>① 信念积累层</b> —
    标的需<b>连续多月</b>表现好才能入选，偶尔失利不会被淘汰<br>
    <code style='color:#F39C12; background:#2a2000; padding:2px 8px; border-radius:3px;'>
    挑战者: C(t) = C(t-1) &times; {decay} + Score &times; {accum}
    </code><br>
    <span style='color:#888; font-size:13px;'>
    入选门槛 = <b>{entry:.0f}</b> &nbsp;|&nbsp;
    退出门槛 = <b>{exit_th:.0f}</b> &nbsp;|&nbsp;
    稳态：70 分 → {steady_70:.0f}，50 分 → {steady_50:.0f}
    </span><br><br>

    <b style='color:#3498DB;'>② 在位者惯性层</b> —
    当前持仓享有<b>慢衰减</b>，RS₁₂₀ 等快因子的短期回调不会立刻侵蚀信念<br>
    <code style='color:#3498DB; background:#001a2a; padding:2px 8px; border-radius:3px;'>
    在位者: C(t) = C(t-1) &times; {holder_decay} + Score &times; {accum}
    </code><br>
    <span style='color:#888; font-size:13px;'>
    在位者稳态：50 分 → {holder_steady_50:.0f}（vs 挑战者 {steady_50:.0f}）&nbsp;|&nbsp;
    效果：动量噪声不导致换手，持续走弱仍会被淘汰
    </span><br><br>

    <b style='color:#E74C3C;'>③ 冠军守擂层</b> —
    在位者享有守擂优势，挑战者必须显著超越才能替换<br>
    <code style='color:#E74C3C; background:#2a0000; padding:2px 8px; border-radius:3px;'>
    替换条件：挑战者信念 &gt; 在位者信念 + {margin:.0f}
    </code><br>
    <span style='color:#888; font-size:13px;'>
    效果：微小分差不再触发换手，持仓周期显著延长，闪现标的被天然过滤。
    </span><br><br>

    <hr style='border:none; border-top:1px solid #333; margin:10px 0;'>
    <b style='color:#ddd;'>📖 状态标签说明</b><br>
    <div style='margin-top:8px; display:flex; flex-direction:column; gap:5px; font-size:13px;'>
      <div>
        <span style='color:#2ECC71; font-weight:bold;'>🛡️ 留任</span>
        <span style='color:#888;'> — 上月在榜，信念值 ≥ 退出门槛（{exit_th:.0f}），原地守擂</span>
      </div>
      <div>
        <span style='color:#3498DB; font-weight:bold;'>🆕 新晋</span>
        <span style='color:#888;'> — 席位有空缺，信念值 ≥ 入选门槛（{entry:.0f}），正式达标入选</span>
      </div>
      <div>
        <span style='color:#F39C12; font-weight:bold;'>⚔️ 挑战</span>
        <span style='color:#888;'> — 席位满员，信念值比最弱在位者高出 {margin:.0f} 以上，强制替换上位</span>
      </div>
      <div>
        <span style='color:#9B59B6; font-weight:bold;'>🔰 新兵</span>
        <span style='color:#888;'> — 候选池不足（达标者 &lt; 空位数），从所有有信念积分的标的里择优兜底补位；
        信念值积累过 {exit_th:.0f} 后才会转为留任状态</span>
      </div>
    </div>
    </div>
    """


def conviction_bar_html(conviction: float, max_val: float = 100.0,
                        status: str = "") -> str:
    """生成单个标的的信念值进度条 HTML。"""
    pct   = min(conviction / max(max_val, 1.0) * 100, 100)
    label, color = get_status_label(status)
    return (
        f"<div style='display:flex; align-items:center; gap:8px; margin:4px 0;'>"
        f"<div style='flex:1; background:#1e1e1e; border-radius:4px; height:10px; position:relative;'>"
        f"<div style='width:{pct:.0f}%; background:{color}; border-radius:4px; height:10px;'></div>"
        f"</div>"
        f"<span style='font-size:14px; font-weight:bold; color:{color}; min-width:40px;'>"
        f"{conviction:.0f}</span>"
        f"<span style='font-size:13px; color:{color};'>{label}</span>"
        f"</div>"
    )


def decisions_html(decisions: list[dict]) -> str:
    """生成本月决策日志的 HTML。"""
    if not decisions:
        return ""
    rows = ""
    for d in decisions:
        _, color = get_status_label(d["action"])
        icon = {"defending": "🛡️", "new_entry": "🆕", "challenged": "⚔️",
                "cold_start": "🔰", "dropped": "📉"}.get(d["action"], "•")
        rows += (
            f"<div style='font-size:13px; color:#bbb; padding:3px 0; "
            f"border-bottom:1px solid #1a1a1a;'>"
            f"{icon} <b style='color:{color};'>{d['ticker']}</b> — "
            f"{d['detail']}"
            f"</div>"
        )
    return (
        f"<div style='background:#111; border-radius:6px; padding:10px; "
        f"margin-top:8px;'>"
        f"<div style='font-size:14px; font-weight:bold; color:#aaa; "
        f"margin-bottom:6px;'>本月守擂决策日志</div>"
        f"{rows}</div>"
    )
