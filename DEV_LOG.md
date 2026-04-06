# DEV LOG — valuation-radar-ui

---

## 2026-04-06 | B 组改进实验失败 → 全量回滚

### 背景

在「B 组宏观适配评分重构」完成后，进一步尝试通过三个叠加方案优化 B 组历史持仓质量（见 `B组改进.md`）。实验后发现综合效果**适得其反**——红色亏损标的数量增多，整体结果劣于改动前，紧急执行全量回滚。

### 失败实验内容（已全部撤销）

三个方案同时上线，方向完全一致（全部「加进攻、减防御」），叠加后产生连锁负效应：

**方案 1：F1 RealQuality 去掉股息率，改为纯 EPS 稳定性**
- 理论：去掉 `div_norm` 回填噪音，Quality 信号区分度翻倍
- 实际：EPS 单因子离散度更大 → 月间分数波动加剧 → 信念值更不稳定 → 换手增加

**方案 2：信念衰减加速 + exit_threshold 35 → 39**
- 理论：在位者因子分 < 35 时触发 0.70 加速衰减，加速淘汰持续走弱标的
- 实际：门槛提高 + 衰减加速双重收紧 → 更多标的被提前踢出 → 更多短 stint → 更多来不及涨就被止损的闪现亏损

**方案 3：RS120d 权重 15% → 22%，Resilience 权重 20% → 13%**
- 理论：进攻期趋势信号加码，弥补 B 组在牛市的结构性落后
- 实际：动量权重暴增 47%、防御权重暴降 35%。B 组定位是"核心底仓"，追涨杀跌正好是反面——动量反转期（如 PLTR 高位回落）高 RS120d 权重把其选入，加速衰减机制又让它亏着被踢出

**同时修改的周边文件：**
- `api_client.py`：`get_stock_metadata()` 新增并发拉取 `revenue_growth` 和 `log_mcap`，回填时替代硬编码 9.0
- `data/arena_history.json`：按新权重重新回填，产生了质量更差的历史记录

### 根因分析

三个方案在 `B组改进.md` 中提出时各自都有局部合理性，但同时实施产生的核心问题是：**B 组的定位是"稳健核心底仓"，三个改动全部朝"增加进攻性"方向推进**，等于把防御型底仓改造成了追涨杀跌的动量策略，与设计初衷完全相反。

### 回滚操作

```
git checkout HEAD -- conviction_engine.py pages/3_资产细筛.py api_client.py
git checkout HEAD -- data/arena_history.json data/horsemen_monthly_verdict.json data/prev_classification.json
```

所有代码和数据文件均已恢复至改动前状态（即「B 组宏观适配评分重构」完成后的版本）。

### 经验教训与后续优化方向

- [ ] **一次只改一个变量**：下次迭代需严格单因素测试，每次改动后独立回填 + 跑 `pytest test_b_quality.py -v -s` 对比数据再决定是否保留
- [ ] **RS120d 权重调整上限**：B 组底仓定位决定了 RS120d 顶多从 15% → 17%，22% 是明显过激的
- [ ] **方案 2（加速衰减）可以单独尝试**：exit_threshold 不变（保持 35），只加 score<35 触发 0.70 加速衰减的逻辑，效果可能是正向的
- [ ] **方案 1（去掉股息率）需配合更多测试**：如果 div_norm 回填噪音确实是问题，可先在非回填模式下验证 EPS 单因子的分数稳定性，再决定是否改 F1

---

## 2026-04-06 | B 组宏观适配评分重构 — 四档动态权重 + Macro Alignment

### 背景

B 赛道持仓碎片化严重：Page 5 盈利统计显示 33% 闪现率（<3月）、26% 空仓月、平均持仓仅 5.4 月。根因诊断发现 RS120d（120 日中期动量，15% 权重）是 B 组 6 因子中**唯一高波动因子**，月间波动 5-15 分，导致信念值在 40 门槛附近反复穿越。

关键观察：现有架构**已预留**宏观剧本接口但 B 组从未连线 —— 侧边栏标注"平滑剧本供 B/C 组使用"，回填循环中已按月推导 `bc_regime` 并传给 C 组，唯独 `compute_scorecard_b()` 从未接收 `macro_regime` 参数。

更深层洞察：2022-05 宏观剧本从 Hot(再通胀) 切换至 Stag(滞胀) 后，BRK-B、CVX 等标的的 RS120d 逐月恶化，信念被慢性侵蚀直至跌穿门槛。**问题不是剧本切换导致即时换手（信念制已吸收冲击），而是 RS120d 滞后反映新宏观环境 → 分数渐进下滑 → 信念缓慢穿越门槛**。

### 设计方案：七因子动态权重 + Macro Alignment

核心思路：不同宏观剧本下，"好的压舱石"的定义不同。进攻期保留 RS120d 作为辅助，防御期归零转向纯质量筛选。新增 MacroAlignment 因子（与 C 组同源）作为第 7 因子常驻 10%。

四档权重表 (`B_REGIME_WEIGHTS`):

| 因子 | Soft (复苏) | Hot (过热) | Stag (滞胀) | Rec (衰退) |
|------|:-----------:|:---------:|:-----------:|:---------:|
| F1 RealQuality (股息+EPS稳定性) | 20% | 20% | **25%** | **30%** |
| F2 Resilience (MaxDD逆) | 20% | 15% | **25%** | **25%** |
| F3 Sharpe1Y | 20% | 20% | 20% | 20% |
| F4 RS120d | **10%** | **10%** | **0%** | **0%** |
| F5 MCapPremium | 10% | 10% | 10% | 10% |
| F6 RevenueGrowth | 10% | **15%** | 10% | 5% |
| F7 MacroAlignment (NEW) | 10% | 10% | 10% | 10% |

设计逻辑：
- **Stag/Rec（防御期）**：RS120d 归零，Quality + Resilience 加码 — 消灭动量噪声导致的碎片化
- **Soft/Hot（进攻期）**：RS120d 降至 10%（原 15%）— 动量仍可辅助选优，但权重降低以减少波动
- **Hot 特化**：Revenue 提至 15% — 过热期成长性受追捧
- **Rec 特化**：Quality 提至 30% — 衰退期现金流和股息最重要，Revenue 降至 5%
- **MacroAlignment 常驻 10%**：标的在 `_MACRO_TAGS_MAP[regime]` 中得 100 分，否则 0 分

### 改动

**`pages/3_资产细筛.py`**

- **新增 `B_REGIME_WEIGHTS` 常量**：四档权重元组 `(w_q, w_r, w_s, w_rs, w_m, w_rev, w_macro)`
- **`compute_scorecard_b(df)` → `compute_scorecard_b(df, macro_regime="Soft")`**：
  - 新增第 7 因子 MacroAlignment（复用 `_MACRO_TAGS_MAP`，与 C 组 line 782 同源逻辑）
  - 按 `B_REGIME_WEIGHTS[macro_regime]` 查表取权重替代硬编码
  - 更新 docstring 为 7 因子架构说明
- **回填调用**（line ~576）：`compute_scorecard_b(df_cls, bc_regime)` — 终于连线！
- **Pre-arena 调用**（line ~2050）：`compute_scorecard_b(_df_pre_b, macro_regime)`
- **实时调用**（line ~2207）：`compute_scorecard_b(df_b, macro_regime)`
- **`_B_FACTOR_COLORS`**：追加第 7 色 `#1ABC9C`
- **`_render_podium_b` / `_render_leaderboard_b`**：因子循环从 `range(1,7)` 改为 `range(1,8)`
- **冠军解读文案**：增加宏观适配因子说明、当前剧本档位显示、RS120d 权重百分比

**`test_b_quality.py`**
- 头部文档"可调旋钮一览"新增 `B_REGIME_WEIGHTS` 条目

### 遗留与未来优化方向
- [ ] 改动需重新「回填历史数据」（60 个月），生成新的 `arena_history.json` 后跑 `pytest test_b_quality.py -v -s` 验证效果
- [ ] `_MACRO_TAGS_MAP` 在回填模式中使用的是当前映射（非历史快照），对大多数大盘蓝筹适用但不完美
- [ ] 若 Stag/Rec 期间 MacroAlignment 的 binary 0/100 过于激进，可考虑引入 graded scoring（如按 regime 概率加权）

---

## 2026-04-06 | B 组信念引擎 — 在位者惯性衰减层 (Holder Decay Bonus)

### 背景
B 组评分引入 RS120d（120 日相对强度，权重 15%）后，捕捉机会成本的能力提升了，但持仓周期显著碎片化。**表现为：** 榜单（候选池）稳定，但 Top 3 名单反复进出，闪现 stint 增加。之前没有 RS120d 时持仓周期很长，但错过了一些显著机会成本更好的标的。

### 根因分析

B 组 6 因子的月间波动特性差异巨大：

| 因子 | 权重 | 月间波动 |
|------|------|---------|
| RealQuality（股息率+EPS稳定性） | 25% | 极低 |
| Resilience（最大回撤倒数） | 20% | 低 |
| Sharpe1Y | 20% | 中等 |
| **RS120d（中期动量）** | **15%** | **高** |
| MCapPremium | 10% | 极低 |
| RevenueGrowth | 10% | 低 |

RS120d 是唯一高波动因子。120 天窗口每月滑动，相对强度月间波动 ±5~10 百分点，映射到 ±5~10 的归一化分。15% 的权重足以在质量相近的底仓标的间反复扰动排名。

关键点：`update_convictions()` 对所有标的使用统一的 `decay_rate = 0.75`，不区分在位者和挑战者 —— RS120d 的月间噪声被无差别传导到信念值上。

### 改动

**`conviction_engine.py`**
- **新增 `holder_decay_rate` 参数**：`CONVICTION_B_CONFIG` 新增 `holder_decay_rate = 0.78`，在位者使用慢衰减。
- **`update_convictions()` 签名变更**：新增 `current_holders: list[str] | None = None` 参数。在位者使用 `holder_decay_rate`，非在位者使用标准 `decay_rate`。
  ```
  挑战者: C(t) = C(t-1) × 0.75 + Score × 0.25  （稳态 = Score × 1.0）
  在位者: C(t) = C(t-1) × 0.78 + Score × 0.25  （稳态 = Score × 1.136）
  ```
- **模块文档更新**：架构说明从两层（积累 + 守擂）升级为三层（积累 + 在位者惯性 + 守擂）。
- **`explain_config_html()` 更新**：白盒面板新增「② 在位者惯性层」说明，展示双衰减公式与稳态对比。

**`pages/3_资产细筛.py`**
- **回填调用**（line ~595）：`_conv_update(_bf_conv_state, _bf_factor_scores, current_holders=_bf_conv_holders)`
- **实时调用**（line ~2195）：`_conv_update(_rt_conv_state, _rt_factor_scores, current_holders=_rt_conv_holders)`

**`test_b_quality.py`**
- 架构描述更新，可调旋钮表中碎片化/高换手修复方向更新为 `holder_decay_rate`。

### ⚠️ 关键校准陷阱 —— holder_decay_rate 不可高于 0.786

初始设计 `holder_decay_rate = 0.82`，但与之前「加快衰减让走弱标的更快退出」（`decay_rate` 降到 0.75）的设计意图冲突：

| 情景 | 因子得分 | 标准 0.75 稳态 | 0.82 稳态 | 退出线 35 | 结论 |
|------|---------|---------------|-----------|----------|------|
| 真走弱 | 30 | 30.0 → 淘汰 | **41.7 → 赖着不走** | 35 | ❌ 冲突 |

**约束推导**：`steady_state = Score × accum / (1 - holder_decay) < exit_threshold`
当 Score = 30（真走弱）：`30 × 0.25 / (1 - d) < 35` → `d < 0.786`

最终校准 `holder_decay_rate = 0.78`：

| 情景 | 因子得分 | 标准 0.75 稳态 | 0.78 稳态 | 退出线 | 结论 |
|------|---------|---------------|-----------|--------|------|
| 真走弱 | 30 | 30.0 → 淘汰 | 34.1 → 淘汰 | 35 | ✅ |
| 中度衰退 | 35 | 35.0 → 边界 | 39.8 → 缓冲 | 35 | ✅ 多一点容错 |
| 动量噪声 | 45 | 45.0 → 安全 | 51.1 → 稳固 | 35 | ✅ 不会被误杀 |

**记住：`holder_decay_rate` 的硬上限是 `1 - (min_exit_score × accum / exit_threshold)`。调 `exit_threshold` 或 `accumulate_rate` 时必须同步检查此约束。**

### 遗留与未来优化方向
- [ ] 改动需重新「回填历史数据」（Streamlit 页面按钮），生成新的 `arena_history.json` 后跑 `pytest test_b_quality.py -v -s` 验证效果
- [ ] 若 0.78 仍碎片化，可小幅上调至 0.785（接近硬上限）；若持仓过粘错过机会，下调至 0.76
- [ ] 长期考虑：如果 B 组引入更多高波动因子，可能需要将 holder inertia 从参数化（全局 holder_decay_rate）升级为因子级别的差异化衰减（对慢因子和快因子分别设 decay），但当前单参数已足够

---

## 2026-02-28 | Page 1 宏观定调 — 全页统一度量衡重构 (3Y Z-Score 单一尺度)

### 背景
用户指出：① 防抖状态机（Anti-Whipsaw）的平滑效果与"刷新页面次数"绑定，违反客观性；② 债市阶梯和聪明钱因子使用 20 日涨跌幅，与宏观时钟（3Y Z-Score）尺度不统一。

### 改动
**`pages/1_宏观定调.py`**
- **移除防抖状态机**：删除 EMA 平滑逻辑和 Anti-Whipsaw 面板。宏观剧本直接由 4 个剧本证据链得分最高者确定，无 session 记忆。`fetch_macro_scores` API 调用同步移除，`api_clock_regime` 改为本地由 `_quad_a` 推导。
- **全页统一度量衡**：新增 `_ratio_z_curr(a, b)` 全局 3Y Z-Score 助手函数。
- **宏观底色 4 指标卡**：`TLT/SHY`、`HYG/IEF`、`TIP/IEF`、`UUP/SHY` 全部改为 3Y Z-Score，显示单位从 `%` 改为 `σ`。
- **债市阶梯**：`r_tlt/r_ief/r_shy` 换为 `_ratio_z_curr`，曲线形态判断阈值改为 ±0.3σ，图表 x 轴换为 Z-Score（range_color [-2,2]）。
- **聪明钱因子**：全部 8 个因子 ETF 改为对 SPY 的 3Y Z-Score（衡量历史性超额），图表 range_color [-2,2]，战术分组均值标签从 `%` 改为 `σ`，`_spy_vs_iwm` 改为 `_ratio_z_curr('SPY','IWM')`。

---

## 2026-02-28 | Page 1 宏观定调 — 参数降维与语义白盒化重构

### 背景
市场基于 1-3 年的信用周期定价，过长的时间窗口会导致 Z-Score 锚点失真。原有的 Z-Score 称呼易引发歧义（误认为宏观绝对值），且 UI 布局上的“白盒溯源”和“历史输出表”位置不利于顺畅的视觉推演。

### 改动
**`pages/1_宏观定调.py`**
- **计算窗口参数降维**: 
  - 彻底废弃 `战略之眼 (10Y/2500日)`，降维为 `中期战略视角 (3Y/750日)`。
  - 彻底废弃 `战术之眼 (3Y/750日)`，降维为 `短期战术视角 (1Y/250日)`。
  - 同步修改底层 `z_window` 和 `get_z_a_trajectory` 的 `rolling(window)` 参数，确保新定义严丝合缝。
- **语义重构与正名**:
  - 全局将 "Growth_Z" / "Inflation_Z" / "Z-Score" 表述改为 "经济预期边际差 (Growth Expectation Momentum)" 和 "通胀预期边际差 (Inflation Expectation Momentum)"。
  - 在美林时钟旁白区新增白盒化解释注记，明确 Z-Score 测量的是“预期的边际变化率”。
- **UI 布局重组与历史表格式化**:
  - 将 "白盒溯源" (Expander) 移至 "象限裁决横幅" (过热/再通胀) 正下方。
  - 提取 "宏观剧本演变历史输出表"，紧接置于动态旁白与美林时钟板块正下方，符合逻辑推演链。
  - 历史审计表输出以汉字结果为主（`现任剧本(状态机)` 与 `原始最强剧本`），辅助更新后命名的预期边际差参数列，完美适配给 Page 6 (仓位配置) 的最终状态需求。

---

## 2026-02-27 | Page 6 仓位配置 — 漏斗评分与卫星激活统一使用现任剧本平滑胜率

### 背景
`fetch_funnel_scores` 在 Page 6 被调用时传入的是 `raw_probs`（原始截面胜率），导致 Molt 评分中占 40 分的宏观共振项（`score_macro`）基于快变的原始胜率计算，而非慢变的状态机现任剧本。结果：卫星激活门控用的是平滑胜率（正确），但实际选股评分仍跟着原始剧本走（错误）。

### 改动

**`pages/6_仓位配置.py`**
- 将 `session_state.get("smoothed_regime_probs")` 和 `session_state.get("live_regime_label")` 的读取提前到 `fetch_funnel_scores` 调用之前（原来在其后）。
- 新增 `_scores_macro = live_smoothed_probs if live_smoothed_probs else raw_probs`，以平滑胜率替代原始胜率传入 `fetch_funnel_scores`，确保 `df_qualified` 排序与卫星激活逻辑所用的剧本信号保持一致。
- fallback 逻辑完整：若 Page 1 未曾访问（session_state 为空），自动退回 `raw_probs`，无副作用。

### 遗留
- [ ] `arena_winners`（来自 Page 4）的冠军名单在 Page 4 访问时基于彼时的原始胜率生成，若剧本在两次访问间发生切换，arena_winners 中的票可能与当前现任剧本不完全对齐。建议用户在剧本切换后重新访问 Page 4 刷新竞技场结果。

---

## 2026-02-27 | 宏观定调 — 🎯 战术分组映射模块上线 (Tactical Group Mapping)

### 背景
"聪明钱因子"板块原有结论仅输出进攻/防守文字描述，缺乏对高净值客户最直接的可执行洞察（Actionable Insight）。本次在因子结论卡下方新增"战术分组映射"模块，将因子共振信号自动翻译为"建议超配 X 组"的白话战术指令。

### 改动

**`pages/1_宏观定调.py`**
- 新增因子驱动的战术组得分引擎（6 分制加权评分）：
  - **C 组（时代之王）**：动量霸榜(+2) · 投机进场(+1) · 进攻风格占优(+1) · 大盘跑赢小盘(+1)
  - **D 组（预备队·强周期）**：价值/小盘霸榜(+2+2) · 高贝塔正收益(+1) · 小盘跑赢大盘(+1)
  - **A 组（压舱石·防御）**：低波霸榜(+2) · 质量/红利进前三(+1+1) · 防守风格占优(+1)
  - **B 组（均衡核心）**：得分 < 2 时兜底，信号混杂无明确共振
- 渲染一个色彩编码的 Actionable 卡片，包含：
  - 推荐组别 + Emoji 徽章 + 动态彩色边框
  - 可视化进度条 `[████░░]` 显示共振强度（满分 6 格）
  - 信号置信度（高/中/低）三色标注
  - 触发因子 Top-3 名称 + 进攻/防守均值数值透明披露
  - 对应参考 ETF 标的

### 设计原则
- 纯前端计算，零后端依赖，复用已有 `off_f` / `def_f` 字典，无新数据拉取
- 分组名称仅作 UI 文字引用，未触碰 `my_stock_pool.py` 任何核心定义

---

## 2026-02-27 | D 组 ScorecardD 重构：预备队 → 爆点扫描仪

### 背景
D 组（预备队）原有评分体系沿用「动量 × R:R × 均线金叉」三因子框架，混入了「越跌越买」的抄底逻辑（Z-Score 反向计分），与 D 组真实使命相悖。D 组的核心价值不是评估"便不便宜"，而是识别"右侧爆发质量高不高"，即全市场无差别扫描早期异动股，向 C 组持续输送新鲜血液。

### 改动

**`api_client.py`**
- 新增 `get_arena_d_factors(tickers: tuple)` — 10 线程并发拉取 D 组 ScorecardD 三维因子：
  - `vol_z`：5 日均量相对 60 日基准的 Z-Score（量价共振烈度）
  - `rs_20d`：标的近 20 日收益率减去 SPY 同期收益率（真实超额 Alpha）
  - `ma60_dist`：`(当前价 / MA60 − 1) × 100%`（季线突破位置）

**`pages/4_资产细筛.py`**（原 `4_资产强筛.py` 已重命名）
- **废除旧因子**：完全移除 `mom20 50% / z_score_inv 30% / bullish 20%` 抄底框架
- **`ARENA_CONFIG["D"]` 全面改写**：三维度重组（满分 100 分）：
  - 维度一：量价共振烈度 `vol_z` — 权重 **45%**
  - 维度二：相对强度 Alpha `rs_20d` — 权重 **35%**
  - 维度三：均线起飞姿态 `ma60_breakout` — 权重 **20%**
- **新增 `_score_ma60_breakout(dist)`**：分段打分函数
  - `−10% ∼ +20%`（黄金突破区）→ 100 分
  - `+20% ∼ +50%` → 线性衰减至 0
  - `> +50%`（强弩之末）→ 0 分
  - `−10% ∼ −20%` → 100 → 50 衰减
  - `< −20%`（基础太弱）→ 继续下探至 0
- **新增 `compute_scorecard_d(df)`**：独立评分引擎，不复用通用 `compute_arena_scores`
- **新增 `_render_podium_d()`**：D 专属颁奖台，展示 Vol_Z / RS vs SPY / MA60偏离+姿态标注（绿色黄金突破区 / 橙色偏高 / 红色强弩之末 / 蓝色蓄力），替代原 Z-Score/动量/趋势健康
- **新增 `_render_leaderboard_d()`**：D 专属排行榜，三列指标 + 专属三色堆叠条（紫/蓝/橙），替代通用渲染器
- **D 渲染主体块（`elif _sel4 == "D":`）全面重写**：
  - 接入 `get_arena_d_factors` 拉取实时数据
  - 白盒公式面板展示 `Score_D = (45×Z_Vol5d) + (35×RS_20d) + (20×MA60_Breakout)`
  - KPI 卡片「趋势健康」→「黄金突破区」（统计处于最佳起飞姿态的标的数）
  - 冠军深度解读给出 MA60 姿态语义判断

### Bug 修复
- 修复 `_render_leaderboard_d` 中 f-string 表达式内含反斜杠转义（`\"因子N_分\"`）导致的 `SyntaxError`（Python ≤ 3.11 不允许 f-string `{}` 内含反斜杠）；改为预先提取局部变量 `f1_val / f2_val / f3_val`

### 遗留与未来优化方向
- [ ] `rs_20d` 当前以「标的 20 日收益 − SPY 20 日收益」近似超额 Alpha；更严格的定义应使用因子回归残差（Jensen's Alpha），留档待后续升级
- [ ] SPY 基准在 `get_arena_d_factors` 中每次调用均独立拉取（10 线程共享同一次 SPY 提前拉取已实现），若 API 限流偶发失败，`spy_ret20` 会 fallback 为 0，导致 RS 因子退化为绝对收益排名，暂可接受
- [ ] `ma60_dist` 在标的历史数据不足 60 日时退化为全区间均线，精度有损，已在代码中注释留档

---

## 2026-02-27 | 宏观时钟 Timeframe Toggle：战术之眼 vs 战略之眼

### 背景
宏观时钟当前采用固定的 750 日（≈3 年）滚动 Z-Score 窗口。对于需要观察跨商业周期结构性定位的用户，单一尺度无法提供"降维打击"的对比视角。同时，2026-02-25 遗留项中已记录"未来可考虑增加动态窗口选项"，今日正式实现。

### 改动

**`pages/1_宏观定调.py`**

- **时钟尺度切换器（Timeframe Toggle）**：在"🕰️ 宏观周期定位"标题行右侧新增水平 `st.radio`，提供两档：
  - ⚔️ **战术之眼 (Tactical · 3Y)**：750 日滚动 Z-Score，基准窗口 3 年，展望未来 3–6 个月；对冲基金动态网格的黄金比例，滤噪且提前半年感知趋势拐点。
  - 🔭 **战略之眼 (Structural · 10Y)**：2500 日滚动 Z-Score，基准窗口 10 年，展望未来 1–2 年；揭示跨完整商业周期的结构性定位，切换时重新拉取 12 年历史数据。
- **时间尺度语义标注**：切换器下方实时显示"基准窗口 Xyr · 展望未来 Y 个月/年"，让用户直观理解当前时钟的参考时域。
- **session_state 解耦设计**：切换器写入 `session_state["clock_timeframe"]`，脚本顶部在数据拉取之前读取该值以确定 `z_window`（750 or 2500）和 `years_to_fetch`（4 or 12），实现切换 → rerun → 正确数据管道 的全链路联动。
- **作用域精准标注**：切换器 tooltip 明确注明"仅影响宏观时钟的 Z-Score 基准窗口，页面其余部分不变"，避免用户误解。
- **UI 联动**：象限裁决横幅右侧徽章、白盒溯源展开区内的"XXX 日滚动 Z-Score"文字及合成方法说明全部动态引用 `z_window`，随切换同步更新。
- **位置**：Toggle 从侧边栏移除，归位至时钟标题行右侧 inline，语义上与时钟强绑定，不污染全局侧边栏空间。

### 遗留与未来优化方向
- [ ] 战略之眼首次切换需重新拉取 12 年数据（约 30 秒），后续可考虑对两种尺度分别维护独立的 `@st.cache_data` 避免重复拉取。
- [ ] FRED 官方数据 `get_clock_fred_data()` 已固定拉取 10 年历史，足够覆盖两档窗口；但若 FRED API 降级，战略之眼的 Z-Score 精度会受影响，已通过 fallback 降级到 ETF 代理，留档待优化。

---

## 2026-02-26 | P3: Page 2 & Page 4 ABCD 色块可点击切换分组

### 背景
Page 2（资产粗筛）与 Page 4（同类资产竞技场）顶部的 ABCD 大色块视觉面积大、信息密度高，却不可交互；用户须点击色块下方另起一行的 `st.tabs` 小字 Tab 才能切换分组，造成明显的操作冗余与视觉割裂。

### 改动

**`pages/2_资产粗筛.py` / `pages/4_资产强筛.py`（两页同步）**

- **交互层**：新增 `st.session_state["page2_selected_group"]` / `["page4_selected_group"]`（默认 `"A"`）维护当前选中组；每个色块下叠放一个空 label 的 `st.button(use_container_width=True)`，点击后更新 session_state 并 `st.rerun()`。
- **视觉层**：色块恢复为原有 HTML 大卡片（图标 / 计数 / 标签 / 更新频率）；选中态加深背景色 + 2px 实线边框 + `box-shadow` 发光，未选中态降调，Python 逐帧动态生成。
- **隐形覆盖技术**：注入 CSS 将 `div[data-testid='stButton']` 包装层高度压缩为 `height:0; position:relative`，内部 `button` 改为 `position:absolute; top:-Npx`，精准飞回上方色块，使整个卡片面积均可响应点击，视觉上无任何按钮痕迹。
- **悬停反馈**：CSS `:has(button:hover)` 在鼠标悬浮时对目标列的 stMarkdownContainer 施加 `brightness(1.18) + translateY(-3px)`，呈现轻浮起效果。
- **移除 `st.tabs`**：删除 `tab_labels` / `tabs = st.tabs(...)` 行；Page 2 的 `render_class_tab` 去掉 `with tab:` 上下文直接渲染；Page 4 的 `with tab_x:` 四块改为 `if _sel4 == "X":` 分支。

### Debug 过程记录（关键坑）

CSS 调试共经历三轮定位：

1. **`div[data-testid='stMain']` 选不到任何元素**：经 `components.html` DOM 探针确认，当前 Streamlit 版本的主内容容器为 `section[data-testid='stMain']`（非 `div`），`div` 前缀导致选择器从第一个词就失效。
2. **`:first-of-type` 选中错误元素**：页面上有 20+ 个 `stHorizontalBlock`，含侧边栏导航等非主内容元素，`:first-of-type` 命中的是一个 4 列纯 Markdown 块，ABCD 块实为 `blockIdx:1`。
3. **最终选择器**：改用 `[data-testid='stMainBlockContainer']`（确认为 `div`）作为祖先限定，配合 `:has(> div:nth-child(N)):not(:has(> div:nth-child(N+1)))` 以列数唯一锁定目标块（Page 2 = 5 列，Page 4 = 4 列且含 stButton）。

### 遗留与未来优化方向
- [ ] CSS 选择器依赖 Streamlit 内部 DOM 结构（testid 命名），Streamlit 大版本升级时需重新验证选择器有效性。

---

## 2026-02-26 | Page 4: 同类资产竞技场差异化打分因子 (P3)

### 背景
竞技场原有评分体系对所有 ABCD 四组采用同一套因子框架，无法体现各组的差异化投资逻辑：
A 组（防守/稳健）缺少股息率维度，C 组（成长/动量）缺少 Forward EPS、量能异动等核心 Alpha 捕捉因子。

### 改动

**`api_client.py`**
- 新增 `get_arena_c_factors(tickers: tuple)` — 10 线程并发拉取 C 组 ScorecardC 所需的两个特殊因子：
  - `earningsGrowth`（华尔街一致预期 YoY EPS 增速，fallback `revenueGrowth`）
  - 5 日成交量 Z-Score（相对 60 日基准，用于捕捉机构抢筹信号）

**`pages/4_资产强筛.py`**
- **A 组股息率因子（新增第 4 因子）：**
  - `ARENA_CONFIG["A"]` 升级为 4 因子，权重重分配：均线结构 30% / 估值稳健 20% / 长周期动能 25% / 股息率 25%
  - A tab 进入时自动调用 `get_stock_metadata()` 拉取实时股息率并注入 DataFrame
  - `compute_arena_scores()` 新增 `div_yield` 源映射，自动 Min-Max 归一化
- **C 组全新 ScorecardC 评分体系（满分 100 分）：**
  - 新增 `compute_scorecard_c()` 函数，实现 5 因子公式：
    `Score_C = (40×Z_ForwardEPS) + (15×log₁₀(MCap)) + (20×Z_Vol5d) + (15×Fit_Macro) + (10×Heat_Narrative)`
  - F4 宏观顺风：比对侧边栏选定剧本与 `MACRO_TAGS_MAP` — 顺风满分，逆风 0 分
  - F5 叙事热度：读取资产池内置 `STOCK_NARRATIVE_MAP` + `NARRATIVE_THEMES_HEAT`，Max-Norm 归一化
  - C tab 独立渲染，跳过通用 `compute_arena_scores`
  - 白盒公式面板：在竞技场结果卡上方渲染完整公式与各因子颜色说明，满足白盒化设计第一基本法
  - 冠军深度解读文字展示宏观剧本匹配状态及叙事主题
- **侧边栏新增「宏观剧本设定」选择器：** Soft / Hot / Stag / Rec，驱动 C 组 Macro Fit 打分
- **渲染引擎通用升级：**
  - `_render_podium` 和 `_render_leaderboard` 全面动态化，支持 2-5 个因子，引入 `_FACTOR_PALETTE` 调色板
  - 冠军解读文字动态拼接所有因子名称与得分，不再硬编码 3 因子格式

### 遗留与未来优化方向
- [ ] 宏观剧本选择器目前为手动设定，理想状态是从 Page 1 的 `api_clock_regime` 自动读取并写入 session_state，消除手动操作
- [ ] `earningsGrowth` 字段在 yfinance 中并非所有标的都有值（ETF 通常为 None），fallback 到 `revenueGrowth` 后精度有损失，DEV_LOG 留档待优化
- [ ] C 组 ScorecardC 的 Vol_Z 目前基于 60 日滚动，与需求文档中"过去 5 个交易日 Z-Score + 价格相对 5 日均线偏离度"的完整定义相比还缺少价格偏离度分量，已阉割，待后续版本补齐

---

## 2026-02-25 | 宏观定调中心 Phase 3 重构完成：多维复合时钟引擎与白盒化 UI

### 背景
当前系统中的 X 轴（增长）和 Y 轴（通胀）过度依赖单一的 XLY/XLP 和 TIP/IEF，存在严重的指标失真。根据架构师指令，对 `1_宏观定调.py` 进行了分为三阶段的重构，Phase 1 建立 FRED 混合管道，Phase 2 采用三引擎交叉验证（750日 Z-Score 等权），Phase 3 则是对 UI 层进行深度白盒化展示。

### 改动
**`pages/1_宏观定调.py`**
- **象限裁决逻辑 (Quadrant Logic)**：新增五阶象限判定，优先判断双轴 Z-Score 均在 ±0.5 以内的"软着陆"中心区，以及过热、复苏、滞胀、衰退四个极值象限。
- **复合坐标横幅 (Composite Banner)**：在宏观周期定位标题下方新增高亮横幅，直观打印当前所处象限名称、具体 Growth & Inflation Z-Score 坐标点，以及 750 日计算窗口提示。
- **白盒化拆解面板 (White-Box Breakdown)**：彻底废除旧版单指标“模型逻辑”文案，更替为全新的多维复合引擎拆解面板，将 Growth 轴（消费、工业、信用）与 Inflation 轴（聪明钱、大宗、核心CPI）的底层组成、权重及宏观传导逻辑明确展示在 UI 上。
- 遵循数据防御编程，对变量和标签进行了安全处理（如 FRED 接口不可用时的自动降级说明）。

### 未来优化方向
- [ ] 当前 Z-Score 采用静态 750 日滚动窗口，未来可考虑增加动态窗口选项供高级用户切换对比。
- [ ] 信用利差因子的极值判定是否需要非线性化处理，待后续实盘验证。

---

## 2026-02-25 | Page 4→5 路由重构：竞技场冠军直通猎杀

### 背景
Page 5（个股深度猎杀）侧边栏原本使用一个全开放的战术分组多选框（A/B/C/D/E/F/G/H），
配合本地 Funnel Scan（MA + Sortino + R:R 打分），让用户可以从任意分组挑选标的。
这与 Page 5 的架构定位完全矛盾——该页设计为接收 Page 4 竞技场的胜利者，而不是独立选股入口。

### 改动

**`pages/4_资产强筛.py`**
- 在 `_render_arena_tab()` 函数的评分完成后，自动将每个赛道（A/B/C/D）的 **Top 3** 写入
  `st.session_state["p4_arena_leaders"]`（按 cls 分组，值为 list of dict）。
- 无需用户点击"深度猎杀"按钮即可自动同步，按钮路由（`p4_champion_ticker`）仍保留用于高亮默认选中项。

**`pages/5_个股分析.py`**
- 移除：全组多选框、本地 Funnel Scan 函数、宏观时钟检测函数、宏观分组映射、
  全量 Ticker 列表构建、`_get_p5_data()`——共删除约 145 行死代码。
- 移除无用 import：`numpy`、`datetime/timedelta`、`REGIME_MAP`、`USER_GROUPS_DEF`、
  `MACRO_TAGS_MAP`、`SECTOR_MAP`。
- 新增：从 `p4_arena_leaders` 读取 Top 3 × 4 赛道 = 最多 12 个候选，
  以 🥇🥈🥉 勋章标注排名，展示为 selectbox。
- 若 Page 4 尚未访问（session_state 为空），显示引导警告而非空选框。
- 手动越权输入框保留在底部，供高级用户绕过路由。

### 未来优化方向
- [ ] Page 4 目前每次渲染都会覆盖 `p4_arena_leaders`，若用户在 Page 4 切换 Tab 顺序，
      先渲染的 Tab 结果可能被后渲染的覆盖（实际上是合并 dict，无问题，但需留意）。
- [ ] 可考虑在 Page 5 侧边栏增加按赛道筛选的 radio，方便快速聚焦某一 class。
- [ ] `p4_champion_ticker`（按钮直通路由）目前仅高亮默认选中，未来可做成置顶显示。
