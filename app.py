"""侧边栏导航入口。

用 st.navigation 显式声明页面分组，代替 pages/ 目录自动发现——这样侧边栏能有分组小标题。
页面仍是 pages/ 下的平级文件，没有拆成子页面；URL 路径与自动发现时一致（数字前缀被剥掉）。
改页面顺序只需调下面列表的顺序，不用再重命名文件。
"""
import streamlit as st

st.set_page_config(page_title="Moltbot 宏观雷达", layout="wide", page_icon="📡")

nav = st.navigation({
    "": [
        st.Page("home.py", title="系统状态", default=True),
    ],
    "宏观与舆情": [
        st.Page("pages/0_宏观雷达.py", title="宏观雷达"),
        st.Page("pages/1_宏观定调.py", title="宏观定调"),
        st.Page("pages/2_舆情监控.py", title="舆情监控"),
    ],
    "旧策略链": [
        st.Page("pages/3_资产细筛.py", title="资产细筛"),
        st.Page("pages/3_资产细筛_GBDT.py", title="资产细筛 GBDT"),
        st.Page("pages/4_资产调研.py", title="资产调研"),
        st.Page("pages/5_个股择时.py", title="个股择时"),
        st.Page("pages/6_仓位配置.py", title="仓位配置"),
        st.Page("pages/6_持仓对比.py", title="持仓对比"),
    ],
    "大类观察": [
        st.Page("pages/7_风险预警.py", title="风险预警"),
        st.Page("pages/8_币圈流动性.py", title="币圈流动性"),
        st.Page("pages/9_机构持仓.py", title="机构持仓"),
        st.Page("pages/10_行业PE.py", title="行业PE"),
        st.Page("pages/11_基本面长图.py", title="基本面长图"),
        st.Page("pages/12_价格台阶.py", title="价格台阶"),
        st.Page("pages/13_因子轮动.py", title="因子轮动"),
        st.Page("pages/28_主题簇.py", title="主题簇"),
    ],
    "稳定类策略": [
        st.Page("pages/14_黄金带鱼.py", title="黄金带鱼"),
        st.Page("pages/15_带鱼斜率.py", title="带鱼斜率"),
        st.Page("pages/16_ROIC稳定.py", title="ROIC稳定"),
        st.Page("pages/17_FCF收益率稳定.py", title="FCF收益率稳定"),
        st.Page("pages/18_回购稳定.py", title="回购稳定"),
        st.Page("pages/19_板块王朝.py", title="板块王朝"),
    ],
    "进攻类策略": [
        st.Page("pages/20_FCF进攻.py", title="FCF进攻"),
        st.Page("pages/21_科技龙头.py", title="科技龙头"),
        st.Page("pages/22_动量双龙.py", title="动量双龙"),
        st.Page("pages/23_纳指100.py", title="纳指100"),
        st.Page("pages/24_戴金龙头.py", title="戴金龙头"),
        st.Page("pages/25_另类资产.py", title="另类资产"),
        st.Page("pages/27_行业龙头.py", title="行业龙头"),
    ],
    "总结": [
        st.Page("pages/26_组合净值.py", title="组合净值"),
    ],
})

nav.run()
