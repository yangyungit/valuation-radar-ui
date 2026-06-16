---
model: claude-opus-4-7
complexity: complex
---

# 执行 plan：C组双龙持仓（page0 第三个 tab）

> 给新窗口 agent 的自包含执行文档。读完即可直接开工，无需翻聊天记录。
> 跨两个仓库：后端 `valuation-radar`、前端 `valuation-radar-ui`。
> 本文档是多轮人机讨论收敛后的**最终方案 v3**，所有"为什么这么定"都写进去了，按此严格执行，不要自行改设计。

---

## 0. 一句话目标

在 page0 `pages/0_宏观雷达.py` 的"板块王朝接力图"区块里，**新增第三个 tab「📈 C组双龙持仓」**：
在 3Y/5Y/10Y 窗口内，对 C 组（11 个 SPDR sector ETF）的成分股汇总池，跑一个**可执行规则的历史模拟**——
每月按动量选出最强的 **2 只个股**持有，用"守擂缓冲"压低换手，扣交易成本，输出净值曲线、持仓时间带、统计卡、换手-收益取舍图。

**诚实定位（必须在 UI 顶部明示，不准包装成真实业绩）**：
这是"**信号无前视 + 可执行规则的历史模拟**"，但**股票池含生存者偏差**（只有当前标普500成分，缺失历史上被剔除/退市/收购的公司）。
叫它**研究原型**，不叫"真实可执行回测"。

---

## 1. 背景：这块在系统里的位置

- 前端 `pages/0_宏观雷达.py` 约 542 行起是"§1.6 板块王朝接力图"。
- 565 行 `_dyn_tab1, _dyn_tab2 = st.tabs(["👑 王朝接力图", "🏆 王朝龙头股"])` → **改成三个 tab**，新增第三个。
- 已有 `_DYNASTY_TAB_WINDOWS = ["3Y", "5Y", "10Y"]` 和上方的 `_dynasty_window` radio（556 行），**复用，不新建窗口选择器**。
- 后端时序走 `fetch_macro_radar_timeseries(window, profile="dynasty")`；龙头钻取走 `fetch_dynasty_leaders(...)` → 后端 `compute_dynasty_leaders`。
  本功能**新增独立后端函数 + 新 endpoint**，不复用上面两个的返回结构（口径不同）。

---

## 2. 策略规格（最终锁定，逐条照做）

### 2.1 选股池
- C 组 = 11 个 SPDR sector ETF（XLK/XLF/XLE/XLV/XLI/XLY/XLP/XLU/XLB/XLRE/XLC），覆盖全部 11 个 GICS sector。
- 候选个股 = 这 11 个 sector 的成分股汇总 ≈ 标普500 全体。
  - 取法：对 `_SPDR_TO_GICS` 里 11 个 sector 各调 `get_sp500_by_gics_sector(gics)` 并并集；或直接读 `sp500_gics` 全表。**动手前先确认这两条等价**（理论上 C 组覆盖全 GICS，应等价）。
- **`date_added` 半修复前视**：个股在月 t 只有当 `date_added <= t` 才可被选（避免在入指数前被选中）。
  - **动手前必须抽查 `sp500_gics.date_added` 字段质量**（空值率、格式）。若大面积为空/不可靠，则退化为"全程当前池"，并在 UI 明确标注"未启用入指数日过滤"。
- ⚠️ 生存者偏差：当前池缺失历史上被剔除/退市/收购的公司，结果偏乐观，UI 顶部必须标注。

### 2.2 排名信号（决定"谁更强"，用户可切）
- 默认 **12M** = 过去 252 个交易日涨幅。
- 可切 **12-1** = 过去 252 日、但跳过最近约 21 个交易日（避短期反转）。
- 可切 **6M** = 过去 126 个交易日涨幅。
- 都在真实交易日上算（用价格面板自身的交易日索引即可，yfinance 返回的就是交易日）。

### 2.3 风险门槛（决定"是否还值得持有"，独立于排名信号，固定用 12M）
- 一只票"合格"当且仅当：**过去 12M 绝对收益 > 0 且 当前价 > MA200**（MA200 = 过去 200 个交易日均价）。
- **注意**：无论排名信号切到 6M 还是 12-1，**风险门槛永远用 12M 那条口径**（排名回答"谁更强"，门槛回答"是否值得冒险"，两个概念分开，UI 要写清）。
- 做成开关 `risk_protect`，**默认开**。
  - 开：不合格的票不能进/不能留，优先由其他合格票补位；合格票不足 2 只时，缺少的槽位才转 BIL。
  - 关：忽略门槛，槽位永远持排名选出的 2 只，永不进 BIL。
- 提醒：12M 收益>0 与 价>MA200 高度相关，震荡期会反复进出 BIL；正因如此才要开关 + 在统计卡展示它的代价（见 2.8）。

### 2.4 持仓数量与权重
- **固定持有 2 只**（产品核心叫"双龙"，**不做可调数量**，不要加 2/3/5 参数）。
- 初始等权 50/50 买入。

### 2.5 独立槽位账户（关键实现语义，别搞错）
- 把资金分成**两个各自独立复利的槽**（槽A / 槽B），不是一个大锅。
- **不再平衡时（默认）**：每个槽各自复利；某槽的票被替换，**只把该槽当前市值**换成新票，另一槽分文不动 → 组合权重自然漂移。
  - 例：槽A 5万买NVDA→涨到15万；槽B 5万买AVGO。AVGO 被 AMD 替换 → 只用槽B的5万买AMD，槽A的15万NVDA不碰。换名只在被换槽的市值上付成本。
- **再平衡开启时**：每月执行日把组合总资产重新分成 50/50（槽间挪钱），并对挪动的名义额扣成本。
- **BIL 也按槽走**：某槽无合格票 → 该槽整体转 BIL；两槽都无合格票 → 100% BIL。

### 2.6 守擂（唯一换手旋钮 K）
- 进场：从合格票里按排名取前 2 填满两槽。
- 保留：在位的票**仍在前 K 名 且 过风险门槛** → 继续持有。
- 卖出：**跌出前 K 名 或 风险门槛失败** → 卖出，腾出的槽由"当前排名最高的、合格的、未持有"的票补上；无合格票则该槽转 BIL。
- **K 范围 2~60**，滑块默认 **30**（中性展示值，不代表最优，不要在 UI 标"最优"）。
  - K=2 = 每月严格持最新 Top2 = 最高换手基准（正好是 2.7 的对照线）。
  - 说明：池有 ~500 只，"每月稳居前 5"几乎不可能 → 小 K 换手极高；低换手区在大 K（20/30/50）。这是 K 范围必须放宽到 60 的原因。
- **v1 不加挑战者 margin**（第二道守擂留 v2）。

### 2.7 对照线（净值图上）
- 主线：**双龙策略**（当前 K）。
- **纯Top2 对照线** = 同一套策略在 K=2 的结果（frontier 已算，免费），回答"守擂相比月月追 Top2 省了多少换手、亏/赚多少"。
- 基准：**SPY**（市值加权标普500）、**RSP**（等权标普500，代表"普通一只票的平均"）。
- 可选：11 只行业 ETF 等权（默认收起）。

### 2.8 执行、成本、统计
- **执行时点**：月末收盘出信号，**次日交易日收盘成交**（DB 只有 Close，不做次日开盘）。
- **成本**：每条腿（买/卖各算一次）按单边默认 **10bps**（可调，放高级设置）扣在成交名义额上。换名 = 卖旧+买新 = 两条腿。再平衡挪动也按腿计。**成本口径在代码里写注释固定下来，保持前后一致。**
- **换手口径**：年化单边换手 = 展示期内各执行日 `0.5 × Σ|w_new − w_old|`（w 为占总资产比例）的总和 ÷ 展示期实际年数。
- **统计卡指标**（大白话命名见 §4.3）：累计收益 / 年化收益(CAGR) / 最大回撤 / 收益回撤比(Calmar) / 换股次数 / 平均一只拿几个月 / 年均换手 / 累计成本 / 比SPY多赚 / BIL停留月数。

### 2.9 frontier（换手-收益取舍图）
- 后端**一次性**把 K 从 2 扫到 60（建议网格 `[2,5,10,15,20,25,30,40,50,60]`，可全扫）跑出来，**复用同一份动量/合格面板**（贵的是数据+面板，K 循环很便宜）。
- 每个 K 返回：(年均换手, 扣成本年化收益, 收益回撤比)。
- 前端画散点/折线：横轴年均换手，纵轴两条（年化收益 + 收益回撤比）；当前 K 高亮。**不自动标"最优K"**，UI 提示"看稳定平台、别挑历史最高的孤点"。

---

## 3. 后端实现（valuation-radar）

### 3.1 落点
- `macro_engine.py`：新增回测函数（建议 `compute_double_dragon_backtest(window, signal, k, risk_protect, rebalance, cost_bps)`）。
- `api_server.py`：新增 endpoint（建议 `GET /api/v1/macro/dynasty/double_dragon`）。
- `tests/`：新增 `test_double_dragon.py`。

### 3.2 复用的现有函数（动手前 grep 确认签名，别凭记忆）
- `_SPDR_TO_GICS`、`get_sp500_by_gics_sector`、`get_sp500_prices`、`get_regime_prices`（见 `compute_dynasty_leaders` 约 2075 行的用法）。
- `_DYNASTY_WINDOW_CONFIG`（约 92 行，取 `display_days`：3Y/5Y/10Y = 756/1260/2520）。
- `_TICKER_LISTING_OVERRIDE`（借壳身份校正，如 OKLO，沿用）。
- 价格下载/批处理 `_yf_download_batched`（如需补 RSP/BIL 历史）。`sp500_gics.date_added` 字段。

### 3.3 算法（逐步，务必无前视）
1. **取数据窗口**：展示窗口 = `display_days` 个交易日；**额外预热 ≥ 252+200 个交易日**（动量+MA200 需要起点前历史）。即数据起点 = 展示起点往前推约 1.5 年。
2. **价格面板**：候选个股 `get_sp500_prices(tickers, data_start, data_end)`；基准 `get_regime_prices` 取 SPY/RSP/BIL + 11 个 sector ETF。RSP/BIL 若 DB 没有，用 `_yf_download_batched` 拉并入。全部 `.astype(float)`，按交易日索引对齐。
3. **逐日收益**：每只票日收益序列（用于槽内复利）。BIL 同理（拿不到 BIL → 现金 0 收益，标注降级）。
4. **月末信号面板**（在交易日上 resample ME 取每月最后交易日 t）：
   - 排名信号值（按 `signal` 选 12M/12-1/6M 的窗口）。
   - 风险门槛布尔：`ret_12m(t) > 0 and price(t) > MA200(t)`。
   - `date_added <= t` 可选过滤。
   - 当月排名（对合格票或全体按信号降序，rank min）。
   - **所有量只用 ≤ t 的数据算**。
5. **槽位模拟（月度循环）**，对给定 K：
   - 维护 slotA/slotB：each = {ticker | "BIL" | None, value}。
   - 决策日 t 生成新目标，**成交在 t 的下一个交易日 t+1 收盘**：
     - 计算保留/卖出/补位（见 §2.6），risk_protect=False 时跳过门槛、永不 BIL。
     - 对发生变动的槽，在 t+1 按当时价格换手，扣两条腿成本。
   - t+1 到下一个决策日之间，每个槽按其持仓（票或 BIL）日收益复利。
   - rebalance=True：每个执行日把两槽按总资产掰回 50/50，扣挪动成本。
6. **净值序列**：daily 组合净值 = slotA.value + slotB.value（从 1.0 或初始资金归一）。
7. **基准净值**：SPY/RSP/11ETF等权 各自归一（11ETF等权 = 11 条 ETF 日收益等权合成，按月或不再平衡均可，简单起见日度等权）。
8. **统计**：按 §2.8 口径算全部指标。
9. **frontier**：对 K 网格重跑第 5-6 步（复用第 4 步面板），每个 K 收 (年均换手, 净CAGR, Calmar)。
10. **当前持仓**：最后一个月各槽 {ticker, 首次持有月, 当前排名, 已守擂月数} 或 BIL。

### 3.4 返回 schema（endpoint JSON）
```
{
  "success": true,
  "window": "5Y", "signal": "12m", "k": 30,
  "risk_protect": true, "rebalance": false, "cost_bps": 10,
  "dates": [...],                       # daily
  "equity": {"strategy":[...], "top2":[...], "spy":[...], "rsp":[...], "eqw11":[...]},
  "holdings_timeline": [{"month":"YYYY-MM","slotA":{...|null|"BIL"},"slotB":{...}}],
  "current_holdings": {"slotA":{"ticker","name","since","rank","held_months"}|{"bil":true}, "slotB":{...}},
  "stats": {"cum_return","cagr","max_dd","calmar","n_swaps","avg_hold_months",
            "ann_turnover","cum_cost","excess_vs_spy","bil_months"},
  "frontier": [{"k","ann_turnover","net_cagr","calmar"}, ...],
  "meta": {"universe_size","data_start","display_start","survivorship_note","date_added_used": true|false,
           "price_as_of","signal_as_of","last_execution_date","stale_days","is_stale",
           "requested_days","actual_days","actual_years","window_complete"}
}
```
- 失败返回 `{"success": false, "error": "..."}`，前端显式判 `success`（不准静默失败，见数据一致性约束2）。
- **缓存键** = (window, signal, k, risk_protect, rebalance, cost_bps)；贵的价格面板按 (window, signal, risk_protect, date_added_used) 缓存，K 循环复用。首次加载会慢（~500 股 + 预热 + BIL/RSP），做进程内缓存。

### 3.5 测试 `tests/test_double_dragon.py`
- 至少 3 条：
  1. 3Y/5Y/10Y × {12m} × 默认开关，endpoint/函数返回 success、equity 长度 == dates 长度、frontier 非空。
  2. **无前视不变性**：把"展示窗口之后"的未来价格人为改动，断言历史每月的选股决策与净值在改动前后**完全一致**（证明没用到未来数据）。
  3. risk_protect 关 vs 开：关时永不出现 BIL 月、bil_months==0；构造合格票不足 2 只的月份，开时缺少槽位必须进入 BIL。
- 跑 `pytest tests/test_double_dragon.py -q` 全绿。

---

## 4. 前端实现（valuation-radar-ui）

### 4.1 落点
- `api_client.py`：新增 `fetch_dynasty_double_dragon(window, signal, k, risk_protect, rebalance, cost_bps)`，**照抄 `fetch_dynasty_leaders` 的缓存 + 错误包装写法**（动手前读它）。在侧边栏强刷处（约 49 行 `fetch_dynasty_leaders.clear()` 附近）注册 `.clear()`。
- `pages/0_宏观雷达.py`：565 行 `st.tabs([...])` 加第三项 `"📈 C组双龙持仓"`，新增 `with _dyn_tab3:` 块。

### 4.2 UI 布局（从上到下）
1. **Tab 标题/副标题** + **⚠️ 诚实声明 caption**：信号不看未来 / 次日成交 / 扣成本；但池是当前标普500成分、含生存者偏差 → 研究原型，非真实业绩。（若未启用 date_added 过滤，补一句说明。）
2. **顶部控制区（精简）**：排名信号 radio `12M/12-1/6M`；守擂 K 滑块 `2~60` 默认 30；个股趋势过滤开关默认开；再平衡开关默认关；`⚙️ 高级设置` expander 内放成本 bps 滑块（默认10）+ "显示11只行业ETF等权"勾选。
3. **当前持仓卡**（insight-box，**显式 for 循环**渲染两个槽，不用列表推导）：标题写明截至哪个信号月；槽A/槽B → `名称(ticker)｜首次持有 YYYY-MM｜当前排名 第N｜已守擂 M 月`；空仓槽显 `BIL（无足够合格股票）`。
4. **净值曲线**（plotly 折线，送图前 `.astype(float).dropna()`）：默认只显**双龙策略 + SPY**；纯Top2 / RSP / 11ETF 设 `visible="legendonly"`（在图例、默认不画，点图例展开）。
5. **持仓时间带**：两条横向轨道（槽A/槽B），每只票一种颜色（只给真正持有过的票上色），hover 显 ticker + 区间；BIL 用灰色。看接力与持有时长。
6. **统计卡**：`st.metric` 网格，双龙 vs 纯Top2 并排；大白话命名见 §4.3。
7. **K 取舍图 frontier**（plotly）：横轴年均换手，纵轴两条（年化收益 + 收益回撤比），每点一个 K，当前 K 高亮；caption 提示"看稳定平台、别挑孤立最高点"，不标"最优"。

### 4.3 统计卡大白话命名（强制）
| 内部/术语 | UI 显示 |
|---|---|
| CAGR | 年化收益 |
| Calmar | 收益回撤比（越高越好） |
| max_dd | 最大回撤（从最高点最大跌幅） |
| ann_turnover | 年均换手（每年大约换掉多少仓位） |
| excess_vs_spy | 比SPY多赚 |
| avg_hold_months | 平均一只拿几个月 |
| n_swaps | 换股次数 |
| cum_cost | 累计成本 |
| cum_return | 累计收益 |
| bil_months | BIL停留月数 |

### 4.4 前端架构合规自检（必过）
- 业务计算**全在后端**，前端只渲染（不准在前端算回测/动量/选股）。
- Streamlit 组件用**显式 for 循环**，不用列表推导式。
- 送 plotly 前 `.astype(float).dropna()`。
- 自定义 HTML/CSS 字号：正文 ≥13px、标题 ≥15px、脚注 ≥13px。
- 侧边栏保留全局 `st.cache_data.clear()` 一键强刷（已有，确认新 fetch 的 `.clear()` 已注册）。

---

## 5. 不准动清单（红线）

- 不准改 `my_stock_pool.py`、A/B/C/D 战术分组。
- 不准动 `narrative.db` / `universe.db` / `data/` 缓存数据 / `arena_history*` / `conviction_state*`。
- 不准改 `requirements.txt` / `pyproject.toml` / DB schema / migration。
- 不准改 `DATA_FLOW.md` / `DATA_CONSISTENCY_PROTOCOL.md` / `REQUIREMENTS.md` / `page2_dictionary_manual.md`。
- 前端不准硬编码后端常量（成本默认值、K 默认值等以后端返回/参数为准，能从后端拿就别写死）。
- 新增 `/api/v1/*` endpoint = API 契约变更：**必须在两仓 `DEV_LOG.md` 记一条**，并提醒主理人前端 `api_client.py` 已同步。

---

## 6. 运行与 Git 工作流（本地优先，⭐ 重要）

**主理人当前目标 = 先在本地跑通，一切以本地为主。线上 Render 由主理人本地验证通过后亲自同步，执行 agent 不要碰线上。**

- **不要 `git push`**：可以本地 commit（显式文件路径、中文 message、动词开头、首行 ≤60 字），但**推送一律留给主理人**。线上部署不在本任务范围。
- 本地启动验证（两步，缺一不可）：
  1. 后端：`cd valuation-radar && source ../system/venv/bin/activate && python api_server.py` → `http://localhost:8000`
  2. 前端：`cd valuation-radar-ui && source ../system/venv/bin/activate && streamlit run app.py` → `http://localhost:8501`
- 真相源 = **本地 localhost**（不要 curl Render，不要拿 Render 数据做验证）。
- 先后端、再前端（前端依赖后端新 endpoint，后端起来了前端才能联调）。
- 显式文件路径 `git add`，禁止 `git add -A/.`；commit 前先 `git status` 核对。
- 后端 Python 改动，验证前 `ReadLints` 无新增错误、`pytest` 绿。
- 不 force / 不 amend / 不动 config / 不新建分支 / **不 push**。

---

## 7. 验收标准（机器可判 + 人工确认）

> 全程在**本地** localhost 验证（后端 :8000、前端 :8501），不 push、不碰 Render。

机器可判：
1. 后端 `pytest tests/test_double_dragon.py -q` 全绿（含无前视不变性测试）。
2. endpoint 对 3Y/5Y/10Y × {12m,12-1,6m} × {risk on/off} × {rebalance on/off} 均返回 success，equity 长度==dates，frontier 非空。
3. 前端 tab 渲染无异常；净值图默认只显双龙+SPY，其余 legendonly 可点开；统计卡用大白话名；K 滑块改动能刷新。
4. `ReadLints` 前后端均无新增错误。

人工确认（交付时一并汇报给主理人）：
5. K 从小到大时年均换手大体下降（frontier 形态合理）。
6. 如实汇报个股趋势过滤开/关后的收益、回撤、换手与 BIL 停留差异，不预设开启后一定降低回撤。
7. ⚠️ 生存者偏差声明在 UI 顶部可见。

---

## 8. 明确推迟到 v2（v1 不做，别顺手加）

- 历史时点真实成分股（消除生存者偏差）——需新数据源，最重。
- 多周期合成 / 风险调整动量信号。
- 第二道守擂（挑战者 margin）。
- walk-forward 自动样本外验证 / 自动选最优 K。
- 次日开盘成交（需补 OHLC）。
- BIL 之外的现金代理细化。

---

## 9. 决策依据备忘（防止执行时被"优化"冲动带偏）

- **为何固定 2 只**：产品核心是"双龙"，可调数量模糊概念、加过拟合面。波动大是特征不是 bug，用"最大回撤"数字暴露即可。
- **为何独立槽位 + 默认不再平衡**：最贴合"低换手"目标；再平衡=砍赢家喂输家，与动量逻辑相悖，故默认关、做成开关供对比。
- **为何风险门槛固定 12M、独立于排名信号**：排名答"谁更强"，门槛答"是否值得冒险"，混用会让用户切 6M 时困惑。
- **为何 K 放到 60**：500 池里小 K=高换手，低换手区在大 K，范围必须够宽，默认 30 仅中性展示。
- **为何 frontier 不标最优**：单一历史路径 + 生存者偏差下，挑历史最高 K = 过拟合；只用它看"换手换收益"的取舍。
