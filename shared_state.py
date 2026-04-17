"""跨页面共享状态常量（Single-Source Keys）

本模块遵循 DATA_CONSISTENCY_PROTOCOL 约束 4「跨层契约显式化」：
所有跨页面共享的 `st.session_state` key 必须集中定义在此，禁止在各 page 里
散落字符串字面量。未来重命名只需改此处。

详见 `../valuation-radar/DATA_CONSISTENCY_PROTOCOL.md` 第 4 条。
"""

from __future__ import annotations


class SharedKeys:
    """跨页面共享的 st.session_state key 常量。

    命名规则：大写 + 下划线；字符串值保持与历史代码一致，保证兼容。
    新增 key 前先确认是否真的跨页面；单页面状态保留字面量即可。
    """

    # ── Arena 守擂缓冲区（Page 4 ↔ Page 5 双向同步） ──
    ARENA_BUFFER_N = "arena_buffer_n"            # 当前生效的 Top-N
    CONFIRMED_BUFFER_N = "confirmed_buffer_n"    # Page 4 点「确认」后的值
    P5_BUFFER_SYNCED = "_p5_buffer_synced"       # Page 5 同步方向哨兵

    # ── A 组合成权重模式（Page 4 → Page 5） ──
    A_WEIGHT_MODE = "a_weight_mode"              # "equal" / "belief"

    # ── Arena 竞选结果（Page 3 → Page 4/5/6） ──
    P4_ARENA_LEADERS = "p4_arena_leaders"        # 当期各赛道 Top-3 详细记录
    ARENA_WINNERS = "arena_winners"              # 当期各赛道 Top-3 ticker 列表
    ABCD_CLASSIFIED_ASSETS = "abcd_classified_assets"  # 当期 ABCD 分类结果

    # ── 宏观剧本（Page 1 → Page 0/4/6） ──
    CURRENT_MACRO_REGIME = "current_macro_regime"
    CURRENT_MACRO_REGIME_RAW = "current_macro_regime_raw"
    SMOOTHED_REGIME_PROBS = "smoothed_regime_probs"
    LIVE_REGIME_LABEL = "live_regime_label"
    HORSEMEN_MONTHLY_PROBS = "horsemen_monthly_probs"


SHARED_DEFAULTS: dict = {
    SharedKeys.ARENA_BUFFER_N: 3,
    SharedKeys.CONFIRMED_BUFFER_N: 3,
    SharedKeys.A_WEIGHT_MODE: "equal",
}


def get_shared(key: str, fallback=None):
    """从 st.session_state 取跨页面共享状态，带默认值兜底。

    用法：
        from shared_state import SharedKeys, get_shared
        n = get_shared(SharedKeys.ARENA_BUFFER_N, 3)
    """
    import streamlit as st
    if key in SHARED_DEFAULTS and fallback is None:
        fallback = SHARED_DEFAULTS[key]
    return st.session_state.get(key, fallback)
