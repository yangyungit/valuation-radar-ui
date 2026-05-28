# Universe 扩容 W5A 收尾验收报告（2026-05-20）

> 本报告执行的是 W5A：Step 1/2/3/5/6/7 已落地，Step 4 只做 C 桥 day-0 baseline。由于 W2/W3/W4 均在 2026-05-20 当天落地，C 桥 7/14 天自然观察期未到，本轮不对 C 桥强弱做 pass/fail 判定。

## 0. 执行结论

- 结构验收通过：四个最薄 L2 的 breadth-eligible medium+ 成员均达到 `>=5`。
- V3 90 天 force 回填成功：`latest_common_date=2026-05-19`，38 个可用日期全部 computed，0 failed。
- C 桥 day-0 baseline 已完成：33 个新增 ticker 全部 `bridge_confidence >= medium`，其中 9 个已经 `C>0`，`low/none=0`。
- 健康巡检已落地：`stale_factor=0`，`narrative_orphan=0`；冷启动 ticker 未被误判为失败。
- 退场机制选择 B：不新增 `universe.status` schema，不自动 archive，只输出 watch / archive / proxy_only 建议清单。

复验日期：

- T+7：2026-05-27，补跑 C 桥爬升初验。
- T+14：2026-06-03，补跑 C 桥最终爬升验收。

## 1. 扩容前后基线

本轮扩容前基线使用 W2 前备份：

- `data/narrative.db.bak.w2_20260520_173327`
- `data/universe.db.bak.w2_20260520_173327`

`data/narrative.db.bak.w4_20260520_193501` 只代表 W4 改造前，不代表 universe 扩容前，因此未作为 W2/W3 扩容对比基线。

| 指标 | 扩容前 | 当前 | 变化 |
|---|---:|---:|---:|
| universe active | 116 | 149 | +33 |
| affinity active | 865 | 998 | +133 |
| affinity archived | 48 | 48 | +0 |
| active dictionary | 604 | 605 | +1 |
| T1 dictionary | 166 | 188 | +22 |
| 当前 active universe 分布 | - | stock 130 / etf 17 / crypto 2 | - |

W5 备份：

- `data/narrative.db.bak.w5_20260520_233721`
- `data/universe.db.bak.w5_20260520_233721`

## 2. Page2 Tab5 V3 动量轮动改善

V3 force 回填：

```text
success=true
date_count=38
computed=38
skipped=0
failed=0
latest_common_date=2026-05-19
```

90 天可比对比口径：使用 W2 前备份与当前库中共同可比日期，截止 `2026-05-11`。

| 指标 | 扩容前 | 当前 | 变化 |
|---|---:|---:|---:|
| 样本天数 | 85 | 85 | +0 |
| breadth 标准差均值 | 27.2941 | 22.1915 | -18.7% |
| breadth 平均值 | 34.4124 | 32.2523 | -2.16 |
| 主线 top1 切换次数 | 37 | 33 | -4 |
| Catalyst_Overlay top1 干扰次数 | 0 | 0 | +0 |

解读：breadth 平均值小幅下降，不是失败信号，主要是新增 ticker 加入后把真实截面从“少数老成员”扩展为更完整的成员篮子，短期会稀释部分高分老成员；更关键的是 breadth 标准差下降 18.7%，主线切换次数下降 4 次，说明扩容后轮动曲线更稳，没有被 Catalyst_Overlay 或 ETF 噪声打穿。

### 最薄 4 个 L2 验收

| L2 | 扩容前 breadth eligible | 当前 breadth eligible | 当前 all medium+ | 结论 |
|---|---:|---:|---:|---|
| Semi_Memory_&_Cycles | 2 | 6 | 6 | PASS |
| Space_Economy | 2 | 5 | 6 | PASS |
| Cybersecurity_&_Data | 2 | 5 | 6 | PASS |
| Crypto_Assets | 3 | 5 | 6 | PASS |

## 3. Page3 D 组共振守擂改善

本轮 D 组做了两层检查：

1. 直接对比 W2 前备份与当前 `d_snapshot_resonance` / `d_endurance_pool` 数据。
2. 用 `scripts/replay_d_endurance_local.py` 跑只读 30 天守擂回放，不覆盖生产 `d_endurance_*` 表。

### D snapshot 数据面对比

| 指标 | 扩容前备份 | 当前 | 变化 |
|---|---:|---:|---:|
| 30 天 STRONG_NARRATIVE 命中次数 | 253 | 253 | +0 |
| 30 天 bridge medium+ 命中次数 | 252 | 252 | +0 |
| 30 天 NO_NARRATIVE 次数 | 40 | 40 | +0 |
| 守擂池平均填充率 | 52.9% | 52.9% | +0.0% |
| 守擂池一日游率 | 75.0% | 75.0% | +0.0% |

说明：当前 `d_snapshot_resonance` 与 W2 前备份行数一致，代表 D snapshot 尚未按新 universe 重新生成。因此这里不是扩容没有改善，而是 D 组快照本身仍是扩容前数据面。W5A 只记录基线，不做最终 D 改善判定。

### 30 天只读守擂回放

| 指标 | 当前只读回放 |
|---|---:|
| 日期范围 | 2026-04-08 → 2026-05-19 |
| 实际天数 | 30 |
| 平均池容量 | 1.67 / 4 |
| 满座天数 | 3 |
| 空池天数 | 7 |
| ENROLLED | 20 |
| LANDED | 20 |
| LANDED_low_E | 20 |
| CASH_GATE_WARNING | 0 |
| DRIFT_WARNING | 4 |

只读输出：

- `../valuation-radar/scripts/output/w5_d_replay/d_endurance_replay_daily.csv`
- `../valuation-radar/scripts/output/w5_d_replay/d_endurance_replay_decisions.csv`
- `../valuation-radar/scripts/output/w5_d_replay/d_endurance_replay_pool.csv`

## 4. C 桥 day-0 baseline

本轮只做 day-0 打桩，不做最终爬升验收。

| 指标 | 数值 |
|---|---:|
| 新增 ticker | 33 |
| C>0 | 9 |
| low/none | 0 |
| T+7 复验 | 2026-05-27 |
| T+14 复验 | 2026-06-03 |

| ticker | L2 | A | C | S | B | conf | primary | degraded_C |
|---|---|---:|---:|---:|---:|---|---|---|
| ASML | AI_Infrastructure | 0.72 | 0.00 | 0.70 | 0.72 | medium | affinity | no_cooc_data |
| KLAC | AI_Infrastructure | 0.72 | 0.00 | 0.70 | 0.72 | medium | affinity | no_cooc_data |
| ORCL | AI_Monetization | 0.65 | 0.52 | 0.70 | 0.65 | high | affinity |  |
| NOW | AI_Monetization | 0.72 | 0.16 | 0.70 | 0.72 | medium | affinity |  |
| DE | Agri_&_Agriculture | 0.65 | 0.00 | 0.45 | 0.65 | medium | affinity | no_cooc_data |
| CTVA | Agri_&_Agriculture | 0.65 | 0.00 | 0.85 | 0.65 | medium | affinity | no_cooc_data |
| MOS | Agri_&_Agriculture | 0.78 | 0.00 | 0.85 | 0.78 | medium | affinity |  |
| MBLY | Autonomous_Mobility | 0.59 | 0.00 | 0.55 | 0.59 | medium | affinity | no_cooc_data |
| APTV | Autonomous_Mobility | 0.59 | 0.00 | 0.55 | 0.59 | medium | affinity | no_cooc_data |
| OUST | Autonomous_Mobility | 0.59 | 0.00 | 0.00 | 0.59 | medium | affinity |  |
| NVO | Biopharma_Ecosystem | 0.86 | 0.42 | 0.75 | 0.86 | high | affinity |  |
| MRK | Biopharma_Ecosystem | 0.78 | 0.87 | 0.75 | 0.78 | high | affinity |  |
| MSTR | Crypto_Assets | 0.84 | 1.00 | 0.00 | 0.84 | high | affinity |  |
| MARA | Crypto_Assets | 0.72 | 0.00 | 0.00 | 0.72 | medium | affinity | no_cooc_data |
| IBIT | Crypto_Assets | 0.78 | 1.00 | 0.00 | 0.78 | high | affinity |  |
| CRWD | Cybersecurity_&_Data | 0.84 | 0.00 | 0.55 | 0.84 | medium | affinity | no_cooc_data |
| PANW | Cybersecurity_&_Data | 0.72 | 0.00 | 0.55 | 0.72 | medium | affinity | no_cooc_data |
| ZS | Cybersecurity_&_Data | 0.72 | 0.00 | 0.55 | 0.72 | medium | affinity | no_cooc_data |
| CIBR | Cybersecurity_&_Data | 0.78 | 0.00 | 0.00 | 0.78 | medium | affinity | no_cooc_data |
| BX | Financials_&_Private_Credit | 0.84 | 0.28 | 0.75 | 0.84 | medium | affinity |  |
| HCA | Healthcare_Services_&_MedTech | 0.65 | 0.00 | 0.80 | 0.65 | medium | affinity | no_cooc_data |
| ELV | Healthcare_Services_&_MedTech | 0.72 | 0.00 | 0.75 | 0.72 | medium | affinity | no_cooc_data |
| NVR | Housing_&_Homebuilders | 0.78 | 0.00 | 0.85 | 0.78 | medium | affinity | no_cooc_data |
| TOL | Housing_&_Homebuilders | 0.72 | 0.00 | 0.85 | 0.72 | medium | affinity |  |
| XHB | Housing_&_Homebuilders | 0.72 | 0.00 | 0.00 | 0.72 | medium | affinity |  |
| CEG | Nuclear_&_AI_Power | 0.65 | 0.00 | 0.40 | 0.65 | medium | affinity | no_cooc_data |
| SNDK | Semi_Memory_&_Cycles | 0.72 | 0.73 | 0.35 | 0.72 | high | affinity |  |
| STX | Semi_Memory_&_Cycles | 0.65 | 0.65 | 0.35 | 0.65 | high | affinity |  |
| SIMO | Semi_Memory_&_Cycles | 0.65 | 0.00 | 0.70 | 0.65 | medium | affinity | no_cooc_data |
| RKLB | Space_Economy | 0.59 | 0.00 | 0.45 | 0.59 | medium | affinity | no_cooc_data |
| ASTS | Space_Economy | 0.65 | 0.00 | 0.00 | 0.65 | medium | affinity | no_cooc_data |
| IRDM | Space_Economy | 0.65 | 0.00 | 0.00 | 0.65 | medium | affinity | no_cooc_data |
| ARKX | Space_Economy | 0.65 | 0.00 | 0.00 | 0.65 | medium | affinity | no_cooc_data |

## 5. 健康巡检初次扫描结果

脚本：

- `../valuation-radar/scripts/universe_health_check.py`
- 输出：`../valuation-radar/scripts/output/universe_health_check.md`

结果：

| 类别 | 数量 | 结论 |
|---|---:|---|
| stale_factor | 0 | factor panel 已修复，无断流异常 |
| narrative_orphan | 0 | 没有 active ticker 在所有 active L2 上完全无桥 |
| C bridge weak | 62 | watch，不是 archive；新增未满 7 天 ticker 已豁免 |
| cold-start exempt | 20 | age < 7 days，不判 C 桥弱 |
| structural_warning | 1 | `US_Industrial_Reshoring` breadth eligible 只有 3 |
| archive_candidates | 0 | 本轮不建议自动归档 |

结构提醒：

| L2 | 问题 | 当前 |
|---|---|---:|
| US_Industrial_Reshoring | breadth-eligible medium+ members < 5 | 3 |

## 6. 退场与代理清单（选项 B）

本轮不新增 `universe.status` 字段，也不自动改库。退场机制以巡检输出为准，由主理人手工拍板。

| 清单 | 结果 |
|---|---|
| archive_candidates | none |
| proxy_only | AIQ, ARKX, CIBR, GLD, IBIT, IGV, ITA, PAVE, PICK, SMH, URA, XAR, XHB, XLP, XLU, XLV, XRT |

`C bridge weak` watch 清单较长，属于 C 桥自然观察和新闻链路成熟度问题，本轮不视为扩容失败。完整名单见 `../valuation-radar/scripts/output/universe_health_check.md`。

## 7. 遗留问题与下一步

1. 2026-05-27 补跑 C 桥 T+7 初验，重点看 `no_cooc_data` 是否从 24/33 明显下降。
2. 2026-06-03 补跑 C 桥 T+14 终验，再判断是否需要为 weak ticker 加词或重审 primary_l2。
3. `US_Industrial_Reshoring` 是本轮唯一结构短板，建议后续单独设计一小批 reshoring pure-play / infrastructure manufacturing 名单。
4. D 组 snapshot 尚未按新 universe 重算，本报告只保留 W5A 基线。等新快照自然累积或单独授权 D snapshot PIT 重算后，再做 D 改善判定。
5. overview 与 W5 plan 不归档为“全部完成”，保留到 T+7/T+14 复验完成后再归档。

## 8. 产物清单

后端：

- `../valuation-radar/scripts/w5_compare_v3.py`
- `../valuation-radar/scripts/universe_health_check.py`
- `../valuation-radar/scripts/output/w5_compare_v3.md`
- `../valuation-radar/scripts/output/w5_compare_v3.json`
- `../valuation-radar/scripts/output/universe_health_check.md`
- `../valuation-radar/scripts/output/universe_health_check.json`
- `../valuation-radar/scripts/output/w5_d_replay/*.csv`

前端：

- `data/universe_expansion_w5_report.md`
- `DEV_LOG.md`
