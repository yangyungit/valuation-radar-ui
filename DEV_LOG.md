# DEV LOG — valuation-radar-ui

---

## 2026-04-12 | A 组赛道剔除 Z 种子池资产（防止固收屠榜）

### 背景与动机
Z_SEED_POOL 中的固收/生息类资产（SGOV、BIL、SHV、SHY、TLT、PFF 等 27 只）天然具备极低回撤、极低波动、低 SPY 相关性的属性，完美匹配 A 组「避风港防御指数」的四维评分体系。导致 A 组排行榜被这些"稳如狗拿利息"的品种屠榜——而 A 组的设计初衷是筛选**防御性权益资产**（如 KO、PG、XLU），不是吃利息的纯固收品种。

### 改动清单

**`valuation-radar/api_server.py`**
- `get_stock_pool_data()` 响应新增 `Z_SEED_TICKERS` 字段：下发 Z 种子池全部 ticker 列表，供前端识别并排除。
- `from my_stock_pool import` 新增 `Z_SEED_POOL`。

**`screener_engine.py`**
- `classify_all_at_date()` 新增可选参数 `z_seed_tickers: set`。
- 分类后若 ticker ∈ z_seed_tickers，从 `qualifying_grades` 中移除 "A"。
- Z 种子池资产仍正常参与 Z 组竞赛，不受影响。

**`pages/3_资产细筛.py`**
- 顶部解包 `_Z_SEED_TICKERS = set(_core_data.get("Z_SEED_TICKERS", []))`。
- 实时分类和历史回测两处 `classify_all_at_date()` 调用均传入 `z_seed_tickers=_Z_SEED_TICKERS`。

### 影响范围
- A 组参赛选手减少约 15-20 只（纯固收/高息 ETF），剩余为真正的防御性权益标的。
- Z 组不受影响，Z 种子池资产继续在 Z 组正常竞赛。
- B/C/D 组不受影响（Z 种子池标的极少满足这些组的入选条件）。

---

## 2026-04-12 | Z 组排名体系重构：从"股息率驱动"升级为"Total Return 驱动"

### 背景与动机
原 Z 组评分体系以裸股息率为 40% 头号因子，存在重大理论缺陷：
- **股息率是动态 U 本位**：股价腰斩后除息率虚假翻倍（如 STRK：12.71% 息率，-41% 最大回撤），形成"跌出来的假高息"排名陷阱。
- **因子共线性**：原 F2 EPS 稳定性 = `1/vol`，与 F3 低波动率 = `1/vol` 本质相同，等于同一维度权重翻倍。
- **缺失 Total Return 维度**：年发 8% 股息但净值阴跌 15% 的资产，在原体系中依然得高分——是真正的财富粉碎机。

### 改动清单

**`api_client.py`**
- `get_arena_b_factors()` 新增返回字段 `price_return_252`：近 252 日纯价格回报（不含股息），作为 Z 组净值趋势因子的数据源。

**`pages/3_资产细筛.py`**（核心重构）
1. `ARENA_CONFIG["Z"]` 权重体系：四因子 → 五因子
   - 旧：股息率 40% / EPS 稳定性 25% / 低波动 20% / 最大回撤 15%
   - 新：Sharpe 30% / 股息率 20% / 分红续航力 20% / 最大回撤 15% / 净值趋势 15%
2. `FACTOR_ANCHORS` 新增锚点：`sharpe_1y_z (-0.5, 2.0)` / `price_return_1y_z (-0.35, 0.15)`
3. `_FACTOR_PALETTE` 扩充第 6 色 `#E74C3C`（红色映射净值趋势因子）
4. `compute_scorecard_z()` 全面重写：
   - F1 (30%)：夏普比率（来自 `get_arena_b_factors` 的 `sharpe_252`）
   - F2 (20%)：真实股息率（降权，不再是主角）
   - F3 (20%)：分红续航力（保留 EPS 稳定性代理，但消除了与 F1 Sharpe 的共线）
   - F4 (15%)：最大回撤倒数（不变）
   - F5 (15%)：净值趋势惩罚（`price_return_252`，惩罚净值阴跌的资产）
   - **新增：股息陷阱熔断** — 股息率 > 8% 且净值跌 > 20%，触发 `🌋 股息陷阱` 标记并扣 20 分
5. Z 组竞技场数据采集块新增 `夏普比率` 和 `净值趋势_1Y` 两列（含 backfill 路径和 API 路径）
6. 排行榜 Header 列更新：原"年化波动" → 改为"Sharpe"和"净值趋势"
7. 每行 KPI 单元格：显示股息率（含 🌋 陷阱标记）/ Sharpe 值 / 净值趋势%
8. 因子权重 pill 标签、白盒公式展示区、冠军深度解读文案全部同步更新

### 影响范围
- Z 组排名将发生实质性变化：STRK 等"跌出来的假高息"标的排名下滑，SCHD / JEPI 等"稳健总回报"标的排名提升。
- A 组、B 组、C 组、D 组评分逻辑**完全不受影响**。

---

## 2026-04-12 | Page 4 资产调研加入 Z 组支持

### 背景
Page 4（资产矩阵与雷达）的 `CLASS_META` 中完全缺失 Z 级（现金流堡垒），导致 Z 类资产无法出现在散点图、统计卡片、竞技场胜出者区块及资产深度查询面板中。

### 改动
- `CLASS_META` 新增 `"Z"` 条目（label/icon/color/update_freq/criteria/logic/strategy）
- 侧边栏多选框 `selected_cls` 默认加入 Z
- `_GRADE_JITTER`、`_qg_total/show/bullish` 计数字典全部扩容至含 Z
- 散点图循环 `["A","B","C","D","Z"]`、统计卡片改为 5 列
- 竞技场胜出者区块（Top-2 列、历史月度表、连胜统计）全部支持 Z 赛道
- 资产深度查询下拉框：Z 组资产按 Z-Score 升序排序后只显示前 20 名（Z-Score 越低 = 当前收益率越高），超出则显示提示文字

### 影响范围
仅 `pages/4_资产调研.py`，无接口变更。

---

## 2026-04-12 | 宏观定调页 FRED 数据拉取改用 requests 直连

### 背景
`pandas_datareader` 与 `pandas >= 2.0` 存在已知兼容性 bug（`TypeError: deprecate_kwarg() missing 1 required positional argument: 'new_arg_name'`），导致宏观定调页面的 FRED 数据管道（核心 CPI、非农就业、工业生产、HY 信用利差等）实际上无法拉取，质检员一直报警告。

### 改动

**`pages/1_宏观定调.py`**
- 移除 `pandas_datareader` 的 try/import 块。
- 新增 `_fetch_fred_series(series_id, start_date, end_date, api_key)` — 单序列 FRED REST API 调用，自动跳过 `"."` 缺失值。
- 新增 `_fetch_fred_batch(series_ids, start_date, end_date, api_key)` — 批量拉取多序列并合并为 DataFrame。
- `get_clock_fred_data()`：改用 `_fetch_fred_batch`，从环境变量 `FRED_API_KEY` 读取密钥，未配置时抛出明确 RuntimeError（外层 try/except 已兜底降级）。
- `get_liquidity_data()`：同样改用 `_fetch_fred_batch`，未配置密钥时 `df_macro` 优雅降级为空 DataFrame。

**`valuation-radar/api_server.py`**
- `api_keys_status` 端点新增 `FRED_API_KEY` 检查项，质检员密钥面板现在会提示是否已配置 FRED Key。

### 必要操作
需在 Render 环境变量中配置 `FRED_API_KEY`（免费申请：https://fred.stlouisfed.org/docs/api/api_key.html）。

---

## 2026-04-12 | 质检员新增「API密钥」扫描模块

**背景**：首页质检员无法检测 FINNHUB / ALPACA / POLYGON / GEMINI 等第三方 API key 是否在 Render 环境变量中正确配置，导致爬虫静默降级时难以排查。

**变动内容**：
- **后端** `api_server.py`：新增 `GET /api/v1/system/api_keys_status` 端点，读取 6 个关键环境变量（`FINNHUB_API_KEY`、`ALPACA_API_KEY`、`ALPACA_SECRET_KEY`、`POLYGON_API_KEY`、`GEMINI_API_KEY`、`ADMIN_SYNC_TOKEN`），只暴露 `configured: bool`，不泄露 key 值。
- **前端** `health_checker.py`：新增 `check_api_keys()` 检查函数，调用上述端点，每个未配置的 key 产生 WARNING 并附上 Render 操作提示；已注册到 `run_all_checks()` 并发池。
- **前端** `app.py`：在仪表盘 `CATEGORY_ICONS` / `CATEGORY_ORDER` 中注册 `"API密钥": "🔑"`，排在 API契约 之后。

**影响范围**：首页质检员新增「🔑 API密钥」卡片；未配置的 key 将显示黄色 WARNING；不影响已有检查项。

---

## 2026-04-12 | Z 级「现金流堡垒」三阶段全域扩充

**背景**：Z 级赛道长期无候选标的，原因是股票池中仅有少量天然高息股，且 yfinance 的 `lastDividendValue * 4` 假设季度付息，对月度付息资产（如 JEPI/O/STAG 等）严重低估 ~3 倍，导致这些资产无法过 `div_yield >= 1%` 门槛。

### Phase 1：静态种子池 + 数据修复

**`valuation-radar/my_stock_pool.py`**（复杂变动）：
- 新增 `Z_SEED_POOL` 字典：26 个生息类标的，覆盖七大子类——极短债（BIL/SGOV/SHV/SHY）、中长期美债（IEF/TLT/GOVT）、投资级/高收益债（AGG/LQD/HYG/EMB）、高股息权益 ETF（SCHD/VYM/JEPI/JEPQ/DVY/HDV/NOBL）、REITs（O/VNQ/STAG）、优先股（PFF/STRF/STRK）、BDC（ARCC/MAIN）
- 解析引擎追加循环：Z_SEED_POOL 合入 TIC_MAP/SECTOR_MAP/REGIME_MAP/MACRO_TAGS_MAP（不干涉 A/B/C/D 四大禁区）
- TIC_MAP 规模从 116 → 142 个标的
- DEEP_INSIGHTS 新增 26 条机构级投研语料
- NARRATIVE_THEMES_HEAT 新增「🏦 生息资产/现金流堡垒」主题
- STOCK_NARRATIVE_MAP、STOCK_L2_MAP 补全 Z 池所有标的

**`valuation-radar-ui/api_client.py`**（数据质量修复）：
- 新增 `_calc_ttm_div_yield()` 辅助函数：使用 yfinance `.dividends` 历史拉取过去 12 个月真实分红总额计算 TTM 股息率，适配月度/季度/年度任意付息频率
- `get_stock_metadata()`、`get_arena_a_factors()`、`get_arena_b_factors()` 三处 `lastDividendValue * 4 / price` 全部替换为 TTM 计算

**`valuation-radar-ui/pages/3_资产细筛.py`**：
- `FACTOR_ANCHORS["div_yield_z"]` 上限 8% → 12%（覆盖 Strategy 优先股 10%、JEPQ ~9%、STRC 浮动 ~11%）
- `_MOCK_ASSETS` 补充 5 条 Z 级 Mock 数据（SCHD/JEPI/O/BIL/STRF）
- Demo 模式预计算补充 Z 组：注入各标的模拟因子后走 `compute_scorecard_z()` 评分，`arena_winners["Z"]` 不再为空
- 顶部加载 `_SECTOR_MAP = _core_data.get("SECTOR_MAP", {})`
- Z 赛道排行榜上方新增子类分布彩色 pill 标签（固收/高息权益/REIT/优先股/BDC）
- 导入 `import requests` 和 `API_BASE_URL`

### Phase 2：Finviz 全市场周扫 + 侧边栏生息雷达

**新建 `valuation-radar/z_scanner.py`**：
- 基于 `finviz` 库扫描全美股高息标的（股票 >5%、ETF >3%、封闭式基金 >4%）
- 与已知 TIC_MAP + Z_SEED_POOL 做差集，只推送真正的新发现
- 按股息率降序输出，保存到 `z_scan_report.json`
- 支持 `--min-yield` 和 `--output` 命令行参数
- crontab 示例：每周日凌晨 3 点执行

**`valuation-radar/api_server.py`** 新增端点：
- `GET /api/v1/z_scan_discoveries`：返回最新扫描报告
- `GET /api/v1/sec_alerts`：代理 sec_monitor.py 查询
- `GET /api/v1/defi_yields`：代理 defi_monitor.py 拉取

**`valuation-radar-ui/pages/3_资产细筛.py`** 侧边栏新增：
- 「🔭 生息雷达」区块：展示最新扫描报告，超过 8 个折叠显示
- 「📋 SEC 新品告警」区块：展示过去 14 天的新证券注册声明

### Phase 3：SEC 监控 + DeFi 链上收益面板

**新建 `valuation-radar/sec_monitor.py`**：
- 使用 SEC EDGAR 官方免费 API（data.sec.gov），监控 6 个目标发行人（Strategy/iShares/Vanguard/JPM/Schwab）
- 关注表单：S-1/S-3/424B2/424B4/424B5 等新证券注册声明
- 无 API Key 要求，按 SEC User-Agent 规范设置请求头

**新建 `valuation-radar/defi_monitor.py`**：
- 基于 DeFi Llama 公开 API，拉取 TVL > $100M 的稳定币借贷池
- 过滤条件：主流链白名单（ETH/ARB/Base 等）、APY < 100%（排除挖矿奖励）
- 额外提供 `fetch_protocol_summary()` 获取主流协议 TVL 健康度

**`valuation-radar-ui/pages/3_资产细筛.py`** Z 赛道新增：
- DeFi 链上收益率 expander 面板：展示 Top 20 稳定币池，含梯度背景热力图，自动标注当前链上最优收益
- 明确标注"不参与 ScorecardZ 评分"

### 妥协记录
- `finviz` 库需手动安装：`pip install finviz`；周扫描脚本需通过 crontab 单独调度，不在 Streamlit 运行时自动触发
- STRF/STRK 上市时间较短（2025年），yfinance 历史 < 252 天，TTM 股息率可能基于不完整数据；已有 `len(hist) < 60` 兜底逻辑
- DeFi 面板为实时请求（非缓存），网络超时时优雅降级为离线提示
- SEC 监控仅追踪 6 个预设发行人，无法覆盖完全未知的新发行方（需定期手动补充 WATCHED_ISSUERS）

---

## 2026-04-10 | 支链开发对齐 Render 数据：RADAR_API_URL 环境变量

**背景**：同事在支链开发时，本地 `narrative.db` 与 Render 云端数据不一致，导致调试失真；但改动须合并到主链才能影响 Render 部署。

**变动**：
- `api_client.py`：新增 `RADAR_API_URL` 环境变量最高优先级覆盖机制（优先于 `USE_LOCAL_API` 和平台自动判断）。

**使用方法（支链开发时直连 Render 后端）**：
```bash
# 在 valuation-radar-ui 目录下执行
RADAR_API_URL=https://valuation-radar.onrender.com streamlit run app.py
```
本地前端直接打到 Render 后端，数据与生产完全一致，无需拉数据库、无需合并主链。

**注意**：对 Render 后端发起的写操作（词典审核、orphan 操作等）将直接影响生产数据，支链开发时须谨慎使用写接口。

---

## 2026-04-10 | 历史提案回溯 Gemini 质检 + UI 一键筛选按钮

**背景**：v15.8 的自动筛选仅覆盖新生成提案，队列中已有的 17-18 天前的历史提案（含人名、娱乐等垃圾集群）未被筛选。

**变动**：
- `api_client.py`：新增 `trigger_retroactive_screen()` 函数，调用后端 `POST /api/v1/narrative/retroactive_screen`。
- `pages/2_舆情监控.py`：
  - `import` 新增 `trigger_retroactive_screen`。
  - 「💡 新主题提案」标题行右侧新增「🔍 重新筛选（Gemini 质检）」按钮，点击后同步触发回溯筛选，完成后展示驳回/保留统计并刷新页面。

**影响**：仅限 `2_舆情监控.py` 页面的提案审批 Tab。

---

## 2026-04-09 | 叙事四象限雷达：L2板块中文化 + 标注精简

**变动**：

1. `pages/2_舆情监控.py`：在 Phase 5 散布图构建处新增 `_L2_ZH` 中英映射字典，覆盖全部 20 个 L2 板块。
2. 散点图标签、hover tooltip、叙事热度排行榜的 y 轴全部改用中文名称显示，英文原始 key 仍保留在后端数据流与 `session_state`。
3. 四象限角落标注去掉括号说明（`(热度高+加速升温)` 等），只保留 emoji + 标题，减少视觉杂乱。
4. 散点图高度从 600 调整至 660，配合中文缩短标签改善视觉间距。

**影响**：仅限 Phase 5 渲染层，不影响后端数据结构、narrative_heat_ranking session_state 写入（仍用英文 key）及 Page 3 共振逻辑。

## 2026-04-09 | 叙事-动量共振排行榜：Page 2 叙事热度排名 + Page 3 D组共振猎场

**变动**：

1. `api_client.py`：新增 `get_batch_ticker_cooccurrence(tickers, days)` 批量共现查询函数，包装逐 ticker 调用并容错。

2. `pages/2_舆情监控.py`，Phase 5「叙事四象限雷达」：
   - 在四象限散点图下方新增「叙事热度排行榜」，以水平条形图展示全部 L2 板块的叙事动量分（综合热力 × 动量加速因子），按分数降序排列。
   - 叙事动量分公式：`(0.6 × composite_heat + 0.4 × momentum_boost) × 100`，仅正动量参与加速。
   - 条形图附标各 L2 的 Top 3 L3 关键词，颜色区分 concentrated / distributed。
   - 将排行结果写入 `session_state["narrative_heat_ranking"]`，供 Page 3 D 组共振计算消费。

3. `pages/3_资产细筛.py`，D 组赛道：
   - 新增 `fetch_l2_l3_detail` 和 `get_batch_ticker_cooccurrence` 导入。
   - 在 D 组排行榜下方新增「共振猎场」面板，实现叙事 × 动量交叉验证：
     - 白盒公式展示：共振分 = ScorecardD × 叙事热度分 / 100。
     - 叙事热度分 = L2 板块热力分 × L3 匹配度（匹配度 = 共现命中 L3 词温度之和 / 全部 L3 词温度之和）。
     - 通过 `get_batch_ticker_cooccurrence()` 动态获取各 ticker 的新闻共现关键词，与 L2 下辖 L3 词做匹配，自动选取得分最高的 L2 板块。
   - Top 3 共振标的以金银铜颁奖卡片呈现，展示 D 组动量分、匹配板块、L2 热力分、L3 匹配度、叙事热度分、命中词。
   - 完整共振排行榜以 dataframe 呈现，共振分列用 YlOrRd 色阶渐变。
   - 可展开「逐标的共振归因明细」：对每个有效共振标的白盒展示完整计算链路和命中的 L3 关键词。
   - 降级方案：session_state 无数据时直接调用 `fetch_l2_l3_detail` 自行计算；叙事 API 不可用时跳过共振、ScorecardD 排名不受影响。

**设计哲学**：
- ScorecardD 三因子不变（45/35/20），共振分是独立的乘法叠加层。
- 词与标的通过新闻共现动态关联（政教分离原则），不硬编码映射。
- L2 层面打分（有完整热力指标），L3 层面匹配（提供精度系数），两层各司其职。

**跨页面数据流**：
- Page 2 写入 `session_state["narrative_heat_ranking"]` → Page 3 D 组读取。
- Page 3 具备独立降级能力，不依赖 Page 2 必须先访问。

---

## 2026-04-09 | 舆情监控：删除共振猎场（Phase 6）

**变动**：
- `pages/2_舆情监控.py`：完整移除 Phase 6「共振猎场」模块（约 760 行代码）。
  - 删除了导航栏入口 `(6, "共振猎场")`，导航栏从 6 列改为 5 列。
  - 删除 `PHASE_COLORS` 中 `6: "#E74C3C"` 配色项。
  - 删除所有 Phase 6 专属 API 导入：`get_arena_d_factors`、`get_etf_rs20d`、`fetch_narrative_sector_heat`、`fetch_cio_watchlist`、`add_to_cio_watchlist`、`remove_from_cio_watchlist`、`update_cio_watchlist_notes`、`get_alpaca_ticker_news`、`get_ticker_cooccurrence`、`get_alpaca_snapshots`。
  - 更新原理白盒介绍文字，移除对「共振猎场 Tab 6」的引用。

**原因**：功能暂时下线，页面仅保留 Phase 1–5。

---

## 2026-04-09 | 叙事四象限雷达：删除热度榜 Tab + 散点图分层显示重构

**变动**：
- `pages/2_舆情监控.py`，Phase 5「叙事四象限雷达」：
  - **删除「板块热度榜」和「热度异动榜」两个子 Tab**：移除了约 260 行代码（含热度排行表格与词频动量发散柱状图），仅保留「四象限雷达」一个 Tab。`st.tabs()` 由三元组改为单元素元组。
  - **散点图改为分层显示**：原先每个 L2 板块各自独立一条 Plotly trace（所有点混合在一张图上，颜色区分但无图例），重构为两条命名 trace：🔴 **L3单词**（heat_type=concentrated，集中度高）和 🔵 **L2词典**（heat_type=distributed，集中度低）。图表开启 showlegend=True，图例浮于图表左上角，支持点击切换可见性。
  - **统一重命名**：界面上"单词爆发型"一律改为"L3单词"，"多词共振型"一律改为"L2词典"，覆盖 caption、图例说明条、drill-down 面板的热度类型指标卡。

**影响范围**：`pages/2_舆情监控.py`，Phase 5 渲染段。后端 API 无变动。

---

## 2026-04-09 | 舆情监控导航重构：彩色步骤条可点击 + 布局精简

**变动**：
- `pages/2_舆情监控.py` 整体导航逻辑重构：
  - **「引擎原理白盒」移至最顶**：原来置于步骤条之后，现在置于步骤条之前，首屏即可折叠查看 NLP 原理说明。
  - **步骤条改为可点击导航**：原静态 HTML 步骤条 + 下方文字 Tab Bar 合并为一套基于 `st.session_state["active_phase"]` 的按钮式导航（6 个 `st.button` 横向排列），删除了 `st.tabs()` 全局 Tab，各阶段内容改为 `if active_phase == N:` 条件渲染。
  - **词典管理子 Tab 精简**：删除「📋 批量操作」和「📋 词汇档案」两个子 tab，词典管理只保留「📂 词典全景」和「🔇 噪音词管理」两个 tab；批量操作功能已内嵌在词典全景的板块卡片展开区内。

**影响范围**：`pages/2_舆情监控.py`（导航结构、session_state 依赖）

## 2026-04-09 | 批量操作整合至词典全景板块卡片

**变动**：
- `pages/2_舆情监控.py` L2管理 Tab 词典全景视图优化：
  - 每个 L2 板块卡片下方的操作展开区从原来的「添加 + 板块管理」两列布局升级为 **6 个子 tab 内联布局**：`➕ 添加 · 🗄️ 归档 · ♻️ 恢复 · 📦 迁移 · 🚫 标噪 · ✏️ 管理`。
  - **添加 tab**：支持快速添加（单个）和批量添加（粘贴文本）两种模式切换，不再需要跳转到独立批量操作 tab。
  - **归档 / 恢复 tab**：操作范围自动锁定当前板块，multiselect 从本板块词条列表中选择。
  - **迁移 tab**：以当前板块为源，从 selectbox 选择目标板块。
  - **标噪 tab**：支持「仅删除」和「删除 + 标噪」两种模式，覆盖当前板块所有词条。
  - **管理 tab**：保留原板块级操作（重命名 / 归档整板 / 彻底删除）。
  - 原「📋 批量操作」子 tab 改为导引说明页，告知用户操作已迁移，并保留全局入口作为向后兼容。
- 影响范围：仅前端 UI 组织方式变更，不涉及 API 变更。

---

## 2026-04-09 | 词典全景内联管理入口（CIO 词库管理整合）

**变动**：
- `pages/2_舆情监控.py` Tab4（L2/L3 词典全景 & CIO 管理）UI 重构：
  - **词典全景**（原 `v4_sub1`）顶部新增 `＋ 新建 L2 板块` 折叠区，取代原来需要跳转到 CIO tab 才能新建板块的操作路径。
  - 每个 L2 板块卡片下方新增 `⊕ 添加词条 · ✏ 管理` 折叠操作区，可直接对该板块执行：快速添加单条 L3 词条、重命名板块、归档板块、彻底删除板块。操作完成后自动 `rerun`。
  - **批量操作 tab**（原 `🛠️ CIO 词库管理` → 改名 `📋 批量操作`）：移除 Zone 1（L2 板块管理）三列操作区，保留 Zone 2 五个批量 L3 操作 tab（批量添加、归档、恢复、迁移、标噪）。顶部添加引导说明指向词典全景的新入口。

**目的**：减少 tab 切换成本，L2 板块管理操作从全局集中表单改为上下文内联操作，视觉更简洁。

---

## 2026-04-09 | TF-IDF 过滤旧词 + 恢复温度列

**变动**：
- `pages/2_舆情监控.py` Tab3（TF-IDF 挖掘）：在循环中 `continue` 跳过 `verdict == "protected_l3"` 的旧词命中条目，TF-IDF 表格现在只展示真正的新词。旧词已有词典覆盖，在 Tab4（旧词统计）跟踪，无需在 TF-IDF 重复展示。
- 同步恢复 `burst_ratio` 温度列（ProgressColumn，格式 `%.1fx`，最大值 10x）及对应说明文字"温度 > 2.0 = 放量信号"，上一次误删。
- `亲和置信度` ProgressColumn 未受影响，维持原样。

**影响范围**：`pages/2_舆情监控.py` Tab3 TF-IDF 子 tab

---

## 2026-04-09 | 旧词统计表格：删除情感列，新增温度列；TF-IDF 表格删除温度列

**变动**：
- `pages/2_舆情监控.py` Tab1（旧词统计）表格：删除"情感"列（`sentiment` 字段，已无分析价值），在"词频"列后新增"温度"列（`burst_ratio`，格式为 `Nx`，≥2.0 红色 / 1.0–2.0 橙色 / <1.0 灰色）。
- 温度数据来源：在 Tab1 加载时额外调用 `fetch_tfidf_terms(days=prov_days, top_k=500, show_all=True)`，构建关键词 → burst_ratio 查找表；若关键词未出现在 TF-IDF 结果中则显示"—"。
- Tab3（新词发现 / TF-IDF）表格：删除"温度"列（`burst_ratio`），同步更新 column_config 及说明文字，表格更简洁。
- CSS：删除不再使用的 `.prov-sentiment-*` 样式，新增 `.prov-temp` / `.prov-temp-hot` / `.prov-temp-warm` / `.prov-temp-cool` 样式。

**影响范围**：`pages/2_舆情监控.py`。

## 2026-04-09 | Bug Fix：Tab5 兼容后端旧字段名 sentiment_momentum

**问题**：Streamlit Cloud 上 Tab5（叙事雷达）报 `KeyError: heat_momentum`。  
**根因**：后端生产环境 `/api/v1/narrative/l2_l3_detail` 和历史快照接口仍返回旧字段名 `sentiment_momentum`，而前端已改用 `heat_momentum`，导致 DataFrame 中该列不存在。  
**修复**：在 `df_radar` 和 `df_snap` 创建后各加一行兼容 rename shim：若检测到 `sentiment_momentum` 且缺少 `heat_momentum`，自动重命名，后端部署更新后 shim 自动失效（条件不成立即跳过）。  
**影响范围**：`pages/2_舆情监控.py` Tab5 数据加载段。

---

## 2026-04-09 | UI 术语统一：热度系数 → 温度，热度动量 → 词频动量

将 `pages/2_舆情监控.py` 中所有显示标签统一：
- **热度系数**（burst_ratio）全部改为**温度**，与口语保持一致，减少混淆
- **热度动量**（heat_momentum）全部改为**词频动量**，更准确反映其本质（板块提及量的环比变化率，不是情感或热度的导数）
- 共涉及列名、caption、hover 文字、图表轴标题、metric 标签等 21 处

---

## 2026-04-09 | 四象限雷达 Y 轴：情感动量 → 热度动量

将 Tab 5 四象限雷达的纵轴从「情感动量 (VADER sentiment momentum)」替换为「热度动量 (heat momentum)」——即提及量环比变化率 `(近N日日均提及量 - 前7日日均提及量) / max(前7日日均提及量, 1)`。

**动因：** VADER 对中英混合金融标题的情感打分噪声大、不稳定，且"文章标题的平均情绪"与用户关心的"板块热度升降"并不对应。改用提及量环比后，数据源为确定性整数（文章数），信号直观可操作。

**改动范围：**
- **后端 `narrative_engine.py`**
  - `get_l2_l3_detail()` — 查询改为聚合 `mention_count` 日均值及其前置 7 天日均值，输出字段 `heat_momentum` 替代 `sentiment_momentum`
  - `get_quadrant_history()` — 历史快照 Y 轴同步改为提及量环比变化率
  - 四象限名称更新：舆论风口 → **风口正劲**、静默潜伏 → **暗流涌动**、舆论恐慌 → **见顶预警**、冷淡低迷 → **无人问津**
- **后端 `api_server.py`** — docstring 更新
- **前端 `pages/2_舆情监控.py`**
  - Tab 5 Sub-tab 1 (四象限雷达)：Y 轴标签、象限标注、hover tooltip、归因卡、drill-down metrics 全量更新
  - Tab 5 Sub-tab 2 (板块热度榜)：列标题和数值格式改为百分比
  - Tab 5 Sub-tab 3 (情绪异动榜 → **热度异动榜**)：标签、hover、x 轴标题全量更新
  - Tab 6 (共振猎场)：`sentiment_momentum` → `heat_momentum`，风口摘要卡片、信号分类、叙事预热卡片同步更新

**数据兼容：** `daily_cluster_stats.avg_sentiment` 字段保留不删，`calc_sentiment()` / `keyword_match_log` 仍正常写入文章级情感，仅前端展示维度切换。

---

## 2026-04-09 | 质检员系统 (Health Inspector Dashboard)

新增 `health_checker.py` 模块及首页质检面板，打开系统即可一目了然看到所有故障和隐患。

**检查覆盖 8 大类别 (并行执行, ~1.5s 完成)：**
1. **后端连通** — API 可达性、响应延迟检测
2. **API 契约** — 6 个关键端点状态码 & JSON 格式校验
3. **数据完整** — 本地 JSON 数据文件存在性、格式、过期检测 + 核心数据字段校验
4. **行情数据** — yfinance SPY 可用性 & 数据新鲜度
5. **依赖环境** — Python 版本、9 个必需包安装状态、导入异常捕获
6. **舆情引擎** — 引擎状态、爬虫、词典、待审积压检测
7. **页面完整** — 7 个页面 + 3 个核心模块的文件存在性 & 语法编译校验
8. **代码冲突** — Git merge conflict markers 全量扫描

**UI 设计：**
- 首页显示总览横幅（按最严重等级变色：红/橙/黄/绿）
- 5 列 Metric 卡片展示严重/错误/警告/提示/通过计数
- 按类别折叠展开，异常类别默认展开，正常类别折叠
- 侧边栏"重新质检"按钮支持手动刷新
- 结果缓存 5 分钟，不影响页面加载性能

**影响范围：** `app.py`（改）, `health_checker.py`（新增）

---

## 2026-04-09 | 今日新发现置顶 & 子tab顺序调整

在 `pages/2_舆情监控.py` 的"新词发现（TF-IDF）"面板中：
1. 将子 tab 顺序调整为"🆕 今日新发现"排第一，"📊 TF-IDF 挖掘"排第二，"🤖 gemini质检"排第三。
2. 在"今日新发现" tab 最顶部新增"质检通过词 Top-20 热度"柱状图（独立调用 `fetch_tfidf_terms(days=7, top_k=50)`），让用户进入该 tab 时立刻看到高温词热力概览，再往下浏览新词卡片详情。

---

## 2026-04-09 | 舆情监控 Tab 顺序对调与命名优化

在 `pages/2_舆情监控.py` 中对 Tab 1（原"信号溯源"）与 Tab 3（原"词汇热力"）进行位置对调，并统一优化命名，使界面展示顺序符合 NLP pipeline 的认知逻辑（先发现新词，再追踪旧词命中）。

**具体变更：**
- Tab 1（新）：**新词挖掘**（原 Tab 3 TF-IDF 自底向上发现），副标题更新为"对新词——发现、过滤、决定要不要晋升入词典；对旧词——持续监测在语料中的温度变化（爆发系数）"
- Tab 3（新）：**旧词统计**（原 Tab 1 信号溯源），副标题更新为"追踪词典中已有关键词的文章命中记录"
- `protected_l3` 质检标签：全文 5 处由"词典保护 / L3保护 / 受保护"统一改为 **旧词命中**
- Pipeline Stepper 步进器标签同步更新

**影响范围：** 纯前端展示层，无后端或 API 变更，不影响数据流逻辑。

---

## 2026-04-09 | 舆情监控页新增 NLP 流水线白盒科普面板

在 `pages/2_舆情监控.py` Pipeline Stepper 下方新增一个默认折叠的 `st.expander` 科普模块，向用户白盒化展示 NLP 流水线五层工作原理（①新闻采集层 → ②关键词匹配 → ③TF-IDF 热词挖掘 → ④LLM语义过滤 → ⑤因子聚合共振信号），采用与页面色系一致的彩色卡片网格布局，纯前端 HTML/CSS，不涉及后端或 API 变更。

---

## 2026-04-09 | GDELT DOC API 改造为差异化渠道

### 变动内容

`narrative_engine.py` 中，`fetch_news_gdelt`（DOC API）的调用策略由"全关键词重复搜索"改为"差异化的估值分析语料补充"，解决其与 GKG CSV 高度重叠、净贡献接近零的问题。

**具体变更：**
1. 新增常量 `_GDELT_DOC_VALUATION_TERMS`：20 条估值分析专用短语（`price target`、`analyst upgrade`、`EV/EBITDA`、`earnings beat` 等），这些词常见于分析师报告，但不会被 GDELT NLP 打上 `ECON_/BUS_` 主题标签，因此与 GKG CSV 真正互补。
2. 新增常量 `_GDELT_DOC_MIN_GKG_COUNT = 200`：GKG 阈值保护。
3. 改造 `fetch_all_news()` Layer 1-B 路由逻辑：
   - GKG ≥ 200 条时：DOC API 仅搜索 `_GDELT_DOC_VALUATION_TERMS`（差异化分析师语料）
   - GKG < 200 条时：DOC API 退回全关键词兜底搜索（GKG 数据稀疏应急）

**影响范围：** 仅 `valuation-radar/narrative_engine.py`，不涉及数据库结构或 API 接口变更。正常运营日 DOC API 请求次数大幅减少（从 `ceil(len(keywords)/10)` 批次降至 `ceil(20/10) = 2` 批次），节省约 8 秒/批次的限速等待。

---

## 2026-04-09 | GDELT 主流水线改为每日自动触发

### 变动内容

在 `valuation-radar/api_server.py` 新增 `DailyPipelineScheduler` 后台线程，随服务启动自动拉起。线程每 10 分钟检查一次当前 UTC 时间，在首次到达 UTC 08:00（北京时间 16:00）时自动触发一次 GDELT + Google News RSS 主流水线，确保当天语料完整落库后再运行，避免时差导致的 DATA_MISSING 错误。可通过环境变量 `DAILY_PIPELINE_UTC_HOUR` 调整触发时刻。调度线程的启动位置置于 `_run_narrative_pipeline_bg` 函数定义之后，规避启动期竞态风险。手动触发接口 `/api/v1/narrative/run_pipeline` 保持不变，两套机制共享同一个 `pipeline_status` 互斥锁，不会重复跑。

---

## 2026-04-09 | 信号溯源面板信息源单一假象修复

### 问题描述

用户在「1·信号溯源」面板看到第一页结果几乎全是 Google RSS，误以为其他信息源（GDELT GKG、Finnhub、Alpaca、Polygon.io）没有数据。

### 根因

`keyword_match_log` 中，各信息源的 ID 由插入顺序决定：
- 守护进程源（Finnhub/Alpaca/Polygon）连续运行，早于 NLP 流水线写入，ID 较低
- GDELT GKG 在流水线中第一步 batch 插入，ID 居中
- **Google RSS 在流水线最末尾插入，ID 最高**

原 `get_match_log` 使用 `ORDER BY id DESC`，第一页 50 条几乎全是 Google RSS，其他源需翻到后面几页才能看到。本地验证：`ORDER BY id DESC LIMIT 50` → google_rss=34 + polygon=16，其余三源完全不可见。

### 修复

**`valuation-radar/narrative_engine.py` — `get_match_log`**
- 排序改为 `ORDER BY match_date DESC, _rn, news_source`，其中 `_rn = ROW_NUMBER() OVER (PARTITION BY match_date, news_source ORDER BY id DESC)`。轮询交替保证每页包含各源等比例文章（5源时每页各取10条），单源筛选时退化为正常时间倒序。
- 响应新增 `source_counts` 字段（`{source_key: count}`），供前端展示各源总量。

**`pages/2_舆情监控.py` — Tab 1**
- 表格上方新增「信息源覆盖」彩色徽章行，显示当前筛选条件下各信息源的文章匹配总数，让用户一眼确认全部信息源均有数据。

---

## 2026-04-08 | Render Disk 冷启动修复 — 词典状态误判 + API 超时优化

### 背景

后端 Render 服务新挂 Persistent Disk 后，重部署导致 `narrative.db` 被写入临时路径，磁盘上的词典为空。同时发现前端在 Render 冷启动（30-60 秒）期间，15s 请求超时触发 `degraded` 错误，进而被误判为「词典为空」并渲染「快速建库」横幅，对用户产生误导。

### 改动

**`api_client.py`**
- `_narrative_get` timeout：15s → **45s**（覆盖 Render 免费版冷启动窗口）
- `_narrative_post` timeout：30s → **60s**（NLP 流水线触发等长操作留余量）

**`pages/2_舆情监控.py`**
- `has_active_library` 判断由 `active_non_seed_count > 0` 改为 `total_active_count > 0`：种子词典（312 条）就位即视为已建库，不再要求必须有人工批准的词条
- 新增 `_dict_api_ok` 防御：`degraded=True`（API 超时/502）时跳过「快速建库」横幅，不将网络错误误判为词典为空

### 根因总结

| 层 | 原因 | 修复 |
|---|---|---|
| DB 层 | Render disk 新挂，`seed_dictionary()` 未在持久化路径运行 | 手动调用 `push_dict_to_render.py` 的 `force_seed` 接口补种 312 条 |
| API 层 | `dictionary_stats` 只统计 `source != 'seed'`，种子词条被忽略 | 后端新增 `total_active_count` 字段（见后端 DEV_LOG）|
| 前端层 | Render 冷启动超时 → `degraded` → 误触「快速建库」逻辑 | timeout 延长 + degraded 时直接跳过判断 |

### 结果

- Render 词典：22 个 L2 板块，312 条种子词条
- 冷启动期间前端不再误显「词典为空」横幅
- 词典管理（Tab 4）可正常展示完整 taxonomy

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

---

## 2026-04-09 | 叙事引擎服务端批量历史回填

### 背景
四象限雷达历史快照仅有约 16 个日期，数据稀少导致历史规律难以验证。需要回填过去半年的叙事快照数据，但旧方案（本地脚本轮询 API）要求本地机器持续在线，无法睡觉挂后台跑。

### 改动

**`valuation-radar/api_server.py`（后端）**
- 新增 `backfill_status` 全局状态字典（tracking: running / total / done / skipped / failed / current_date / finished_at / last_error）。
- 新增 `_run_batch_backfill_bg(start_date_str, end_date_str, force_missing)` 后台线程函数：内部自主循环遍历工作日，自动跳过已有快照，等待普通流水线空闲后再触发 `run_full_pipeline`，单日日间冷却 3s，遇到普通流水线占用最多等待 15 分钟。
- 新增 `POST /api/v1/narrative/batch_backfill` 端点：接受 `days / start_date / end_date / force_missing` 参数，一次触发后 Render 自主跑完全部日期，不依赖客户端保持连接。
- 新增 `GET /api/v1/narrative/batch_backfill_status` 端点：实时返回回填进度供前端轮询。

**`valuation-radar-ui/api_client.py`（前端 API 层）**
- 新增 `trigger_batch_backfill(days, start_date, end_date, force_missing)` 函数。
- 新增 `fetch_batch_backfill_status()` 函数。

**`valuation-radar-ui/pages/2_舆情监控.py`（UI 侧边栏）**
- 在「NLP 流水线」与「孤儿院」之间新增「📦 历史批量回填」区块。
- 提供「回填天数」滑块（30-365 天，默认 180 天）+ `DATA_MISSING` 强制重跑复选框 + 启动按钮。
- 回填运行期间显示进度条（完成百分比 + 当前日期 + 跳过/失败计数），每 15 秒自动轮询刷新。
- 完成后展示成功/跳过/失败汇总，并清空 cache 触发数据刷新。

### 影响范围
跨项目改动：后端 API + 前端 API 客户端 + UI 页面。回填任务完全在 Render 服务端执行，客户端关闭后不影响进度。
