三个可执行的改进方案
方案 1: 重构 F1 — 去掉股息率，释放 Quality 因子全力
当前 F1 = (div_norm + eps_stab_norm) / 2   ← div_norm 回填=0, 半废
改为 F1 = eps_stab_norm                     ← 质量信号直接翻倍
影响：在回填中，所有标的的 Quality 因子区分度直接翻倍。EPS 稳定性高的标的（如 AVGO、ETN、WMT）会获得更高分数，防御型低波动但实际走弱的标的会被拉开差距。

方案 2: 信念衰减加速 — 持续走弱时加速淘汰
在 conviction_engine.py 的 update_convictions() 中加入「加速衰减」逻辑：

当在位者因子分 < 35 时：
  decay = min(holder_decay, 0.70)   ← 不再享受慢衰减保护
效果：V (Visa) 的因子分在 2025-07 之后持续 31-34 分，如果用 0.70 衰减，信念会从 46.7 → 37.7（低于 exit_threshold 39），比实际早 2-3 个月被淘汰，避免 -9.8% alpha 损失。

方案 3: 权重再分配 — 进攻期 RS120d 和 Sharpe 要更激进
当前 Soft 权重：

(0.18 Quality, 0.18 Resilience, 0.20 Sharpe, 0.18 RS120d, 0.10 MCap, 0.10 Rev, 0.06 Macro)
建议调整：

(0.15 Quality, 0.13 Resilience, 0.22 Sharpe, 0.22 RS120d, 0.10 MCap, 0.12 Rev, 0.06 Macro)
从 Quality 和 Resilience 各削 3%/5% 给 Sharpe 和 RS120d。B组在牛市（2023 AI 牛市、2025 科技反弹）的结构性落后正是因为趋势因子权重不够。

修改涉及的文件
文件	改动
pages/3_资产细筛.py	compute_scorecard_b(): F1 去掉 div_norm，直接用 eps_stab_norm；B_REGIME_WEIGHTS 调整
conviction_engine.py	update_convictions(): 加速衰减逻辑
api_client.py	get_arena_b_factors(): 可以不再返回 div_yield（或保留但B组评分不用）
前端展示	ARENA_CONFIG["B"] 的 factor_labels 和 weights 需同步更新
三个方案可以同时做，互不冲突。 改完后需要重新回填历史数据（点回填按钮），再跑 pytest test_b_quality.py -v -s 验证效果。

