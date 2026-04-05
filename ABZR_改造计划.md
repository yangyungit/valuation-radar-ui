# AB 改造 + Z 组新增 — 可执行计划

> **背景**：基于 AB 组历史回测的表现分析，确认以下改动。锚点归一化和并行独立评估已完成，本计划聚焦尚未落地的增量改动。
>
> **执行方式**：在新的聊天窗口中按 Task 顺序逐项执行。每个 Task 自包含，标注了精确的文件路径、函数名和代码模式。

---

## Task 1: Z 组「现金流堡垒」— Page 3 新增赛道

### 1.1 设计概要

Z 组是一个**收息停泊区**，不同于 A 组（避风港，重对冲性）。Z 组的核心诉求：**拿得到真实现金流**。

| 维度 | A 组（避风港） | Z 组（现金流堡垒） |
|------|-------------|-----------------|
| 核心目标 | 低回撤 + 低相关性 | **高股息 + 稳定现金流** |
| GLD 能入选？ | 能（零股息但低相关性强） | **不能**（零股息不达门槛） |
| 典型选手 | GLD, DUK, XLP | SCHD, VYM, MO, SO, BIL, TLT |
| 在仓位配置中的角色 | 核心底仓 | **宏观制动器的避风港 + 主动选择的收息仓** |

### 1.2 评分卡：`compute_scorecard_z()`

**ScorecardZ — 现金流堡垒指数（满分 100 分）**

```
Score_Z = (40 × DivYield) + (25 × EPS_Stability)
        + (20 × InvVol) + (15 × InvMaxDD)
```

| 因子 | 权重 | 锚点 Key | 锚点值 | 含义 |
|------|:---:|---------|-------|------|
| 股息率 | **40%** | `div_yield` | (0.0, 8.0) | Z 组扩大上限到 8%（覆盖 REITs、高息股） |
| 盈利稳定性 | **25%** | `eps_stability` | (0.5, 10.0)（复用 B 组） | 分红的可持续性代理 |
| 低波动 | **20%** | `vol_inv` | (0.40, 0.08)（复用 A 组） | 收息仓不想坐过山车 |
| 抗跌韧性 | **15%** | `max_dd_inv` | (-0.25, -0.03)（复用 A 组） | 保护本金 |

**入选门槛**：`div_yield >= 1.0%`（硬过滤，零股息资产不参赛）

### 1.3 改动文件清单

#### (a) `pages/3_资产细筛.py`

**1. `CLASS_META` 增加 Z 组**（约 L52-77）

```python
"Z": {
    "label": "Z级：现金流堡垒",
    "icon": "🏦",
    "color": "#1ABC9C",
    "bg": "#0d2b25",
},
```

**2. `ARENA_CONFIG` 增加 Z 组**（约 L83-159）

```python
"Z": {
    "score_name": "现金流堡垒指数",
    "weights": {"div_yield": 0.40, "eps_stability": 0.25, "vol_inv": 0.20, "max_dd_inv": 0.15},
    "invert_z": False,
    "factor_labels": {
        "div_yield":     "现金奶牛 (真实股息率)",
        "eps_stability": "分红续航力 (盈利稳定性)",
        "vol_inv":       "绝对低波 (年化波动率倒数)",
        "max_dd_inv":    "本金盾 (最大回撤倒数)",
    },
    "logic": (
        "Z 组「现金流堡垒」使命：筛选能持续提供真实现金流收入的资产。<br>"
        "① 真实股息率（年化股息率，权重 40%）— 拿到手的钱最重要<br>"
        "② 分红续航力（盈利稳定性代理，权重 25%）— 确保分红可持续<br>"
        "③ 绝对低波（年化波动率倒数，权重 20%）— 收息仓不坐过山车<br>"
        "④ 本金盾（最大回撤倒数，权重 15%）— 保护本金安全<br>"
        "入选门槛：股息率 ≥ 1%。零股息资产（如 GLD）不参赛。"
    ),
},
```

**3. `FACTOR_ANCHORS` 增加 Z 组专用锚点**（约 L513-527）

```python
"div_yield_z": (0.0, 8.0),   # Z 组股息率上限扩至 8%（覆盖 REITs/高息 ETF）
```

> 注：其他三个因子复用已有锚点 `eps_stability`, `vol_inv`, `max_dd_inv`。

**4. 新增 `compute_scorecard_z()` 函数**（在 `compute_scorecard_b()` 后面，约 L788）

仿照 `compute_scorecard_a()` 的代码模式，关键差异：
- 入选门槛：`div_raw >= 1.0` 硬过滤，不满足的行直接丢弃
- 股息率锚点用 `div_yield_z` (0.0, 8.0) 而非 `div_yield` (0.0, 5.0)
- 权重：40% / 25% / 20% / 15%

```python
def compute_scorecard_z(df: pd.DataFrame) -> pd.DataFrame:
    """
    ScorecardZ -- Z 组「现金流堡垒指数」评分体系 (满分 100 分)

    Score_Z = (40 x DivYield) + (25 x EPS_Stability)
            + (20 x InvVol) + (15 x InvMaxDD)

    入选门槛：股息率 >= 1.0%，零股息资产不参赛。
    """
    if df.empty:
        return df

    result = df.copy()

    # 硬过滤：股息率 >= 1%
    div_raw = result.get("股息率", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    result = result[div_raw >= 1.0].copy()
    if result.empty:
        return result

    div_raw = result["股息率"].astype(float).fillna(0.0)
    f1_norm = _anchor_norm(div_raw, *FACTOR_ANCHORS["div_yield_z"])

    eps_stab_raw = result.get("EPS稳定性", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f2_norm = _anchor_norm(eps_stab_raw, *FACTOR_ANCHORS["eps_stability"])

    vol_raw = result.get("年化波动率", pd.Series(0.3, index=result.index)).astype(float).fillna(0.3)
    f3_norm = _anchor_norm(-vol_raw, *FACTOR_ANCHORS["vol_inv"])

    dd_raw = result.get("最大回撤_raw", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f4_norm = _anchor_norm(-dd_raw.abs(), *FACTOR_ANCHORS["max_dd_inv"])

    result["因子1_分"] = (0.40 * f1_norm).round(1)
    result["因子2_分"] = (0.25 * f2_norm).round(1)
    result["因子3_分"] = (0.20 * f3_norm).round(1)
    result["因子4_分"] = (0.15 * f4_norm).round(1)

    result["竞技得分"] = (
        result["因子1_分"] + result["因子2_分"] + result["因子3_分"] + result["因子4_分"]
    ).round(1)

    result = result.sort_values("竞技得分", ascending=False).reset_index(drop=True)
    result["排名"] = range(1, len(result) + 1)
    return result
```

**5. Z 组因子数据获取**

Z 组需要的因子（股息率、EPS 稳定性、年化波动率、最大回撤）与 A 组 + B 组的因子**完全重叠**。因此：

- **不需要新建 `get_arena_z_factors()`**
- 在 Z 组 UI 逻辑中，合并调用 `get_arena_a_factors()` 和 `get_arena_b_factors()` 的结果即可
- A 组提供：div_yield, max_dd_252, spy_corr, ann_vol
- B 组提供：eps_stability
- 合并两者的字段填入 Z 组 DataFrame

**6. UI 改造：4 列 → 5 列**

当前赛道选择用 `st.columns(4)` + 循环 `["A", "B", "C", "D"]`。需要改为 `st.columns(5)` + `["A", "B", "Z", "C", "D"]`。

涉及位置：
- L1844: `overview_cols = st.columns(4)` → `st.columns(5)`
- L1845: `for i, cls in enumerate(["A", "B", "C", "D"])` → `["A", "B", "Z", "C", "D"]`
- L1813-1841: CSS `_ABCD4` 选择器中 `:has(> div:nth-child(4)):not(:has(> div:nth-child(5)))` 需要更新为 `:has(> div:nth-child(5)):not(:has(> div:nth-child(6)))`，hover 循环从 `range(1,5)` → `range(1,6)`

**7. Z 组 Tab 渲染逻辑**

在 L2150 `elif _sel4 == "D":` 之前，新增 `elif _sel4 == "Z":` 分支。代码模式仿照 B 组（L1892-2016），因为 Z 组和 B 组因子来源相似：
- 拉取 A 组因子（股息率、最大回撤、波动率）+ B 组因子（EPS 稳定性）
- 合并到 df_z DataFrame
- 调用 `compute_scorecard_z()`
- 写入 `p4_arena_leaders["Z"]` 和 `arena_winners["Z"]` 和 `_record_arena_history("Z", ...)`
- 颁奖台和排行榜可复用 `_render_arena_tab()` 通用函数

**8. 历史回填适配**

`_backfill_arena_history()` 中的赛道循环（搜索 `for cls in ["A", "B", "C", "D"]`）需要加入 `"Z"`。

**9. 历史榜单展示**

L2284-2290 的历史榜单区域，已通过 `_sel4` 变量动态读取 `CLASS_META[_sel4]`，Z 组加入 `CLASS_META` 后应自动适配。但需确认 `_compute_streaks` 和 `_streak_badge_html` 是否也用到硬编码的 `["A","B","C","D"]`。

**10. `screener_engine.py` 的 `classify_asset_parallel()` 适配**

搜索 `classify_asset_parallel` 函数，增加 Z 组的独立评估逻辑：
- Z 组入选条件：`div_yield >= 1.0%`（唯一条件，不需要滞后带，因为股息率本身是慢变量）
- 在 qualifying_grades 中加入 "Z"
- `_primary_grade()` 优先级：A > B > Z > C > D

---

## Task 2: B 组评分卡增加 Revenue 增速因子

### 2.1 设计

| 因子 | 当前权重 | 新权重 |
|------|:---:|:---:|
| 真·护城河质量（股息率 + EPS 稳定性） | 40% | **35%** |
| 抗跌韧性（MaxDD 倒数） | 30% | **25%** |
| 长效性价比（Sharpe 1Y） | 20% | **20%** |
| 绝对体量（log 市值） | 10% | **10%** |
| **Revenue 增速（新增）** | — | **10%** |

### 2.2 改动文件清单

#### (a) `FACTOR_ANCHORS` 新增锚点（`pages/3_资产细筛.py` L513-527）

```python
"revenue_growth": (-5.0, 25.0),   # 收入增速 %：负增长到 25% 覆盖大部分大猩猩
```

#### (b) `ARENA_CONFIG["B"]` 更新权重和因子标签（L103-121）

```python
"B": {
    "score_name": "核心底仓质量指数",
    "weights": {"real_quality": 0.35, "resilience": 0.25, "sharpe_1y": 0.20, "mcap_premium": 0.10, "revenue_growth": 0.10},
    "invert_z": False,
    "factor_labels": {
        "real_quality":    "真·护城河质量 (股息率+盈利稳定性)",
        "resilience":      "抗跌韧性 (近1年最大回撤倒数)",
        "sharpe_1y":       "长效性价比 (近1年夏普比率)",
        "mcap_premium":    "绝对体量 (log10市值壁垒)",
        "revenue_growth":  "成长弹性 (Revenue 增速)",
    },
    "logic": (
        "核心底仓质量指数：兼顾防御与成长弹性，追求极低换手率与极强抗跌性。<br>"
        "① 真·护城河质量（股息率 + 盈利稳定性双因子代理，权重 35%）<br>"
        "② 抗跌韧性（近 1 年最大回撤越小得分越高，权重 25%）<br>"
        "③ 长效性价比（近 1 年夏普比率，长期风险调整收益，权重 20%）<br>"
        "④ 绝对体量（log10 市值壁垒，大象起舞加分，权重 10%）<br>"
        "⑤ 成长弹性（Revenue 增速，避免纯防御型占位，权重 10%）<br>"
        "高分者兼具护城河深度与成长宽度。"
    ),
},
```

#### (c) `compute_scorecard_b()` 增加第 5 因子（L744-787）

在现有 4 因子之后增加：

```python
# ── 因子 5: Revenue 增速 (10%, new)
rev_raw = result.get("Revenue增速", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
f5_norm = _anchor_norm(rev_raw, *FACTOR_ANCHORS["revenue_growth"])

result["因子1_分"] = (0.35 * f1_norm).round(1)   # was 0.40
result["因子2_分"] = (0.25 * f2_norm).round(1)   # was 0.30
result["因子3_分"] = (0.20 * f3_norm).round(1)   # unchanged
result["因子4_分"] = (0.10 * f4_norm).round(1)   # unchanged
result["因子5_分"] = (0.10 * f5_norm).round(1)   # NEW

result["竞技得分"] = (
    result["因子1_分"] + result["因子2_分"] + result["因子3_分"]
    + result["因子4_分"] + result["因子5_分"]
).round(1)
```

#### (d) `api_client.py` — `get_arena_b_factors()` 增加 Revenue 增速字段（L182-238）

在 `_fetch_one(t)` 函数中增加：

```python
# Revenue Growth: TTM vs prior year
try:
    fin = stock.financials  # or stock.quarterly_financials
    if fin is not None and "Total Revenue" in fin.index and fin.shape[1] >= 2:
        rev_curr = fin.loc["Total Revenue"].iloc[0]
        rev_prev = fin.loc["Total Revenue"].iloc[1]
        rev_growth = ((rev_curr - rev_prev) / abs(rev_prev) * 100) if rev_prev != 0 else 0.0
    else:
        rev_growth = 0.0
except Exception:
    rev_growth = 0.0
```

并在返回的 dict 中增加 `"revenue_growth": rev_growth`。

#### (e) B 组 UI 中填充 Revenue 增速列

在 B 组 Tab 渲染逻辑（L1892-2016）中，从 B 组因子数据中读取 `revenue_growth` 并填入 `df_b["Revenue增速"]` 列，使其可被 `compute_scorecard_b()` 消费。

#### (f) B 组颁奖台/排行榜适配

`_render_podium_b()` 和 `_render_leaderboard_b()` 需增加第 5 因子的展示（搜索现有 4 因子列，仿照增加第 5 列）。

---

## Task 3: B 组宏观制动器 — Page 6

### 3.1 设计

在 Page 6 步骤 1 宏观剧本门控（L125-149）后面，增加 B 组的仓位制动逻辑：

```python
# ── 新增：B 组宏观制动器 ──────────────────────────────────────────
B_REGIME_THROTTLE = {
    "Soft": 1.0,    # 软着陆：B 组满仓
    "Hot":  0.75,    # 过热：B 组 75%
    "Stag": 0.50,    # 滞胀：B 组 50%，剩余泊入 Z 组
    "Rec":  0.0,     # 衰退：B 组清仓，全部泊入 Z 组
}
b_throttle = B_REGIME_THROTTLE.get(live_regime_label, 0.75)
```

### 3.2 改动位置

#### (a) 核心池配置（L341-387）

当前逻辑：A 组固定 25%，B 组固定 25%。

改为：
```python
for tier, base_pct, label in [("A", 25.0, "压舱石"), ("B", 25.0, "大猩猩")]:
    # B 组应用宏观制动器
    if tier == "B":
        actual_pct = base_pct * b_throttle
        z_park_pct = base_pct - actual_pct  # 减出的部分泊入 Z 组
    else:
        actual_pct = base_pct
        z_park_pct = 0.0

    # ... 原有选股逻辑用 actual_pct 替代 total_pct ...

    # 如果有 Z 组停泊部分
    if z_park_pct > 0:
        z_picks = st.session_state.get("arena_winners", {}).get("Z", [])[:2]
        if z_picks:
            for zt in z_picks:
                portfolio.append({
                    "配置层": "核心底仓 Core", "所属阵型": "Z",
                    "代码": zt,
                    "名称": TIC_MAP.get(zt, zt),
                    "Molt评分": 0.0,
                    "分配仓位": round(z_park_pct / len(z_picks), 2),
                    "白盒归因": f"B组宏观制动({live_regime_label})减仓 → Z组收息停泊",
                    "所属板块": SECTOR_MAP.get(zt, "—"),
                })
        else:
            portfolio.append({
                "配置层": "核心底仓 Core", "所属阵型": "Z", "代码": "BIL",
                "名称": "极短债/现金等价物", "Molt评分": 0.0,
                "分配仓位": round(z_park_pct, 2),
                "白盒归因": f"B组宏观制动({live_regime_label})减仓 → 泊入 BIL",
                "所属板块": "现金",
            })
```

#### (b) 步骤 1 日志表增加制动器信息

在 `step1_logs` 中增加一行展示 B 组制动器状态：

```python
step1_logs.append({
    "项目": "B组宏观制动器",
    "状态": f"{'✅ 满仓' if b_throttle >= 1.0 else f'⚠️ {b_throttle*100:.0f}%'}",
    "说明": f"当前剧本 {live_regime_label}，B组仓位比例 {b_throttle*100:.0f}%，"
            f"减仓 {(1-b_throttle)*25:.0f}% 泊入 Z 组",
})
```

#### (c) 手动底仓选股 UI 适配

L528 区域的手动底仓选股（A/B multiselect）下方，增加 Z 组的展示信息：
- 显示当前 Z 组冠军列表（来自 `arena_winners["Z"]`）
- 显示制动器导致的 Z 组泊入金额

#### (d) 步骤 2 说明文字更新

L526 的 `st.caption()` 中，更新配置描述，加入 Z 组停泊机制说明。

---

## 执行顺序建议

```
Task 1 (Z 组) ──→ Task 3 (宏观制动器 + Z 组停泊)
                        ↑
Task 2 (B 组 Revenue) ─┘  （Task 2 独立于 Task 1，可并行）
```

**推荐顺序**：

1. **先做 Task 2**（B 组 Revenue 增速）— 改动最小，独立可测
2. **再做 Task 1**（Z 组新增赛道）— 改动量最大，但自包含
3. **最后做 Task 3**（宏观制动器）— 依赖 Task 1 的 Z 组 `arena_winners["Z"]`

---

## 不在本轮范围内

| 项目 | 状态 | 原因 |
|------|------|------|
| 渐进仓位（1月33%→2月66%→3月+100%）| **暂缓** | 主理人需进一步思考延误军情的权衡 |
| 宽进严出退出机制 | **暂缓** | 同上 |
| A 组评分卡股息权重调整 | **不做** | 引入 Z 组后 A 组保持原定位（对冲避风港） |
