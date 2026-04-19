# DEV LOG — valuation-radar-ui

---

## 2026-04-19 | ScorecardA Harness 定稿同步：A 组前端权重 45/15/10/30 → 20/10/40/30

**动因**：后端 `valuation-radar` 仓 commit `a95015b`（2026-04-18 夜）经 A 组 Harness 三阶段门控回测（OOS 87.8% / 扰动 76.5%）将 ScorecardA 权重定稿为 **F1=20 / F2=10 / F3=40 / F4=30**，DCR 升为首要因子（市场级风控由 SPY 熔断接管）。但前端 Page 3「A 级压舱石 — 避风港防御指数」赛道仍展示旧权重 45/15/10/30，错位 14 小时主理人才发现。

**根因（事后复盘，订正昨日错标签）**：当时执行后端 commit 的 AI 没有自查前端是否存在硬编码镜像副本，**既有 cursor rules 也未明确覆盖此场景**——`data-consistency.mdc` 约束 4「跨层契约显式化」只管 `_ARENA_SAVE_N` 类后端常量与 `SharedKeys` session_state key，不管 Scorecard 权重的前端展示副本；`core-protocols.mdc` 红线第 7 条只规定跨仓库改动的推送顺序，不强制提醒前端有无副本要改。已于本次同步在 `valuation-radar/.cursor/rules/core-protocols.mdc` 红线追加第 9 条，机械化触发条件 + 具体 grep 清单，避免下次再犯。

**改动**（纯 UI 文案 + 顶部胶囊百分比，不影响实际评分；评分仍由后端 `_api_get_arena_a_scores` 走最新 ScorecardA）：
1. `pages/3_资产细筛.py:127-128` `ARENA_CONFIG["A"]["weights"]` dict：`0.45/0.15/0.10/0.30` → `0.20/0.10/0.40/0.30`（顶部胶囊百分比由 `cfg_a["weights"]` 动态读取，自动同步）
2. `pages/3_资产细筛.py:134` factor_labels：`spy_corr_inv` 标签从 "宏观对冲 (SPY相关性倒数)" 改为 "宏观对冲 (DCR下行捕获)"，与后端 F3 实际口径一致
3. `pages/3_资产细筛.py:139-143` logic 四行 tooltip：①②③ 权重数字同步为 20%/10%/40%；末行新增一句说明 Harness 数据驱动 + SPY 熔断接管市场级风控
4. `pages/3_资产细筛.py:2682-2685` 底层公式 expander：`Score_A` 系数 (45,15,10,30) → (20,10,40,30)；F3 高亮加粗（首要因子）；新增脚注一行说明 OOS/扰动通过率与 SPY 熔断（−12% 清仓 / −6% 解除）

**验收路径**：Streamlit Cloud 重新部署后 Page 3 → 「A 级：压舱石 -- 避风港防御指数」赛道 → 顶部胶囊应显示 `极限抗跌 20% / 现金奶牛 10% / 宏观对冲 40% / 带鱼质量 30%` → 展开 "📐 底层因子公式（ScorecardA v4 满分 100）" 核对新公式与脚注。

**不改动**：B/C/D/Z 四组权重与文案零改动；ScorecardA 评分逻辑（窗口/阈值/熔断）已在后端 `core_engine.py` 落地，前端不参与计算。

---

## 2026-04-18 | ScorecardA v3 前端文案对齐：weights/tooltip/底层公式三处同步至 45/15/10/30

**动因**：后端 `ScorecardA` v3 本次调权（F4 恢复 30%、s5 主导 0.50，详见 `valuation-radar/DEV_LOG.md` 同日条目）的同时，发现前端长期存在**三处权重文案互不一致**：
- `pages/3_资产细筛.py:127-128` weights dict：`30/20/20/30`（旧 v1 风格）
- `pages/3_资产细筛.py:139-142` tooltip 文案：`30/20/20/30`
- `pages/3_资产细筛.py:2682-2685` 底层公式 expander：`35/25/20/20`（更老的历史版本，完全不对）
- 后端 v2 实际跑：`45/20/20/15`
- 四套权重同时存在，违反 `.cursorrules` 约束 4 "跨层契约显式化"。

**改动**（纯 UI 文案，不影响评分逻辑，前端不参与计算）：
1. `pages/3_资产细筛.py:127-128` weights dict：`"max_dd_inv": 0.45, "fcf_yield": 0.15, "spy_corr_inv": 0.10, "ribbon_quality": 0.30`（供顶部胶囊百分比渲染用）
2. `pages/3_资产细筛.py:139-144` tooltip 四行文案权重改为 45%/15%/10%/30%，④ 明示带鱼内部 `0.15·s1 + 0.20·s2 + 0.15·s3 + 0.50·s5`
3. `pages/3_资产细筛.py:2681-2695` 底层公式 expander 完全重写：顶层 4 因子 + F4 内部展开，s5 高亮（橙色 0.50 权重），标题加 v3 版本号

**验收路径**：Page 3 刷新 → A 组顶部胶囊应显示 `极限抗跌 45% / 现金奶牛 15% / 宏观对冲 10% / 带鱼质量 30%` → 展开 "📐 底层因子公式（ScorecardA v3 满分 100）" 核对新公式 → tooltip 新文案。

**不改动的东西**：`cfg_a["weights"]` 只喂 UI 胶囊百分比（line 2195/2659 只读 int(wval*100)），不参与任何本地计算；真正评分仍由 `_api_get_arena_a_scores` 走后端 ScorecardA v3。B/C/D/Z 文案零改动。

---

## 2026-04-18 | 修复回填后 NameError：`_history` 页面级变量未定义，提前抓快照

**症状**：Page 3「A 级压舱石 — 历史月度 Top 10」区块，点「🔄 回填历史数据」→ 绿字 `回填完成！已写入 60 个月的历史档案` 正常弹出 → 紧接着整页红 traceback：
```
File "/mount/src/valuation-radar-ui/pages/3_资产细筛.py", line 3610, in <module>
    _old_hist  = _history  # 回填前快照（页面级变量）
NameError: name '_history' is not defined
```

**根因**：`_history = _load_arena_history()` 定义在 line 3640，**在** 回填按钮处理块（3590-3635）**之后**。Streamlit 按钮点击触发整页 rerun，自上而下执行到 3610 时 `_history` 尚未赋值，直接 NameError。2026-04-16 F4 改造引入 B/C/D/Z 等价性断言（新旧榜单比对）时，假定 `_history` 是"回填前快照"，**没意识到页面顺序**——回填按钮块跑在 `_load_arena_history` 之前。前序 DEV_LOG `2026-04-18 修复回填"假 502"` 只闭合了 `.clear()` 链路，没捕获到这个紧挨着的 NameError（主理人把红字误认成同一个问题）。

**修复**（`pages/3_资产细筛.py`，最小化）：
- 在 `if _do_backfill:` 进入 spinner **之前**先显式 `_old_hist_snapshot = _api_fetch_history() or {}` 抓一份真实快照；
- 等价性断言里 `_old_hist = _old_hist_snapshot`，不再依赖页面末段才赋值的 `_history`。

**不改动的东西**：`_history` 在页面 3640/3787/3790… 处的常规展示逻辑不动；`_api_fetch_history` 的缓存行为不动（60s TTL + push 后主动 `.clear()`）。

**遗留**：Render 日志里密集刷 numpy `RuntimeWarning: invalid value encountered in subtract @ _function_base_impl.py:2882`（`X -= avg[:, None]`）——这是 `corrcoef`/`cov` 在 NaN/Inf 输入上的告警，不 fatal；本次未处理，留给下一条处理后端 `ScorecardA`/`ScorecardD` 相关性计算的输入清洗。

---

## 2026-04-18 | 同步 ScorecardA F4 s4→s5 改造前端说明文案

**改动**：`pages/3_资产细筛.py` A 组 tooltip 文案中"价格贴轨度"改为"MA60斜率正值"，与后端 `core_engine.ScorecardA` s5 新子项对齐；无逻辑改动，仅 UI 文案同步。

## 2026-04-18 | 修复回填"假 502"：fetch_arena_history 补 @st.cache_data，兑现 DCP 约束 5

**症状**：主理人报 Page 3「回填历史数据」失败，toast 文案 `502 Server Error: Bad Gateway`。实际打 Render 日志看，`POST /api/v1/arena/backfill_score 200 OK`、后续 `/api/v1/arena/history/batch`、`/api/v1/conviction_state/A|B` 全部 200；前端页面也先弹出绿字 `回填完成！已写入 60 个月的历史档案`——**回填其实完全成功**。但紧接着一个红色 traceback 盖满整页：`AttributeError` 指向 `pages/3_资产细筛.py:3608` 的 `_api_fetch_history.clear()`。用户视觉上只看到红报错和上一次 502，误以为"持续 502"。

**根因（跨文件契约脱节）**：
- `pages/3_资产细筛.py:3608` 按 `.cursorrules` DCP 约束 5「push_* 成功后必须调对应 fetch_*.clear() 清缓存」的要求调 `.clear()`。
- 但 `api_client.fetch_arena_history`（api_client.py:663）是**裸函数**，从未挂 `@st.cache_data` —— `.clear` 属性不存在。
- 首次 `_do_backfill` 因 Render 冷启动网关抖动撞过一次真 502，主理人重试后走到 200，完整跑完回填；偏偏在"写后校验清缓存"这步把整页崩了。之前 DEV_LOG 2026-04-13 条目 L182 的 TODO「给 push_arena_history_batch 补 fetch_arena_history.clear() + 重读比对」**默认 fetch_arena_history 有 .clear()，从未落地**。

**修复**（1 行装饰器，api_client.py:663）：
```python
@st.cache_data(ttl=60, show_spinner=False)
def fetch_arena_history() -> dict:
```
- `.clear()` 属性立即可用，Page 3 回填成功后的写后失效链路闭合；
- TTL 60s 顺便给 Page 3/4/5 rerun 节流（Streamlit 每个 widget 变化都 rerun，原先每次实打实 GET `/arena/history`），写入侧由 `_api_fetch_history.clear()` 主动失效保证跨页一致。

**不改动的东西**：
- Page 4 / Page 5 调 `fetch_arena_history()` 处零改动——无参缓存透明生效，行为仅从"每次 rerun 发 HTTP"变为"60s 内秒回"，不影响数据正确性。
- Render 后端零改动。

**遗留 / 未来**：
- 502 本身仍可能复现（Render 冷启动网关抖动的物理属性），但不再致命——只要重试一次进入 200 路径，页面就会正确落地 `st.success` 而不再被 AttributeError 盖住。如果后续证实 502 **持续复现**（而非本次的瞬时冷启动），再考虑给 `arena_backfill_score` 加 502/503/504 指数退避重试、并把 `_CHUNK` 从 12 降到 6。
- DCP 约束 5 扫雷 TODO：全仓 grep `@st.cache_data` + 对应 `fetch_*` 函数，确保每个跨页共享读函数都挂了缓存，别再出现"契约约定 .clear() 但实装漏挂装饰器"的脱节。

---

## 2026-04-18 | A 组排行榜"蓝色条全缺"修复：前端 fcf_yield 透传给后端 ScorecardA

**症状**：P0b curl_cffi 修复上线后数据回来了，但 24 位参赛选手的 A 组因子贡献堆叠条**全部缺少 F2 股息/FCF 收益率（蓝色）**。后端 `/api/v1/arena/score_a` 返回的 `score_fcf` 对所有 ticker 恒为 `0.0`。

**根因（跨前后端契约断层）**：
- `ScorecardA.score()`（`core_engine.py:933`）从 `meta.get(ticker, {}).get("fcf_yield", 0.0)` 取 FCF。
- 后端 `/api/v1/arena/score_a` 端点（`api_server.py:3735`）把 `payload.meta_data` 原样塞进 `sc.score(..., payload.meta_data, ...)`。
- 但前端 `api_client.get_arena_a_scores` POST 时写死 `"meta_data": {}`（空 dict）——于是每个 ticker 的 `fcf_yield` 回落到 0，F2 得分恒为 0，蓝色条视觉消失。
- 讽刺的是：前端 `get_arena_a_factors` 早已拉到 `fcf_yield`（还渲染在 A 组表格"FCF 收益率"列里），**只是没传回后端**。

**修复**（最小改动，纯前端）：
1. `api_client.py:884-913`：`get_arena_a_scores` 第二参数 `meta_data_hash: str` → `meta_data_json: str`（语义更清晰），函数内 `json.loads` 还原 dict 再 POST。`@st.cache_data` 的 cache key 仍然 hashable（字符串），4 小时内 tickers 不变则命中缓存。
2. `pages/3_资产细筛.py:2714-2733`：调 `_api_get_arena_a_scores` 前先把 `_factors_a` 里每个 ticker 的 `fcf_yield` 摘出来打包成 JSON：
   ```python
   _meta_for_a = {t: {"fcf_yield": float(_factors_a.get(t, {}).get("fcf_yield", 0.0))} for t in df_a["Ticker"]}
   _meta_json_a = json.dumps(_meta_for_a, sort_keys=True)
   _new_a_result = _api_get_arena_a_scores(tuple(...), meta_data_json=_meta_json_a)
   ```

**影响**：A 组堆叠条开始显示蓝色（F2），总分会相应抬升（F2 权重 20%）。后端无改动，无需 Render 重启。

**长期风险 / 留痕**：
- **契约脆弱**：`meta_data` 走字符串 JSON 穿透 `@st.cache_data` 是个 workaround；未来若 ScorecardA 再新增因子依赖的字段（如 sector / mcap），得同步扩 JSON schema，容易遗忘。更干净的做法是后端 `/api/v1/arena/score_a` 自己拉 `get_stock_metadata(tickers)` 兜底，让前端只传 tickers——但这会在 Render 引入额外一次 `yf.Ticker.info` 调用（反爬最严的 endpoint）。取舍留给未来重构。
- 前端仍直接调 yfinance 拉 fcf_yield，违反"物理隔离"原则，和 P0b 遗留的长期债同源。后端 `/api/v1/arena/factors` 迁移仍未完成。

---

## 2026-04-18 | 启用 curl_cffi 浏览器指纹，绕 Yahoo Finance 云 IP 401 反爬（前端）

**配套后端同 commit**：`valuation-radar befb6d0`，两仓独立但策略同构。

**症状**：Streamlit Cloud 前端日志堆满 `HTTP Error 401: Invalid Crumb`；Page 3 资产细筛 A 组排行榜得分全 0 且点任何"清除缓存"按钮都救不回来；后端 Render 服务反复 `Shutting down`。初步以为是 `@st.cache_data` 毒化空字典，排查后发现**根源更深**——Yahoo 2026-04 升级 Crumb v2 反爬，对云 IP 全面封禁，yfinance 默认 session 全 401。

**历史遗留问题暴露**：`.cursorrules` 第 5 条规定"前端严禁存放业务逻辑"，但 `api_client.py` / `pages/1_宏观定调.py` / `pages/3_资产细筛.py` / `pages/5_个股择时.py` 等多处直接 `yf.download` / `yf.Ticker()` 拉 yfinance。这是 V14 前的架构遗留，本次反爬事件把它暴露出来——前端 Streamlit Cloud 和后端 Render 同时被封，得前后端**同步**上浏览器指纹补丁。

**修复**（跨仓全量 P0b）：
1. 新增 `_yf_session.py`：与后端同构的工具文件，`YF_SESSION = curl_cffi.requests.Session(impersonate="chrome")`，curl_cffi 缺失时降级 None（yfinance 自建默认 Session，向后兼容）。
2. `requirements.txt`：`yfinance` → `yfinance>=1.3.0`，新增 `curl_cffi`。
3. 所有业务/诊断文件 yf 调用处加 `session=YF_SESSION`：
   - `api_client.py`：13 处（2 × `yf.download` + 6 × `yf.Ticker(t)` + 5 × `yf.Ticker("SPY")`）
   - `pages/3_资产细筛.py`：1 处 `yf.download`
   - `pages/1_宏观定调.py`：1 处 `yf.download`
   - `pages/5_个股择时.py`：2 处 `yf.Ticker`
   - `health_checker.py`：1 处 `yf.Ticker("SPY")`（诊断路径也补齐，避免 health 页误报）

**技术债记录**：前端直连 yfinance 违反物理隔离原则，但本次不做大重构；待 Page 5 风控模块动工时一并把 `api_client.py` 的 `get_arena_X_factors` 全部下沉到后端 `/api/v1/arena/factors` 统一端点（已在 TODO）。

**短期未来风险**：curl_cffi 的 Chrome 指纹若被 Yahoo 进一步识别，本方案会再次失效，届时需切 Polygon.io / Alpha Vantage 付费 API。

---

## 2026-04-18 | 修复 ScorecardA 评分"毒化缓存"陷阱（静默失败 + 30 分钟空字典）

**症状**：用户报告 A 组完整排行榜 24 个选手得分全为 0，点"仅清除当前页缓存"和"清除所有页面缓存"均无效，toast 提示"ScorecardA 后端不可达，得分置零"。直接 `curl https://valuation-radar-server.onrender.com/api/v1/arena/score_a` 返回 `success=true` + 24 个真实评分，Render 日志也有 `POST /api/v1/arena/score_a 200 OK`——后端完全健康。

**根因（违反 `.cursorrules` 第 8 条"禁止静默失败"）**：`api_client.get_arena_a_scores` 的 `except Exception:` 吞掉所有错误并返回 `{"scores": {}, "breakdowns": {}}`，而外层套着 `@st.cache_data(ttl=1800)`——**空 dict 被缓存 30 分钟**。Render 冷启动 / 瞬时网络抖动只要命中一次，用户就要盲等半小时；即使手动 clear 缓存，下一次请求若再次撞到抖动，又会被毒化。且 `except` 未打印任何错误信息，根本无法定位真实故障（`SSLError`/`JSONDecodeError`/`ReadTimeout` 被一锅端）。"仅清除当前页缓存"按钮也漏清了 `get_arena_a_scores` 自身。

**三步最小改动**：

1. **`api_client.py:884-901`**：`get_arena_a_scores` 去静默化——失败/`success=false`/`scores` 为空时一律 `raise RuntimeError`（Streamlit 对抛异常的调用不缓存），彻底杜绝毒化。`timeout=120` → `30`（Render 冷启动最多 30s，120s 徒增用户盲等）。加 `show_spinner=False`（调用方已有 `st.spinner`）。

2. **`pages/3_资产细筛.py:2712-2723`**：调用处补 `try/except Exception as _score_exc`，捕获后把 `type(_score_exc).__name__` + 前 140 字错误透出到 toast，业务侧仍兜底到 `{"scores": {}, "breakdowns": {}}` 走原有"得分置零"分支。下次再踩坑会直接看到真实错因（`ConnectionError` / `JSONDecodeError` / `ReadTimeout` / `SSLError`），不再抓瞎。

3. **`pages/3_资产细筛.py:2359-2369`**：「🔄 仅清除当前页缓存」按钮补上 `_api_get_arena_a_scores.clear()`。用户手动救急不必再依赖"清除所有页面缓存"这个核弹。

**遗留 TODO**：若后续证实 B/C/D/Z 也有类似 "cached API 封装 + 静默 except" 组合，按同模板重构；此次按最小化编辑原则仅修 A 组（症状落点）。

---

## 2026-04-18 | 熔断下沉：拆除 Page 3 选股端扣分，A 组排行榜改用后端 breakdowns

**决策背景**：熔断（回撤/趋势/估值）属于时点风险管控，语义上属于"择时"而非"选股"。V14 ABCD 重构时直接把熔断扣分写死在 Scorecard 里，导致 A 组排行榜出现负分、条形图归一化错位，且 PFE/AAPL/PBR 等 FCF 扎实但近期回撤较大的标的被系统性压制。

**删除的 5 处扣分（core_engine.py）**：
1. `ScorecardA.score`：删 `total_score -= 40`（abs_dd > 0.25 触发）
2. `ScorecardB.score`：删 `total_score -= 30`（3Y 回撤 > 25%）和 `total_score -= 20`（跌破年线）
3. `ScorecardC.score`：删 `total_score -= 30`（跌破 MA60）
4. `ScorecardD.score`：删 `total_score -= 30`（跌破 MA20）
5. `_build_result`：删 `score -= 20.0`（年线乖离 > 80%）

**保留的内容**：所有 `status`/`reason` 标签保留（`🌋 回撤超标` / `🌋 估值熔断` 等），供 UI 展示用。每个 Scorecard 加 `np.clip(0, 100)` 保底。

**ScorecardA 诊断透传**：`score()` 返回 dict 新增 `_diag` 键，包含 `score_dd/score_fcf/score_dcr/score_ribbon/max_dd_3y/status/reason`。`/api/v1/arena/score_a` 端点同步扩展返回 `breakdowns` 字典。`api_client.py` 的 `get_arena_a_scores` 改为返回 `{scores, breakdowns}`。

**前端改动（pages/3_资产细筛.py）**：
- A 组因子分改为直接取后端 breakdowns，废除原 min-max shadow 归一化方案
- `最大回撤_raw` 改用 3Y 窗口（与 ScorecardA F1 同口径），降级时回退 1Y 值
- 新增 `熔断状态` 列；最大回撤单元格 `🌋` 标签 + tooltip 提示
- `_render_leaderboard` 归一化锚从 `竞技得分.max()` 改为 `因子分加总.max()`，消除负分错位

**⚠️ 技术债 - Page 5 持仓风控模块（TODO）**：
熔断逻辑已从选股端剥离，接收方 Page 5 尚未建立。将来需补充以下持仓择时风控：
- 持仓中 A 组标的触发 3Y 回撤 > 25%：发出减仓预警
- 持仓中 B/C 组标的跌破 MA60/MA250：触发"趋势破坏"预警
- 年线乖离 > 80%：触发"估值熔断"预警，建议切现金或对冲
- 实现入口建议：Page 5 新增"持仓风险扫描"区块，遍历当前 leaders 列表，逐一检查上述条件

**操作指引（主理人在 Render 执行）**：
部署新代码后，删除 Render 端 `conviction_state.json` + `arena_history.json`，在 Page 3 触发一次完整回填（6 片 × 12 月），让信念状态从干净起点重建。

## 2026-04-17 | 回填端点分片调用，修复 Render 30s 超时 502

**根因**：`/api/v1/arena/backfill_score` 单次请求循环处理最多 72 个月（60 + 12 warmup）× 全标的，计算时间远超 Render 反向代理 30 秒超时，返回 502 Bad Gateway。

**改动**：
- `valuation-radar/api_server.py`：`ArenaBackfillRequest` 新增 `init_conv_state_a/b`、`init_conv_holders_a/b`、`init_prev_grades_map` 五个可选字段，handler 用其作为初始状态（默认空值向后兼容）；响应增返 `prev_grades_map`。
- `valuation-radar-ui/api_client.py`：`arena_backfill_score` 改为每片 ≤ 12 个月分片调用，信念状态与 `prev_grades_map` 在片间传递，结果合并后返回，对调用方（`_backfill_arena_history`）完全透明。

**影响**：72 个月回填拆为 6 次请求，每次 < 25s，无需修改 Render 配置或调用方代码。

## 2026-04-17 | Arena 评分引擎后移（PR B：前端切换 + 等价性校验）

**根因**：`pages/3_资产细筛.py` 同时维护着与后端 `core_engine.ScorecardA` 分叉的前端影子打分代码（旧公式 30/20/20/30，1 年回溯，SPY 相关性），回填路径从未用上 commit c326d7d 的抗噪重构成果。

**本次改动**：
- `_backfill_arena_history` 全面重写：删除 350 行原始因子预计算 + 打分守擂段，改为一次 HTTP 调 `POST /api/v1/arena/backfill_score`，服务端循环 N 个月，前端只遍历响应写 `_record_arena_history`
- A 组实时路径：删除 `compute_scorecard_a`（旧公式），改为调 `POST /api/v1/arena/score_a`（ScorecardA 新公式：45/20/20/15，3年最大回撤，2年 DCR）；后端不可达时得分置零并 toast 告警
- 新增 `arena_backfill_score()` + `get_arena_a_scores()` 封装函数至 `api_client.py`
- 新增 import `arena_backfill_score as _api_arena_backfill_score` + `get_arena_a_scores as _api_get_arena_a_scores`
- 回填完成后加等价性断言：B/C/D/Z Top3 新旧对比，分差前 5 标的以红字展示

**B/C/D/Z 实时路径现状**：同公式、无正确性问题，前端降级副本暂保留（待后续 PR 清除，届时删除 `compute_scorecard_b/c/d/z` + `FACTOR_ANCHORS` + 共享常量）

**影响范围**：`pages/3_资产细筛.py`（回填函数、A 组实时路径、import）、`api_client.py`

---

## 2026-04-17 | A 组因子抗噪重构 + 换仓归因诊断 + 净收益标注

**背景**：A 组 15 次换仓收益不佳。根因定位：ScorecardA 全用 1 年窗口，而 B 组用 3 年窗口，月间噪声放大约 2.5 倍；F4 Ribbon 权重 30% 叠加 60 天内部窗口，是最大噪声源。

**Page 4 新增换仓归因 expander（`pages/4_资产调研.py`）**：
- 在"历史月度 Top-N"表格下方新增"🔍 换仓归因 — 逐月上位/下位原因" expander。
- 表格列：月份 / 赛道 / 事件类型（留任/挑战上位/新晋/空位填补） / 上位者 / 被替换者 / 信念值 / 分差 / 噪音标记。
- 分差 = 上位者信念 − 被替换者信念 − 守擂优势（A=10, B=8）；分差 < 5 标红"⚠️ 噪音换仓"，≥ 20 标绿"✅ 基本面换仓"。
- C/D/Z 赛道用 factor score 代替 conviction，不扣守擂优势。
- 顶部汇总统计：总换仓次数、A/B 信念驱动次数中的噪音/基本面占比。

**Page 5 新增摩擦净收益（`pages/5_个股择时.py`）**：
- 侧栏新增"💸 摩擦成本参数"区块：佣金率（默认 0.03%）+ 滑点率（默认 0.10%），可调 0–0.5%，slider 带 help 提示。
- 公式：单次摩擦 = 2 标的 × 2 腿 × (佣金 + 滑点)；总摩擦 = 换仓次数 × 单次摩擦。
- A 组和 B 组 KPI 区（换仓次数 metric 正下方）各增一行 `st.caption` 标注净收益和摩擦成本明细。

## 2026-04-17 | Page 5 新增 B 组累计收益率图平行栏目

**变动内容**：在 `pages/5_个股择时.py` 的"A 组累计收益率图" section 之后，新增结构完全对称的"B 组累计收益率图" section。

- 辅助函数 `_build_a_slot_segments` 重命名为 `_build_slot_segments`，加入 `slot_assignments`/`tm_months` 显式参数；`_build_stitched_kline_fig` 加入 `price_cache`/`name_map` 参数；`_calc_slot_stats` 加入 `price_cache` 参数，彻底去除闭包对 `_a_*` 的依赖。
- 新增 `_b_slot_assignments`、`_b_streaks_full`、`_b_slot_weights`、`_b_price_cache` 四份 B 组前置数据，基于 `_tm_hold["B"]` 与 `_compute_streaks_p5("B", _buffer_n)` 计算，价格缓存单独拉取。
- B section 包含：header/caption、KPI 四列（左列/右列总收益、B 级合成总收益、换仓次数）、回撤三列、信念倾斜 caption、左/右/合成三 tab，独立使用 `b_weight_mode` key 和 `b_slot0/1/combined_chart` key。
- 守擂缓冲区 Top-N 控件唯一（B section 复用顶部已有的 `_buffer_n`，不新增控件）。
- **影响范围**：纯前端展示层，无后端 API 变动，无数据流变动，无 `DATA_FLOW.md` / `DATA_CONSISTENCY_PROTOCOL.md` 变动。

## 2026-04-17 | Page 4 / 5 arena_history 降级静默失败告警（约束 2 补丁）

**触发现象**：主理人在 Page 5 切换"合成权重"后发现 A 组累计收益率图和 Page 4 的 Top-N 持仓榜显示内容不一致，怀疑 Page 5 又读回了本地 JSON。

**诊断过程**（按 `.cursorrules` 真相源判别协议）：
1. `git config user.email` = `z@yang-yun.com`、分支 `main` —— 主理人场景，真相源 Render。
2. `curl https://valuation-radar-server.onrender.com/api/v1/arena/history` → `{"success":true,"history":{}}`，**后端 `arena_history` 表当前为空**。
3. `curl /api/v1/screen/results` → `data` 里也没有 `A/B/C/D` leaders。
4. 本地 `data/arena_history.json` 最后修改 4-08 21:49，61 个月 snapshot 老数据。

**根因**：Page 4 / 5 的 `fetch_arena_history()` 拿到空字典后，**静默 fallback 到本地陈旧 JSON**，没有任何红字提醒，用户被"Page 3 当前 session 写入的 `p4_arena_leaders`"与"Page 5 渲染的本地快照"并存的假象误导，误以为 Page 5 数据源比 Page 4 落后。

**违反的硬约束**（见 `../valuation-radar/DATA_CONSISTENCY_PROTOCOL.md`）：
- 约束 2（禁止静默失败）：降级路径没打 `fallback=true` 标签，没 `st.toast` 红字。

### 本次补丁（仅改前端告警逻辑，不掩盖后端空表的真问题）

1. **Page 5 `pages/5_个股择时.py`**：`fetch_arena_history()` 返回空后，fallback 本地 JSON 时读取文件 mtime，触发 `st.toast` + `st.error` 红字，明确告知"正在使用 mm-dd HH:MM 的陈旧快照"，并引导去 Page 3 重跑或查 Render。
2. **Page 4 `pages/4_资产调研.py`**：同样的告警模板，覆盖历史 Top-N 换仓表路径。
3. **Page 6 暂不改**：它只从本地 JSON 收集 ticker 池扩展（`_arena_extra_tickers`），不消费排名语义，加告警反而噪音。

### 后续跟进

- 主理人需要去 Render 前端访问 Page 3 重跑分类，让 `_record_arena_history` → `push_arena_history_batch` 回填 61 个月历史数据。
- 写后校验：下一步给 `push_arena_history_batch` 也补一个"写完立刻 `fetch_arena_history.clear()` + 重读比对月份数"的 verify 钩子，防止再次静默成功但实际没落库。

---

## 2026-04-17 | 数据一致性治理阶段性沉淀 ⭐

**背景**：2026-04-13 至 2026-04-16 共出现 8 次数据一致性 bug（见本文件 4-15 / 4-16 (b)/(d)/(e)/(f)/(g)/(h) 六条记录）。复盘后发现结构性根因是"真相源分裂 × 静默失败 × 硬编码散落 × 跨页面约定脆弱"的乘法级复杂度，需要系统性治理而非逐条打补丁。

### 本次交付物（一次性立四根柱子）

1. **正本数据流图**：[`../valuation-radar/DATA_FLOW.md`](../valuation-radar/DATA_FLOW.md) — 5 个核心字段（arena_history / conviction_state / screen_results / macro_regime / arena_buffer_n）各一张 mermaid 子图，标注权威源/降级源/TTL + 全局不变量清单 5 条。
2. **正本一致性协议**：[`../valuation-radar/DATA_CONSISTENCY_PROTOCOL.md`](../valuation-radar/DATA_CONSISTENCY_PROTOCOL.md) — 五条硬约束（SSOT / 禁止静默失败 / 破坏性 vs 业务性写入分级 / 跨层契约显式化 / 写后校验），每条配正反例。
3. **后端 `.cursorrules` 新增第 8 条"数据一致性协议"**，前端 `.cursorrules` 顶部加指针指向后端正本，避免双份分裂。
4. **契约审计改造（Page 3 / Page 1）**：
   - 中间层三函数（`_save_history_to_local_json` / `_record_arena_history` / `_save_conviction_state`）全部改为返回 `bool`，失败内置 `st.toast` 红字告警。
   - `_save_conviction_state` 新增 `verify=True` 参数实现写后立即读一次校验（holders 数量比对），作为未来关键路径模板。
   - Page 3 `_sync_arena_to_backend` / 首次 `push_screen_results` 调用点加返回值检查。
   - Page 1 `push_macro_regime` 调用点加返回值检查。
5. **集中 session_state 契约**：新建 [`shared_state.py`](shared_state.py)，`SharedKeys` 常量类覆盖跨页面 8 个 key；Page 4 / Page 5 示范迁移了 `CONFIRMED_BUFFER_N` / `P5_BUFFER_SYNCED` 两处，替代字符串字面量。

### 六条经验教训（写给未来的自己）

1. **单一真相源（SSOT）是生死线**，不是建议。每份数据必须有且仅有一个权威存储。
2. **静默失败比真实失败危险 10 倍**——假成功会在三周后以玄学形式报复，必须让失败响亮。
3. **部署环境保护按操作类型分级**：只阻断破坏性操作（DELETE/DROP/CLEAR_ALL），不得阻断业务写入。4-16(e) 是这条教训的血证。
4. **显式契约 > 隐式约定**：存储上限、schema 字段、共享 key 必须集中定义、后端校验、前端引用；散落多处必埋雷。
5. **写后立即读一次校验**成本极低、收益极高，应该成为关键路径的默认做法。
6. **先画拓扑图再写代码**：当系统超过"3 存储 × 2 环境 × 7 页面"这个量级，没有数据流图就是在盲飞。

### 未决清单（后续单独推进，避免单次 PR 过大）

- Page 3 其它 session_state key（`abcd_classified_assets` / `arena_winners` / `p4_arena_leaders`）迁移到 `SharedKeys`
- Page 0/1/6 的宏观剧本 key 迁移到 `SharedKeys`
- 后端 API schema 增加 `_ARENA_SAVE_N` 上限校验（当前仅前端约定）
- 回填路径（`_backfill_arena_history`）checkpoint 失败累计汇总（当前每次 toast 可能刷屏，虽然实测 60 月 / 6 = 10 次尚可接受）
- 本地 JSON fallback 写入增加 `fallback=true` 元数据标签，权威源恢复后合并而非覆盖

### 影响范围

- 新增：`valuation-radar/DATA_FLOW.md`、`valuation-radar/DATA_CONSISTENCY_PROTOCOL.md`、`valuation-radar-ui/shared_state.py`
- 修改：`valuation-radar/.cursorrules`、`valuation-radar-ui/.cursorrules`、`pages/1_宏观定调.py`、`pages/3_资产细筛.py`、`pages/4_资产调研.py`、`pages/5_个股择时.py`
- 零行为变更：所有改造均为纯增强（加返回值检查、加 toast、加常量引用），不改现有业务逻辑

---

## 2026-04-16 (h)

### 修复 Page 4 守擂缓冲区 Top-N 变更无法传递到 Page 5 A 组图表

**Bug — 调整 Page 4 守擂缓冲区 Top-N 后 Page 5 累计收益率图不更新**
- **根因 1**：Page 5 独立计算 `_p5_min_depth` 时仅检查 A/B/C/D 四个赛道，缺少 Z 类，与 Page 4（含 Z）不一致，可能导致二次钳位将用户设定值覆盖。
- **根因 2**：Page 5 没有提供缓冲区控件，用户必须回 Page 4 点「确认」按钮才能变更，且无法在 Page 5 直观验证生效的实际值。
- **根因 3**：Page 4 的 `_save_buffer_n()` 未调用 `os.makedirs`，如果 `data/` 目录不存在则静默写入失败，跨会话持久化失效。
- **修复**：
  1. Page 5 深度检查补上 Z 类，与 Page 4 保持完全一致。
  2. Page 5 A 组图表区域新增 `st.number_input` 控件（key=`p5_buffer_n_input`），修改后图表立即重算，同时通过 `confirmed_buffer_n` session_state 和 `arena_config.json` 双向同步至 Page 4。
  3. 引入 `_p5_buffer_synced` 哨兵变量，正确区分「Page 4 外部变更」和「Page 5 本地变更」两种同步方向，避免循环覆盖。
  4. Page 4/5 的 `_save_buffer_n` 均加入 `os.makedirs(exist_ok=True)` 保护。
- **影响范围**：`pages/4_资产调研.py`、`pages/5_个股择时.py`。

---

## 2026-04-16 (g)

### 修复 Page 5 A 组信念守擂数据源不同步 + 清缓存按钮形同虚设

**Bug 1 — A 组信念守擂持仓累计收益率图显示错误标的**
- **根因**：Page 5 第 80-87 行直接读本地 `arena_history.json` 文件，而 Page 3 的主存储已迁至后端 API (`universe.db`)，本地 JSON 仅在 API 写入失败时作 fallback 写入。正常运行时本地 JSON 是陈旧的，导致 Page 5 与 Page 3 的「历史月度 Top-2 胜出者」不一致。
- **修复**：改为调用 `fetch_arena_history()`（与 Page 3 的 `_api_fetch_history()` 同源），API 失败时才降级读本地 JSON，并过滤 `_` 前缀旧格式键。

**Bug 2 — 「仅清除当前页缓存」按钮点击无反应**
- **根因**：按钮仅清除 `fetch_core_data` 和 `fetch_vcp_analysis`，遗漏了 A 组图表实际依赖的 `fetch_screen_results` 和 `_fetch_weekly_ohlcv`（价格数据）。加之 `st.success()` 后立即 `st.rerun()` 导致提示消息一闪而过。
- **修复**：补齐四个缓存清除；将 `st.success` 替换为 `st.toast`（跨 rerun 持久化提示）；sidebar 代码块移至 `_fetch_weekly_ohlcv` 定义之后以避免 NameError。

---

## 2026-04-16 (f)

### 修复 Page 6 SyntaxError + Page 5 A 组板块静默消失

**Page 6 问题（SyntaxError — 页面完全无法加载）**：
- `pages/6_仓位配置.py` 第 597 行 f-string 内部含反斜杠转义 `\"#888\"`，Python < 3.12 不支持此语法（PEP 701）。`ast.parse` 阶段即失败，整个页面无法编译。
- `fetch_screen_results` 函数在第 267 行调用但未被 import。

**Page 6 修复**：
- 将 f-string 内的 `\"#888\"` 提取为外部变量 `_fallback_clr`，兼容 Python 3.9+
- 补全 `fetch_screen_results` 到 import 语句

**Page 5 问题（A 组守擂图表板块消失）**：
- A 组整段预计算（~300行：惰性换手、slot 分配、价格拉取、NAV 合成等）全部在 `st.header()` 之前执行，任何未捕获异常都会导致板块静默消失，用户看不到任何报错。
- 数据字段访问使用 `r["ticker"]` 硬取，若回填数据中存在缺失字段则触发 KeyError。

**Page 5 修复**：
- 将 `st.header()` 提前到预计算之前渲染，确保标题始终可见
- 价格拉取段增加外层 try/except，失败时显示错误消息而非静默跳过
- 所有 `r["ticker"]` 改为 `r.get("ticker", "")` 防御式访问

---

## 2026-04-16 (e)

### 修复 Render 环境下 arena 回填/信念写入被 IS_PROD_REMOTE 硬性阻断

**问题**：用户在 Render 上多次执行「回填历史数据」后发现 `arena_history` 仍为旧 Top-3 数据，Top-10 扩容始终未生效。根因：`api_client.py` 中 `IS_PROD_REMOTE` 标志在 Render 环境下为 `True`，`push_arena_history_batch` / `push_conviction_state` / `push_screen_results` / `push_macro_regime` 四个写函数在入口处直接 `return False`，**HTTP 请求根本没有发出**，数据全部丢失。回填函数不检查推送返回值，报告"回填完成"——**假成功**。

**修复**（`api_client.py`）：
- 移除 `push_arena_history_batch`、`push_conviction_state`、`push_screen_results`、`push_macro_regime` 四个函数中的 `IS_PROD_REMOTE` 硬阻断，允许正常业务写入
- 保留 `clear_arena_history_backend`（破坏性 DELETE）的 `IS_PROD_REMOTE` 保护不变
- `_narrative_post` 保持现有软保护（`prod_write_confirmed` 勾选后可写）不变

**修复**（`pages/3_资产细筛.py`）：
- `_save_conviction_state` 移除 `if not IS_PROD_REMOTE` 条件，在所有环境下均正常写入
- Page 3 顶部横幅从"只读模式"改为"生产环境"提示，说明归档/信念写入正常，仅破坏性操作被禁用
- 新增 `_save_history_to_local_json(batch)` 兜底函数：API 推送失败时回退写本地 JSON
- 回填路径三处 push 调用均检查返回值，失败时回退本地 JSON

**影响范围**：`api_client.py`、`pages/3_资产细筛.py`。部署后需重新执行一次「回填历史数据」。

---

## 2026-04-16 (d)

### 修复 A 组回填缺失「带鱼质量」因子

**变动内容**：`_backfill_arena_history` 中 A 组历史评分行缺少 `带鱼质量`（ribbon quality）字段，导致 `compute_scorecard_a` 的 F4（权重 30%）始终为 0，历史最高分上限只有 70 分，冠军排名失真。

**修复**：在 A 组回填分支内，直接用 PIT 价格切片重算 ribbon_score（4 子分量：spread 稳定性 s1、MA20>MA60 连续天数 s2、MA60 斜率一致性 s3、价格贴轨度 s4），公式与 `core_engine.ScorecardA` 完全同源。同时移除了回填中计算但从未被 `compute_scorecard_a` 使用的 `年化波动率` 字段（死代码）。

**影响范围**：`pages/3_资产细筛.py`。需要重新执行一次「回填历史数据」操作，以覆盖之前写入的错误 A 组档案。

---

## 2026-04-16 (c)

### 大盘趋势状态机叠加四大剧本背景色带

**变动内容**：在"大盘趋势状态机"图表（`_render_mtm_tab`）中叠加四大剧本历史裁决的背景色带，实现宏观基本面维度与技术形态维度正交双维同框展示。

**实现方式**：
- 在 `_MTM_INDEX_YLABEL` 定义后，提前从 `_regime_api["horsemen_daily_verdict"]` 计算 `_horsemen_daily_mtm`（日度剧本序列）和 `_REGIME_BG_C_MTM`（背景色字典），确保在函数调用时已在闭包作用域内。
- 在 `_render_mtm_tab` 函数内，将 `_horsemen_daily_mtm` reindex 到当前 ticker 的 `_df` 时间轴并 `ffill()`，遍历生成 `_bg_shapes` 列表（每段剧本一个 `type="rect"` shape）。
- 将 `shapes=_bg_shapes` 注入 `_fig.update_layout`，并加判空保护（`_horsemen_daily_mtm` 为空时跳过，K线不受影响）。
- 图表标题更新为"技术形态 × 剧本背景双维叠加"，并在白盒区增加"图层说明"卡片，解释两套颜色系统的含义及不一致时的信号价值。

**影响范围**：仅 `pages/1_宏观定调.py`，SPY 和 QQQ 两个 Tab 均受益，无 API 变更。

---

## 2026-04-16 (b)

### Arena 历史存储扩容 Top-3 → Top-10 & 连续在榜月数 bug 修复

**问题**：Page 4「守擂缓冲区 Top-N」滑块从 3 改为 5 时，「历史月度 Top-2 胜出者」表格完全不变。排查发现 `arena_history` 每赛道每月**只存储了 3 条记录**，`[:5]` 和 `[:3]` 切到的数据完全相同，导致缓冲区参数无效。

**Page 3 改动**（`pages/3_资产细筛.py`）：
- 新增常量 `_ARENA_SAVE_N = 10` 与辅助函数 `_expand_arena_records()`，将信念引擎选出的 Top-3 用 scorecard 补齐至 10 条
- 7 个 `_record_arena_history()` 调用点全部改为传入扩展后的列表（A/B 组信念选出 + scorecard 补齐；C/D/Z 组直接 `head(10)`）
- 回填路径同步修改，C/D/Z 用 `head(_ARENA_SAVE_N)`，A/B 用 `_expand_arena_records`

**Page 4 改动**（`pages/4_资产调研.py`）：
- `_compute_streaks_p4(cls)` 新增 `top_n` 参数，原硬编码 `[:3]` 改为 `[:top_n]`
- `_all_streaks` 计算从定义时（slider 之前）移至 `_buffer_n` 确定之后，传入 `_buffer_n`
- 连续在榜月数（X月）现在随缓冲区大小联动

**后端无改动**：`universe_manager.py` / `api_server.py` 的读写管道透传 JSON，不截断记录数。`core_engine.py` 的 `[:3]` 是投资组合构建逻辑，语义正确保持不变。

**生效前提**：需在 Page 3 重新执行「回填历史数据」，使 61 个月的存量数据从 3 条扩充至 10 条。

---

## 2026-04-16

### A 组权重与换仓门槛可调化

**背景**：守擂缓冲区阈值（Top-3）和 A 组合成 NAV 权重（50/50 等权）均为硬编码，无法在 UI 中探索参数敏感性。

**Page 4 改动**（`pages/4_资产调研.py`）：
- `_holdings_map` 和 `_slot_assignments` 计算前读取 `st.session_state.get("arena_buffer_n", 3)` 为 `_buffer_n`
- 将所有 `_recs[:3]` / `_entry.get(_cls, [])[:3]` 改为 `_recs[:_buffer_n]`
- 在白盒标题下方新增 `st.slider("守擂缓冲区 Top-N", 2, 6, key="arena_buffer_n")`，以及信息 caption
- 白盒标题、规则说明卡片中的 "Top-3" 全部改为 `f"Top-{_buffer_n}"` 动态显示

**Page 5 改动**（`pages/5_个股择时.py`）：
- `_tm_hold` 计算前读取 `st.session_state.get("arena_buffer_n", 3)`，所有 `_recs[:3]` 改为 `_recs[:_buffer_n]`
- 新增 `_compute_streaks_p5(cls, top_n)` 函数：计算每月每标的在 Top-N 内的连续在榜月数
- 新增 `_compute_slot_weights(slot_assignments, streaks, months)` 函数：按 streak 为 Slot 0/1 分配权重（30%-70% 区间限制）
- NAV 合成支持两种模式：等权 50/50 / 信念倾斜（按月映射 streak 权重，向量化实现）
- A 组图表标题下方新增合成权重 radio 控件 + 缓冲区信息 caption
- KPI 行新增"换仓次数"指标；信念倾斜模式下显示历史月均权重分布
- Tabs 新增"合成收益率"第三 Tab（含 SPY benchmark 对比线）

**数据流**：Page 4 slider → `session_state["arena_buffer_n"]` → Page 5 惰性换手重算；Page 5 radio → `session_state["a_weight_mode"]` → NAV 合成分支。

---

## 2026-04-15

### 后端 macro_engine 加进程内缓存（修复 yfinance 429 超时）

**背景**：`POST /api/v1/macro/compute` 每次调用都从零重新下载 18个ETF×12年价格 + 7条FRED序列，叠加 Render 免费套餐 yfinance 429限流（20s等待重试×多批次），导致 Page 1 经常触发 300s 超时、回退本地计算，且 Page 6 因此读不到最新剧本。

**修改**：在 `valuation-radar/macro_engine.py` 对三个重下载函数加进程内 dict 缓存（TTL=4小时）：
- `fetch_regime_price_data()` → `_price_regime_cache`
- `get_clock_fred_data()` → `_fred_clock_cache`
- `compute_radar_metrics()` → `_radar_price_cache`

**效果**：Render 实例冷启动后第一次调用正常走网络，后续4小时内任何页面访问直接命中缓存，彻底消除 yfinance 429 叠加超时问题。

---

### Session State 后沉 Step 4 & Step 5 正式完成（yfinance 后端化）

**背景**：Step 4 / Step 5 的妥协记录遗留两个问题：
1. `POST /api/v1/screen/run-classification` 端点仍要求前端传 price_df（1-3MB 序列化）；
2. `POST /api/v1/macro/compute` 端点仍要求前端传 price_records；Page 1 / Page 0 仍在 Streamlit 进程内调 yfinance。

**本次变更**：

#### 后端（valuation-radar）

- **`macro_engine.py`**：新增 `REGIME_TICKERS`（17 个四大剧本计算所需 ETF）+ `fetch_regime_price_data(years=12)` 函数（后端直拉 yfinance）；`compute_macro_regime()` 返回值追加 `_horsemen_monthly_table`（月度裁决表 records，供 Page 1 渲染图表）和 `_horsemen_daily_verdict`（日度裁决 dict，供比值图染色）。
- **`api_server.py - /macro/compute`**：`price_records` 为空时调 `fetch_regime_price_data()` 自拉数据；从返回包中 pop 两个图表字段（不写 DB）并在 HTTP 响应中单独返回；FRED 自拉逻辑不变。
- **`api_server.py - /screen/run-classification`**：`price_records` 为空时根据 `screen_tickers + z_seed_tickers + SPY` 自拉 yfinance 3 年数据，完成后端独立分类；向后兼容旧路径（传 price_records 仍可用）。

#### 前端（valuation-radar-ui）

- **`api_client.py`**：新增 `compute_macro_regime_api(z_window=750)`（POST `/macro/compute`，空 body，TTL=4h）；`run_classification_api` 签名改为 `price_df=None`（末尾可选参数），默认走后端自拉路径，向后兼容。
- **`pages/1_宏观定调.py`**：新增 `compute_macro_regime_api` 调用（在 FRED 拉取后）；移除本地 `_build_horsemen_history()` 函数定义，改从 API 响应重建 `df_hist_horsemen` 和 `_horsemen_daily`；session_state 写入改为直接从 API `data` 字段取值；`push_macro_regime` 降级为仅在 API 不可用时的 fallback 路径。本地 yfinance 下载保留（`df` 仍用于宏观时钟等图表渲染）。
- **`pages/3_资产细筛.py`**：实时分类入口（原 line 2643）改为调 `run_classification_api(screen_tickers, ...)`，不再传 price_df；失败时回退本地 `classify_all_at_date`。历史回填（`_backfill_arena_history`）保留本地计算（需逐月截面，无法简单 API 化）。
- **`pages/0_宏观雷达.py`**：完全重写，移除所有本地 yfinance / ASSET_GROUPS / `calculate_metrics()` / 本地 `generate_deep_insight()`，改为单一 `fetch_macro_radar()` API 调用；保留 HTML 样式的 insight 渲染函数（使用后端返回的 plain-text 拼装）。

**影响范围**：`macro_engine.py`、`api_server.py`、`api_client.py`、`pages/0_宏观雷达.py`、`pages/1_宏观定调.py`、`pages/3_资产细筛.py`。需重启后端才能激活新端点逻辑。

---

### Arena 历史档案迁移至后端 + 回填 Warm-up 修复

**背景**：历史月度 Top 3 档案此前存于前端本地 `data/arena_history.json`，信念状态存于后端 `universe.db`。两个存储源各自读写导致「打架」：实时渲染覆盖写 DB 信念状态后，与本地 JSON 不同步，多次回填后信念值退化为仅 1 个月的积累（等于 `score × 0.22`）。

**本次变更**：

1. **`universe_manager.py`**：新增 `arena_history` 表（主键 `month_key + cls`），及 `get_arena_history` / `upsert_arena_batch` / `clear_arena_history` 三个函数。
2. **`api_server.py`**：新增三个端点 `GET/POST batch/DELETE /api/v1/arena/history`，与 `conviction_state` 位于同一 DB 文件，完全同步。
3. **`api_client.py`**：新增 `fetch_arena_history` / `push_arena_history_batch` / `clear_arena_history_backend`。
4. **`pages/3_资产细筛.py`**：
   - `_load_arena_history`：主走后端 API，本地 JSON 仅作离线降级备用。
   - `_record_arena_history`：新增 `_batch_buf` 参数，回填期间只写内存，每 6 个正式月或末尾统一批推。
   - `_save_conviction_state` / `_load_conviction_state`：移除本地 JSON 双写，信念状态只存 DB。
   - 清除按钮：改为调用 `_api_clear_history()` 清空后端表，同时删本地 JSON 备份。
5. **回填 Warm-up**：`_backfill_arena_history` 新增 `warmup_months=12` 参数。回填时实际处理 `months_back + 12` 个月，前 12 个月只积累信念状态不写档案，使信念值在记录起点前达到稳态（~90% 稳态需 ≈ 11 个月，`holder_decay=0.80`）。
6. **数据迁移**：已将原 `arena_history.json` 的 61 个月数据（243 行）一次性导入 `universe.db`。

**影响范围**：`pages/3_资产细筛.py`、`api_client.py`、`universe_manager.py`、`api_server.py`。需重启后端才能激活新端点。

---

## 2026-04-14

### 新增「A 组信念守擂持仓 K 线图」Section（5_个股择时.py）

**背景**：Page 5 原有"资产细筛盈利统计"仅以表格呈现各段盈亏，缺乏直观的持仓时序可视化。本次在该 Section 上方新增完整的 K 线图与绩效统计模块。

**变动内容**：
- **`_name_map` 提前构建**：从原来位于 Section 0 内部（L479）提前到 `_tm_hold` 构建完成后，供 K 线图和盈利统计共用。
- **A 组 slot-stable 列分配 `_a_slot_assignments`**：遍历 `_tm_months`，对 A 组历史持仓按"优先保留上期位置"策略稳定分配左（slot 0）/ 右（slot 1）列。
- **持仓段序列 `_seg_left` / `_seg_right`**：识别每列的连续持仓段（同一 ticker 连续月份合并为一段），结构为 `[(ticker, start_month, end_month), ...]`。
- **K 线图 `_build_kline_fig()`**：每段一个 `go.Candlestick` trace，使用 8 色预设色板轮换，左右列各一图放在 `st.columns(2)` 中。
- **绩效统计 `_calc_slot_stats()`**：拼接各段净值曲线，计算总收益和最大回撤。
- **合成 A 级整体（半仓等权）**：左右列各 50% 权重对齐日期轴后合成净值，计算整体总收益与最大回撤。
- **UI 布局**：新 Section 标题 + 6 个 `st.metric`（总收益 / 最大回撤 各 3 列）+ 双列 K 线图。

**影响范围**：仅 `pages/5_个股择时.py`，新增约 160 行，无 API 接口变更。

### 删除「演示模式 Mock 数据」死代码（3_资产细筛.py）

**背景**：侧边栏的"竞技场控制台"下有一个"演示模式（使用 Mock 数据）"开关，默认关闭，用于早期开发时在后端不可用时跑通 UI 流程。系统已稳定上线，该开关常年关闭，是典型死代码。

**删除内容**：
- `_MOCK_ASSETS` 硬编码假数据字典（约 35 行）
- 侧边栏 `demo_mode` 开关及说明提示
- 数据来源决策处的 `if demo_mode:` 分支
- Mock 模式预计算竞技场冠军的 `if demo_mode:` 大段代码（约 45 行）
- 所有提示文案中"或开启演示模式"字样统一改为"或清除缓存后重试"

**影响**：页面始终走真实数据路径，无功能损失。

---

### Session State 后沉五步迁移（Steps 1-5）

**背景**：前端跨页面通过 `session_state` 传递宏观剧本、ABCD 分类、竞选结果等业务数据，导致页面访问顺序依赖（Page 1 → Page 3 → Page 4/5/6）、刷新数据忽闪等问题。本次采用 **write-through cache** 模式，将上述数据逐步沉入后端 `universe.db`，消灭顺序依赖。

#### Step 1：宏观 Regime 沉入后端
- **后端** `universe_manager.py`：新增 `macro_regime_cache` 表 + `save_macro_regime()` / `get_macro_regime()` 函数
- **后端** `api_server.py`：新增 `POST /api/v1/macro/regime`、`GET /api/v1/macro/current-regime` 端点
- **前端** `api_client.py`：新增 `push_macro_regime()`（TTL 写后清缓存）、`fetch_current_regime()`（TTL=300s）
- **Page 1**：`session_state` 写入后追加 `push_macro_regime()` write-through 调用
- **Page 3/6**：regime 读取改为优先调 `fetch_current_regime()` API，回退 session_state 过渡兼容

#### Step 2：narrative_heat_ranking 消灭跨页依赖
- **Page 3**：删除 `session_state.get("narrative_heat_ranking")` 优先路径，始终调 `fetch_l2_l3_detail(days=7)` API
- **Page 2**：删除 `session_state["narrative_heat_ranking"] = ...` 写入

#### Step 3：ABCD 分类 + Arena 竞选结果沉入后端
- **后端** `universe_manager.py`：新增 `screen_results` 表 + `save_screen_results()` / `get_screen_results()` 函数
- **后端** `api_server.py`：新增 `POST/GET /api/v1/screen/results` 端点
- **Page 3**：`abcd_classified_assets` 写入后 push；arena_winners/p4_arena_leaders 各写入点后追加 `_sync_arena_to_backend()` 同步
- **Page 4**：`abcd_classified_assets` 改为优先从 `fetch_screen_results()` 读取
- **Page 5**：`p4_arena_leaders` 改为优先从 `fetch_screen_results()` 读取
- **Page 6**：`arena_winners` 改为优先从 `fetch_screen_results()` 读取

#### Step 4：screener_engine / conviction_engine 物理迁入后端
- **后端**：`screener_engine.py` + `conviction_engine.py` 复制到 `valuation-radar/`（以前端版本为准，功能更完整）
- **后端** `api_server.py`：新增 `POST /api/v1/screen/run-classification` 端点（接收 price_records，返回完整分类 + 竞选结果）
- **前端** `api_client.py`：新增 `run_classification_api()` 包装函数
- ⚠️ **妥协记录**：Page 3 实际调用迁移（本地 `classify_all_at_date` → API）**暂缓**。原因：price_df 序列化为 JSON 约 1-3MB/请求，在本地开发环境虽可接受，但引入网络往返耗时会明显拖慢用户体感；且 Page 3 的分类 → 评分 → 竞选链路紧耦合、重构范围大。当前 write-through（Step 3）已能确保跨页面数据一致性，完整迁移留待 Step 5 后端定时触发机制建立后统一处理。

#### Step 5：宏观引擎 + 雷达迁入后端
- **后端** `macro_engine.py`（新建）：
  - FRED 拉取函数 `_fetch_fred_series/batch`、`get_clock_fred_data()`（API Key 从环境变量读取，不再暴露给前端）
  - 四大剧本历史裁决引擎 `_build_horsemen_history()`
  - SPY 5阶趋势状态机 `compute_spy_trend_state()`
  - 完整 regime 计算 `compute_macro_regime()`
  - Page 0 雷达资产池 `ASSET_GROUPS` + `compute_radar_metrics()` + `generate_deep_insight()`
- **后端** `api_server.py`：新增 `POST /api/v1/macro/compute`（接收 price_df，内部拉 FRED，返回+持久化 regime）、`GET /api/v1/macro/radar`（雷达指标）
- **前端** `api_client.py`：新增 `fetch_macro_radar()`（TTL=4h）
- ⚠️ **妥协记录**：Page 1 本地计算仍保留（write-through 已解决 Page 3/6 依赖），完整迁移（Page 1 改调 `/api/v1/macro/compute`、Page 0 改调 `/api/v1/macro/radar`）留待定时触发 + yfinance 后端化后的 Phase 2 执行。

#### 清理
- 删除 Page 3 孤儿 key 读取：`page1_macro_recommended`（该 key 从未有写入方，始终返回空列表 `[]`，删除无副作用）
- `p4_champion_ticker` 保留（这是 Page 3→5 用户点击路由的合法 widget key，非孤儿）

---

## 2026-04-13

### 历史月度 Top 3 宏观剧本白盒化

**背景**：历史月度 Top 3 表格的「四剧本裁决」列之前只显示静态剧本名称，用户无法直观看到剧本切换对 B/C 组评分规则的实际影响。

**改动内容（`pages/3_资产细筛.py`）**：
1. **新增辅助常量**：`_REGIME_CN_TO_CODE`（中→英代码映射）、`_REGIME_EMOJI`（剧本图标字典）、`_B_FACTOR_LABELS`（B 组 7 因子名称元组）。
2. **新增 `_regime_shift_annotation(prev_cn, curr_cn, cls)`**：
   - B 组：从 `B_REGIME_WEIGHTS` 提取前后权重 diff，高亮发生变化的因子及权重升降箭头。
   - C 组：从 `_MACRO_TAGS_MAP` 提取前后宏观顺风标的集合 diff，分别展示新增（绿色）/移出（红色删除线）标的。
   - A/D/Z 组：直接返回空字符串，不插入注释行。
3. **修改主渲染循环**：预计算所有月份裁决列表，利用 look-ahead（`_cls_months[i+1]`）检测月间剧本切换；切换月份在「四剧本裁决」列显示 `前月emoji→当月badge` 箭头提示，且在该月数据行下方插入橙色左边框「🔀 剧本切换影响」注释行。
4. **Caption 动态标注**：A/D/Z 赛道追加提示"本赛道评分不受宏观剧本变化影响"；B/C 赛道提示切换月份会自动插入白盒注释行。

**影响范围**：仅 `pages/3_资产细筛.py` 历史榜单渲染区，不涉及评分逻辑和数据流。

---

### 生产环境写操作防护（RADAR_API_URL 直连场景）

**背景**：同事通过 `RADAR_API_URL` 直连 Render 生产后端进行支链开发时，所有写接口均无保护，存在污染 `narrative.db`（词典/orphan）和 `universe.db`（信念状态/迟滞状态）的风险。

**变动**：
- `api_client.py`：新增 `IS_PROD_REMOTE` 布尔常量（`_env_url` 已设且不含 `localhost`），供各页面读取；`push_conviction_state` 在 `IS_PROD_REMOTE` 时直接 `return False`（Page 3 写操作硬封死）；`_narrative_post` 在 `IS_PROD_REMOTE` 且 `session_state["prod_write_confirmed"]` 未置位时返回 `{"success": False, "blocked": True}`（Page 2 写操作软封锁）。
- `pages/3_资产细筛.py`：导入 `IS_PROD_REMOTE`；`st.set_page_config` 后立即渲染红色 error 横幅；`_save_conviction_state` 函数内及"删除历史"的两处 `_api_push_conv` 调用点均加 `if not IS_PROD_REMOTE:` 双重保护。
- `pages/2_舆情监控.py`：导入 `IS_PROD_REMOTE`；`st.set_page_config` 后渲染 warning 横幅 + 单一确认 checkbox（`key="prod_write_confirmed"`），未勾选时 `_narrative_post` 层自动拦截所有写请求，无需逐一修改 25+ 个写操作调用点。

**影响范围**：仅在 `RADAR_API_URL` 指向非 localhost 时生效；正常本地开发和生产部署行为不受任何影响。

### P0: 择时工具解耦 — 可插拔多策略对比平台

**改动文件：`valuation-radar-ui/pages/5_个股择时.py`**

将原来硬编码的单一 `_compute_timing()` 函数重构为**策略注册表 + 标准接口**架构：

- 新增 `TimingResult(NamedTuple)`：统一所有择时工具的返回结构（signals / benched_zones / timed_rets / raw_rets / overlays），`overlays` 字段取代原先硬编码的 `fast_ma / slow_ma` 返回，每个工具自行声明需要绘制哪些辅助线。
- 新增 4 个独立择时工具函数：
  - `_timing_ma_cross()`：重构自原 `_compute_timing`，支持 MA 金叉/死叉（A/B 组）和价格 vs 生命线（C/D 组），行为与原版完全兼容
  - `_timing_break_ma()`：通用价格 vs 任意 MA 生命线实现（被 break_ma60/break_ma20 复用）
  - `_timing_break_ma60()`：价格跌破 MA60w 生命线策略，蓝色系
  - `_timing_break_ma20()`：价格跌破 MA20w 策略，紫色系
  - `_timing_rapid_drop()`：急跌速断器，默认持仓，单周跌幅 >8% 紧急清仓，价格回升至 MA12w 上方后重新入场，橙色系
- 新增 `_TIMING_TOOLS` 注册表、`_TOOL_COLORS` 颜色表、`_TOOL_SYMBOLS` 形状表（各工具分配独立买卖符号：▲三角/◆菱形/●圆圈/★星形）
- **UI 升级**：Section 1 控件区新增第三列「择时工具多选」（multiselect），默认选中 `ma_cross`，与原有行为完全一致（零打扰升级），可多选进行并排对比
- **渲染引擎升级**：多工具并行运行，overlay 辅助线叠加绘制，信号按工具分色/分形，收益标注改为 `名单 X% | MA金叉 Y% | 速断器 Z%` 多列格式，明细表增加每工具一列择时收益
- **白盒 expander 动态化**：根据选中的工具动态生成策略说明文字，不再是静态硬编码

### P1: Downside Capture Ratio 替换 F3

**改动文件：`valuation-radar/core_engine.py`**（ScorecardA.score() 方法）

将 F3 因子从 `SPY Correlation Inverse (20%)` 替换为 `Downside Capture Ratio (20%)`：

- **原 F3 问题**：Pearson 相关系数不区分涨跌环境，与 SPY 无关的高波动垃圾股（corr ≈ 0）可得中等分，无法区分"真对冲"和"伪不相关"
- **新 DCR 公式**：`DCR = mean(asset_ret[spy_down_days]) / mean(spy_ret[spy_down_days])`，仅在 SPY 下跌日计算标的的平均超额表现
- **打分映射**：`score_dcr = max(0, (1.2 - dcr) / 1.2) * 20`，DCR ≤ 0 满分（SPY 跌时资产反涨），DCR ≥ 1.2 零分（跌得比 SPY 更惨）
- `score_corr` 变量名同步重命名为 `score_dcr`，总分公式对应更新
- 权重保持 20% 不变

### A 赛道深度复盘 — 策略分析经验总结

对 A 赛道（避风港）历史持仓进行全面复盘，从截图实际数据中提取 18 段交易记录，其中 6 段标红（绝对亏损或跑输 SPY），以下为核心发现与未来优化方向。

#### 红色交易归因分析

| 标的 | 持仓区间 | 绝对收益 | 同期 SPY | 失败主因 |
|------|---------|---------|---------|---------|
| KO | 2024-09→2025-04 | -0.8% | +6.5% | 消费股防御神话破灭——GLP-1 减肥药叙事冲击食品饮料板块，叠加估值偏高回调 |
| LMT | 2024-11→2025-04 | +1.4% | -1.5% | 绝对收益正但微薄；国防股受地缘博弈预期波动大，F3 相关性因子未能识别其"伪不相关"特征 |
| NOC | 2025-01→2025-04 | -4.4% | -5.0% | 国防板块集体承压（预算争议+合同延迟），虽略好于 SPY 但绝对亏损 |
| MO | 2024-04→2024-09 | +0.2% | +8.3% | 跑输 SPY 超 8 个百分点；烟草股在牛市中严重滞涨，高 FCF 高股息的价值陷阱特征明显 |
| GLD | 2022-05（仅 1 月）| 微亏 | — | 冷启动问题：信念引擎尚未充分积累信念值即被换出，持仓时间过短 |
| GLD | 2024-01→2024-05 | +13.5% | +11.0% | 实际跑赢 SPY，但页面因阈值设定标红；非真正失败 |

#### 关键洞察

**1. F3 因子（SPY Correlation Inverse）的结构性缺陷**
- Pearson 相关系数不区分"涨时同涨"和"跌时同跌"——一个与 SPY 整体低相关但在崩盘时照样暴跌的标的（如 LMT）会拿到不错的 F3 分数，但完全无法提供下行保护
- **已修复**：替换为 Downside Capture Ratio，仅在 SPY 下跌日计算标的表现，GLD 这类真对冲资产满分，LMT 这类伪不相关资产低分

**2. "低波动率"过滤器的 GLD 误杀教训**
- 曾经尝试在 A 赛道加入低波动率过滤，结果把 GLD 踢出——黄金虽然是最优对冲资产，但其日内/周度波动率并不低
- **结论**：A 赛道不应追求"低波动"，应追求"下行保护"，这两个概念有本质区别。DCR 比波动率更精准地刻画了这一需求

**3. Conviction Engine vs Lazy Turnover 的认知校准**
- 页面 5 的 `_tm_hold` 使用"惰性换手"逻辑重建持仓历史，产出 41 段碎片化交易；但用户实际看到的 18 段长周期持仓来自 Conviction Engine
- **教训**：复盘分析必须基于实际运行路径的数据，不能用简化模型替代。后续如果要做精确回测，应将 conviction engine 的历史状态持久化并直接读取

**4. 黑天鹅防护 = 择时层的责略，非择股层**
- A 赛道的择股层（ScorecardA）负责"选谁有资格上场"，无法预判突发事件
- 黑天鹅防护应在择时层实现：急跌速断器（单周暴跌 >8% 立即清仓）是最务实的 P0 方案
- VIX Panic Gate 可作为 v2 增强；新闻情绪监控成本高、信号噪，暂不推荐

**5. 短持仓期（1-2 月）是换挡代价，无需过度优化**
- GLD 2022-05 仅持仓 1 个月即被换出，属于 conviction engine 冷启动阶段的正常换挡
- 此类短持仓在全部 18 段中占比极低，对组合整体收益影响有限（< 0.5%）
- 如需微调，可考虑"冷启动保护期"（新入选标的前 2 个月不参与挑战替换），但优先级很低

**6. 择时工具解耦是正确方向**
- 当前 MA12w/MA60w 金叉死叉是唯一择时策略，无法判断是否存在更优方案
- 解耦后可平行对比：MA 死叉 vs 跌破 MA60 生命线 vs 跌破 MA20 vs 急跌速断，用历史数据回答"哪种择时更有效"
- 每种工具适合不同市场环境：趋势市适合 MA 死叉，震荡市适合 MA20 快速反应，黑天鹅适合急跌速断

#### 未来优化方向（按优先级）

1. **急跌速断器已实现** → 积累数据观察是否降低了最大单笔亏损
2. **DCR 因子已上线** → 下一轮月度打分时观察 GLD/KO/LMT 排名变化是否符合预期
3. **择时工具对比平台已实现** → 积累 3-6 个月数据后做各工具的 Sharpe/最大回撤/胜率横评
4. **Conviction Engine 历史状态持久化** → 将每月信念值快照写入 DB，支持精确回测而非依赖 lazy turnover 近似


---

## 2026-04-13 | 修复 A 赛道持仓碎片化（惰性换手连坐 + FCF 天花板惩罚）

### 背景 & 问题

**Bug 1：惰性换手"连坐"（Page 4 & 5）**
原持仓守擂逻辑使用 `_prev_h.issubset(_t3)`——全集合判断，只要有任意一个持仓标的跌出 Top-3，整批持仓全部换掉。导致 GLD 等仍在 Top-3 的标的因"伙伴出局"而被无辜踢走，持仓碎片化、闪现率虚高。

**Bug 2：ScorecardA FCF 对商品 ETF 天花板惩罚（core_engine.py）**
GLD 等商品 ETF 既无 `freeCashflow` 也无 `dividendYield`，F2 维度（FCF Yield，权重 20%）直接判 0/20，导致 GLD 得分偏低（63 分 vs 旧版 86 分），影响 A 赛道公平竞争。

### 变动内容

- **pages/5_个股择时.py**（第 152 行）：`issubset` 改为单标的独立守擂——逐个检查前持仓是否仍在 Top-3；保留数 ≥ 2 原样留任，= 1 从 Top-3 顺序补位，= 0 取 Top-2 重置。
- **pages/4_资产调研.py**（第 436-440 行）：同步改为相同的单标的独立守擂逻辑，`traded` 标志改为 `_hold != _prev_hold`（任意持仓变化均触发）。
- **core_engine.py `get_stock_metadata`**（第 43-55 行）：新增 `fcf_source` 字段——若 `freeCashflow` 和 `dividendYield` 均缺失则标记 `"missing"`，否则 `"data"`。
- **core_engine.py `ScorecardA.score`**（第 924-930 行）：F2 判分时检查 `fcf_source`，`"missing"` → 给中性分 10.0/20，不奖不罚；有数据则保持原线性映射。

### 影响范围

- A 赛道 GLD 持仓稳定性提升（模拟：2025-02~2025-11 连续持有，闪现率 59%→51%）。
- ScorecardA GLD 分数从 ~51-63 分回归至更公平的 ~65-75 分区间。
- B/C/D 赛道逻辑不变，不受影响。

## 2026-04-13 | 信念状态迁移至后端持久化 + 回填 Checkpoint 防中断丢失

### 背景 & 问题
信念状态（conviction_state）此前仅存储于前端 `data/arena_history.json`。一旦该文件被意外清空，或历史回填中途被 Streamlit 中断（`_save_conviction_state` 只在循环结束后调用一次），积累的多月信念值全部归零，导致显示"冷启动"而非应有的"卫冕留任"。

### 变动内容

#### 后端（`valuation-radar`）
- **`universe_manager.py`**：新增 `conviction_state` 表（SQLite, `universe.db`），字段 `cls / state_json / holders_json / updated_at`；新增 `get_conviction_state(cls)` 和 `save_conviction_state(cls, state, holders)` 两个 CRUD 函数；`init_db()` 同步建表（幂等）。
- **`api_server.py`**：新增两个端点：
  - `GET  /api/v1/conviction_state/{cls}` — 从 universe.db 读取指定组别（A/B）信念状态
  - `POST /api/v1/conviction_state/{cls}` — 写入/更新信念状态

#### 前端（`valuation-radar-ui`）
- **`api_client.py`**：新增 `fetch_conviction_state(cls)` 和 `push_conviction_state(cls, state, holders)` 两个封装函数，调用上述后端端点，网络失败时安全返回空值。
- **`pages/3_资产细筛.py`**：
  - `_load_conviction_state`：优先从后端 API 读取，失败时降级到本地 JSON（离线兜底）。
  - `_save_conviction_state`：同时写入后端 API（主存储）和本地 JSON（缓存副本）。
  - **回填循环**：每处理 6 个月执行一次 checkpoint `_save_conviction_state`，防止长回填任务中断后丢失所有进度。

### 影响范围
- 信念状态现在有双重保障：后端 SQLite 为主，前端 JSON 为缓存。
- 即使前端文件全部删除，下次重启后加载信念状态仍走后端 API 恢复。
- 即使回填任务在第 N 个月被中断，至多损失最后不超过 6 个月的积累进度。

---

## 2026-04-13 | 排行榜布局优化：信念值列前移，移除冗余得分栏

### 变动内容
- **A/B 组完整排行榜** 新增 `conviction_map` 参数，不再将因子得分单独占用右侧一列（"避风港防御指数"/"核心底仓质量指数"栏移除）。
- **因子分内嵌**：堆叠条形图右侧直接以灰色小字显示原始因子分（`竞技得分`），不再占用专栏空间。
- **信念值列前移**：在最大回撤左边新增"信念值"列（90px），展示 conviction engine 计算的动态信念值 + 守擂状态图标（🛡️ 卫冕 / ⚔️ 挑战 / 🆕 新晋 / 🔰 冷启动），非在位者只显示数字，信念为 0 的标的显示 `—`。
- 调用处同步构建 `_full_conv_map_a` / `_full_conv_map_b`（全量 `conviction_state` + 选拔结果 status），传入渲染函数。
- **澄清概念**：避风港防御指数 = 当期因子快照分；信念值 = 多期积累的动态分，三层机制（信念积累、在位者惯性、冠军守擂）均作用于此值，两者不同。

---

## 2026-04-13 | 白盒加工台：A/B 组分类迟滞 + 信念守擂全量推演（含可调参数）

### 变动内容
在"完整排行榜"与"历史月度 Top 3"之间插入了两层可交互白盒加工台，A、B 两组均适用。

**① screener_engine.py — 迟滞阈值参数化**
- `classify_asset_parallel()` 新增 `thresholds: dict = None` 参数，A 组的 6 个硬编码迟滞阈值（股息进入/退出、回撤进入/退出、相关性进入/退出）改为从 dict 读取，None 时用原默认值（完全向后兼容）。
- `all_details["A"]` 新增 `_was_a`、`_enter_checks`、`_exit_checks`、`_div_yield`、`_max_dd`、`_spy_corr` 等白盒辅助字段，供前端审计表读取。
- `classify_all_at_date()` 新增 `thresholds` 参数并透传给 `classify_asset_parallel()`。

**② 3_资产细筛.py — 两个新白盒渲染函数**
- `_render_hysteresis_whitebox(all_assets_dict)` — 第一层：展示所有候选标的的 A 组审计表（Ticker/名称/上期A/三项指标实际值/通过情况/迟滞效果），内置 6 个阈值 sliders，修改后即时生效（通过 session_state → classify_all_at_date rerun 链路）。
- `_render_conviction_whitebox(...)` — 第二层：Panel A（信念积累明细+可视化信念条）、Panel B（守擂选拔逐步推演）、Panel C（因子排名 vs 信念排名对比+分歧高亮），内置 7 个信念参数 sliders，修改后即时重算并更新 Top N。

**③ A 组改动**
- 读取 session_state 中的信念参数 sliders，构建 `_rt_conv_cfg_a`，所有 `_conv_update` / `_conv_select` 调用改用此 config。
- 在 `_conv_update` 前快照旧信念状态 `_rt_old_conv_a`，供白盒 Panel A 展示"旧→新"变化量。
- `_render_leaderboard(df_scored_a, "A")` 之后追加白盒加工台（分类迟滞 + 信念守擂）。

**④ B 组改动**（与 A 组平行）
- 同样构建 `_rt_conv_cfg_b`（含 7 个 session_state slider keys）、快照 `_rt_old_conv_b`。
- 移除旧的"全候选池信念值一览"展开区，替换为统一的 `_render_conviction_whitebox` 调用。
- `_render_leaderboard_b(df_scored_b)` 之后追加白盒加工台。

### 影响范围
- `screener_engine.py`：2 个函数签名变更（向后兼容），`all_details["A"]` 字段新增
- `pages/3_资产细筛.py`：新增约 280 行白盒函数，A/B 组各约 20 行改动，移除旧的 B 组信念一览展开区

---

## 2026-04-12 | A 级评分卡重构：F2 现金奶牛改为 FCF 收益率，删除 F4 绝对低波，带鱼质量升权至 30%

### 重构动机
两处因子设计缺陷被识别并修复：

**① F2「现金奶牛」概念与实现不符**  
原来用 `div_yield`（股息率）代理「现金奶牛」，有三个硬伤：（1）不派息的优质现金牛（BRK.B、GOOG 等）直接被判零分；（2）股价腰斩后股息率被动翻倍，反而得高分（股息陷阱）；（3）A 组标的（GLD、TLT、BIL）天然无股息，20% 权重白送。  
更严重的是：`get_stock_metadata` 从未向 `meta` 写入 `div_yield` 字段，导致 ScorecardA.score() 里的 F2 **一直静默吃零分**。

**② F4「绝对低波」与 F1「极限抗跌」高度冗余**  
低波动率和低最大回撤高度共线，F4 实质上是 F1（30%）的影子，叠加在一起等于变相给「防守」分配了 45% 权重，挤压了有区分度的带鱼质量因子的空间。

### 改动内容
| 因子 | 旧权重 | 新权重 | 变化 |
|---|---|---|---|
| F1 极限抗跌 (最大回撤倒数) | 30% | 30% | 不变 |
| F2 现金奶牛 → FCF收益率 (FCF/MCap%) | 20% | 20% | **指标替换**：股息率 → 自由现金流收益率，ETF 无 FCF 数据时回退股息率 |
| F3 宏观对冲 (SPY相关性倒数) | 20% | 20% | 不变 |
| F4 绝对低波 (波动率倒数) | 15% | **删除** | 与 F1 共线，下行风险已被 F1 覆盖 |
| F5 带鱼质量 → 升为 F4 | 15% | **30%** | 权重翻倍，成为第二大因子 |

### 改动范围
- `valuation-radar/core_engine.py`: `get_stock_metadata()` 新增 `fcf_yield` 字段（freeCashflow/marketCap*100，ETF 回退 dividendYield*100）；`ScorecardA.score()` F2 改用 `fcf_yield`，删除 F4 vol 计算，F5 权重乘数 15→30。
- `valuation-radar-ui/api_client.py`: `get_arena_a_factors._fetch_one()` 新增 `fcf_yield` 计算（stock.info.freeCashflow/marketCap，ETF 回退 div_yield），返回 dict 新增 `fcf_yield` 键，保留 `div_yield` 和 `ann_vol` 供 Z 组复用。
- `valuation-radar-ui/pages/3_资产细筛.py`: `ARENA_CONFIG["A"]` 权重/标签/logic 文案全部更新；`FACTOR_ANCHORS` 新增 `fcf_yield: (0.0, 10.0)`；`compute_scorecard_a()` 4 因子化，F2 改用 `FCF收益率` 列；数据加载映射 `FCF收益率` 列；`_render_podium_a()` 股息率行改为 FCF 收益率，factor pill 循环 range(1,6)→range(1,5)；冠军深度解读文案同步更新。

## 2026-04-12 | A 级带鱼质量因子 (Ribbon Quality Score) — F5 第五维度

### 设计哲学
A 级压舱石从「纯防守 4 因子」升级为「防守 + 温和趋势质量 5 因子」体系。带鱼质量分 (ribbon_score) 量化趋势的**干净程度**，核心原则：**不惩罚斜率大小，只衡量趋势是否平滑、持续、稳健**。

### 四个子维度 (合成 0~1 分数)
| 子维度 | 权重 | 定义 |
|--------|------|------|
| S1 MA 间距稳定性 | 30% | 近 120 日 `(ma20-ma60)/ma60` 的标准差取倒数，越小越平行 |
| S2 趋势持续天数 | 35% | 从今日往回连续满足 `ma20 > ma60` 的天数 ÷ 252 |
| S3 斜率稳定性 | 25% | 近 60 日 ma60 逐日变化率的变异系数 CV 取倒数，CV 越低越匀速 |
| S4 价格贴轨度 | 10% | 近 60 日 `(price-ma20)/ma20` 标准差取倒数，价格越紧贴均线越好 |

### 权重重分配
| 因子 | 原权重 | 新权重 | 变动 |
|------|--------|--------|------|
| F1 极限抗跌 | 35% | 30% | -5% |
| F2 现金奶牛 | 25% | 20% | -5% |
| F3 宏观对冲 | 20% | 20% | 不变 |
| F4 绝对低波 | 20% | 15% | -5% |
| **F5 带鱼质量** | — | **15%** | +15% |

### 改动范围
- `api_client.py`: `get_arena_a_factors._fetch_one()` 新增 ribbon_score 计算，history 期间从 `1y` 改为 `2y` 以保证 ma60 回溯充足。返回 dict 新增 `ribbon_score` 键。
- `pages/3_资产细筛.py`: FACTOR_ANCHORS 新增 `ribbon_quality: (0.0, 0.80)`；ARENA_CONFIG["A"] 更新权重与 factor_labels；`compute_scorecard_a()` 升级为 5 因子；数据映射新增 `df_a["带鱼质量"]` 列；`_A_FACTOR_COLORS` 追加第 5 色；`_render_podium_a()` 展示第 5 行指标与 F5 因子 pill；冠军深度解读追加 ribbon 文案。
- `core_engine.py`: `ScorecardA.score()` 同步新增 F5 ribbon 逻辑，权重调整为 30/20/20/15/15。

### Anchor 选择依据
`ribbon_quality` 锚点上限设为 0.80 而非 1.0：现实中 ribbon_score > 0.8 极为罕见（需要 S1/S3/S4 均接近满分且 ma20 > ma60 连续超 1 年），设 0.80 为满分等效点可拉开区分度，防止头部拥挤在 100 分附近。

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

## 2026-04-18

### ScorecardA v4 文案同步：F4 s5 改为 RS-line 斜率

**改动文件：** `pages/3_资产细筛.py`

与后端 v4 改动同步，前端两处文案更新：
1. A 组 tooltip ④ 行：`MA60斜率正值` → `RS线斜率`，补充「相对SPY强度主导」说明
2. 底层公式 expander：`ScorecardA v3` → `v4`，`s5_MA60斜率` → `s5_RS线MA60斜率`，满分阈值描述改为「年化跑赢 SPY +5%」
