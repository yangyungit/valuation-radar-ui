# 主理人用户现实记忆 (User Context)

> 本文件记录主理人的长期偏好、环境配置和已知事实，供跨会话参考。
> 每次获得新的稳定信息时追加更新。

---

## 身份与角色
- 本项目主理人，负责所有核心交易阵型的定义与最终决策
- 采用 Cursor IDE 进行 AI 协同开发，偏好精准行级编辑而非大段替换

## 开发环境
- **操作系统**：macOS（Apple Silicon Mac mini）
- **Shell**：zsh
- **Python 虚拟环境**：共享 venv 位于 `../system/venv/`，激活命令 `source ../system/venv/bin/activate`
- **后端启动**：`cd valuation-radar && source ../system/venv/bin/activate && python api_server.py`
- **前端启动**：`cd valuation-radar-ui && source ../system/venv/bin/activate && streamlit run app.py`
- **前端访问**：http://localhost:8501
- **后端访问**：http://localhost:8000

## 云端部署
- **后端平台**：Render.com，$7/月 Starter Web Service（按实例计费，非订阅会员）
  - Cron Job 功能：**可用**，独立按分钟计费（Starter 档 $0.00016/分钟，最低 $1/月起）
  - 每次 z_scanner.py 运行约 2-3 分钟，成本约 $0.003，月均 $0.01
  - ⚠️ Starter 套餐无流量时会自动休眠，冷启动需 30~60 秒
- **后端 Repo**：valuation-radar（部署在 Render Web Service）
- **后端 URL**：https://valuation-radar.onrender.com
- **前端平台**：Streamlit Cloud（https://yangyun-macro.streamlit.app/）
- **前端 Repo**：valuation-radar-ui（部署在 Streamlit Cloud，Linux 环境）

## 项目核心约束（勿违反）
- `my_stock_pool.py` 中 A/B/C/D 四大战术分组是最高业务机密，**绝对不允许**修改
- 前端页面严禁存放业务逻辑，必须通过 API 向后端请求
- 必须用中文与主理人交流

## 已安装依赖
- `finviz==2.0.0`（已安装到 system/venv，2026-04-12）

## 已配置自动化
- **crontab**（本地 Mac mini）：每周日 03:00 自动运行 z_scanner.py，日志输出到 `valuation-radar/z_scanner.log`
- **Render Cron Job**：尚未配置（2026-04-12 待办）

## 待办事项（长期）
- [ ] 在 Render 上配置 Cron Job 运行 z_scanner.py（每周日），实现云端 Z 级生息雷达全自动化
- [ ] SEC WATCHED_ISSUERS 定期补充新的发行人
- [ ] 考虑 STRD（Strategy 10% 非累积优先股）和 STRC（浮动利率月付优先股）加入 Z_SEED_POOL

## 沟通偏好
- 直接、简洁，不废话
- 重要决策要解释清楚再动手
- 遇到报错不要无限循环自调试，要告知主理人
