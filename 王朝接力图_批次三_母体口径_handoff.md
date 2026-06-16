# 王朝接力图 批次三交接：king_score 标准化母体（66 → 25）

> 给新窗口 agent 的自包含交接。读完即可接手讨论，无需翻前面的聊天。
> 跨两个仓库：后端 `valuation-radar`、前端 `valuation-radar-ui`。

## 一句话目标

王朝接力图判"谁戴金"用的 king_score，其横截面标准化母体目前是 **66 个跨资产标的**
（含美债、BTC、黄金、美元等），但产品文案宣称是"25 个板块横截面排名"。批次三要决定
**是否把母体收窄到 25 个板块 ETF**，并评估代价。**这是产品口径决策，不是纯 bug 修复。**

## 背景：王朝接力图是什么

Page0 `pages/0_宏观雷达.py` §1.6。它是三段流水线：

1. **每月谁戴金**：每个月末对板块按 `king_score` 排名，Top1 且 `RS_252d > 0` 戴金（🥇），
   Top2-3 戴银（🥈），其余灰。熊市（RS≤0）Top1 也降级为灰。
2. **连成王朝段**：连续戴金 ≥3 月 = 王朝，2 月 = 接力段，1 月 = 脉冲。
3. **钻取龙头**：每段调后端 `compute_dynasty_leaders` 取成分股超额 Top3。

`king_score` 公式（后端 `macro_engine.py`，权重常量 `_KING_SCORE_W_RS=1.0` / `_KING_SCORE_W_CAP=0.8`）：

```
king_score = 1.0 × Z(RS_252d) + 0.8 × Z(log10(ADV_63d))
```

- `Z(...)` = 横截面标准化（每个交易日对一组标的的该指标做 (x-mean)/std）。
- 第一项 = 年化动量（相对 SPY 的 252 日超额）。
- 第二项 = 容量（63 日成交额 log 后标准化），**目的是把 URA/TAN 这类小众主题盘
  从"时代之王"候选里压下去**——它们动量可能称霸，但盘子小、机构进不去。

## 已完成（批次一、二，别重复做）

- 后端 commit `170056c`、前端 commit `6d10018` + `ece815d`。
- 砍掉 1Y/2Y 窗口（radio 只剩 3Y/5Y/10Y）；当前未结束月标"进行中"不计入王朝月数；
  龙头钻取端点对齐（`common_start/common_end` + `stale_endpoint`）；脏 ticker 过滤；
  OKLO 借壳身份校正（`_TICKER_LISTING_OVERRIDE`，URA 2021-11 严格剔除 OKLO）。
- 已有测试 `valuation-radar/tests/test_dynasty_leaders.py`（3 passed）。
- 已存在 `profile` 机制：timeseries 端点 `/api/v1/macro/radar/timeseries?window=&profile=`，
  `profile=waveform`（§1.5 波形，短窗口用短 RS）与 `profile=dynasty`（§1.6 王朝，全用 RS_252d）
  已解耦。批次三正好在 `profile=dynasty` 分支里改母体。

## 批次三的核心问题（66 vs 25）

后端 `macro_engine.py` 的 `compute_radar_timeseries`，横截面标准化在约 **1360-1382 行**：
`rs_xs` / `log_adv_xs` 是对 `rs_df` / `adv_df` 的**全部列**（= `ASSET_GROUPS` 全部 66 个标的，
含 A 国别 / B 大宗货币 / C 核心板块 / D 细分赛道 / E 固收 / F 因子）做的标准化。

"25 个板块" = C 组 11 个（XLK/XLF/.../XLC）+ D 组 14 个（SMH/IGV/.../PAVE）。

**后果**：容量项 `Z(log10 ADV)` 把 25 个板块和美债、BTC 一起标准化。债券/宽基的 ADV 巨大，
ADV 分布被拉宽，URA 这类小众盘的"容量惩罚"被摊薄 → URA 比"只在 25 板块内比"时更容易戴金。

核验报告（`王朝接力图_五跨度数据核验_2026-06-10.md`）的实测：
- 2026-03：66 母体下 URA king_score=2.374 > SMH 2.092（URA 戴金）；
  仅 25 板块母体下 URA=1.965 < SMH=2.550（应 SMH 戴金）。
- 121 个共同月份中约 **24 个月的金牌归属仅因母体变化而改变**。
- 最近 13 个展示月：66 母体下 URA 7 金居首；25 母体下变成 SMH 7 金 / URA 4 金 / XLF 2 金。

## 我的修复方案设想（待新窗口深化）

**在 `profile=dynasty` 分支下，king_score 的两项标准化只用 25 个板块 ETF（C+D 组）的列做母体；
波形（composite）保持 66 母体不变。**

关键约束：`rs_xs` 当前被 king_score 和波形 `comp_df` 共用（1369-1370 行 comp = rs_xs ± z_xs）。
**不能直接改 `rs_xs`**，否则污染波形。做法是 dynasty profile 下为 king_score **单独**用
25 板块子集重算 `rs` 和 `log_adv` 的横截面 mean/std，与 66 母体的 `rs_xs` 分开。

注意：
- `rs` 字段本身（hover 显示的 RS_252d 绝对值）不受母体影响，不用动。
- 加冕门槛 `RS_252d > 0` 不变（绝对值判断）。
- rank 仍在前端选中组别内排（母体是"标准化分母"，rank 是"排名范围"，两回事）。
- 25 板块母体应取固定的 C+D 全集，**不随前端 selected_groups 变**（否则母体漂移、不可复现）。

## 为什么这是"大决策"，护栏是什么

- 改母体 = 改 king_score 值 = 改 rank = **改写约 24 个历史月份的金牌归属**。这等于动了主理人
  已审计信任的 5Y/10Y 历史金牌序列。**做完必须重新全量核验 5Y/10Y**（用独立数据源复算金牌），
  不能像批次一二那样靠"历史不变性断言"护住——这次历史本来就会变，要的是"变得正确"。
- 因此批次三不能和别的改动捆绑，要独立 commit、独立核验、独立回滚点。

## 待主理人/新窗口拍板的问题

1. **要不要做**：收窄到 25 板块更符合文案、也更能压制小众盘虚火；代价是改写历史金牌、URA
   退居次席。主理人要先认同"URA 不该在 1Y 居首"这个产品判断。
2. **母体到底取哪些**：纯 25 个板块 ETF（C+D），还是要不要把 SPY 这类基准也纳入/排除？
3. **容量项单项改还是整体改**：URA 偏差主要来自容量项（ADV 分布）。是否只把 `Z(log10 ADV)`
   的母体收窄到 25、而动量项 `Z(RS)` 保持 66？还是两项都收窄？需要定性 + 实测对比。
4. **历史核验口径**：用什么独立源、复算多少段，才算"批次三验收通过"。

## 相关代码落点速查

- `macro_engine.py` 1360-1382：横截面标准化 + king_df 合成（**主改点**）。
- `macro_engine.py` `_DYNASTY_WINDOW_CONFIG` / `compute_radar_timeseries(window, profile)`：profile 分支。
- `macro_engine.py` `ASSET_GROUPS`（约 1041 行）：C 组 = 核心板块，D 组 = 细分赛道，合计 25。
- 前端 `pages/0_宏观雷达.py` §1.6 `_render_relay`：消费 king_score，无需改（除非要加母体说明文案）。
- 核验报告：`valuation-radar-ui/王朝接力图_五跨度数据核验_2026-06-10.md`。
