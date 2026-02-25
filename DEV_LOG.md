# DEV LOG — valuation-radar-ui

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
