import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import os
import json
from datetime import datetime, timedelta
try:
    import pandas_datareader.data as web
except Exception:
    web = None
from api_client import fetch_core_data, get_global_data

# 1. 动态向云端 API 请求核心机密字典
core_data = fetch_core_data()
TIC_MAP = core_data.get("TIC_MAP", {})
REGIME_MAP = core_data.get("REGIME_MAP", {})
MACRO_TAGS_MAP = core_data.get("MACRO_TAGS_MAP", {})
USER_GROUPS_DEF = core_data.get("USER_GROUPS_DEF", {})

# --- 架构师注释: 宏观定调中心 v13.37 (终极量化逻辑升级版) ---
# 1. 实装 SPY 5阶状态机（强多头/多头回调/上涨力竭/强空头/震荡）。
# 2. SSOT 对齐缓存，消除 Z-Score 漂移与缩进报错。

st.set_page_config(page_title="宏观定调中心", layout="wide", page_icon="🧭")

with st.sidebar:
    st.header("🛠️ 系统维护")
    if st.button("🔄 仅清除当前页缓存"):
        fetch_core_data.clear()
        get_global_data.clear()
        try:
            get_liquidity_data.clear()
        except NameError:
            pass
        st.success("当前页缓存已清除！")
        st.rerun()
    if st.button("🗑️ 清除所有页面缓存"):
        st.cache_data.clear()
        st.success("所有页面缓存已清除！")
        st.rerun()

years_to_fetch = 10  # 10年原始数据，扣除750日预热后约7年着色范围，三大比例图视野充足
z_window = 750       # 统一使用 3Y (750日) 中期战略基准

st.markdown("""
<style>
    .metric-value { font-size: 24px; font-weight: bold; }
    .status-green { color: #2ECC71; font-weight: bold; font-size: 14px; }
    .status-red { color: #E74C3C; font-weight: bold; font-size: 14px; }
    .status-grey { color: #95A5A6; font-weight: bold; font-size: 14px; }
    
    .scenario-card { border-radius: 8px; padding: 15px; margin-bottom: 20px; border: 1px solid #444; background-color: #222; height: 100%; }
    .evidence-list { margin-top: 15px; border-top: 1px solid #444; padding-top: 10px; }
    .ev-item { margin-bottom: 6px; font-size: 14px; line-height: 1.5; display: flex; color: #ddd; }
    .ev-pass { color: #2ECC71; font-weight: bold; margin-right: 5px; }
    .ev-fail { color: #7f8c8d; margin-right: 5px; }
    
    .formula-box { background-color: #1a1a1a; border-left: 3px solid #3498DB; padding: 15px; margin-top: 10px; font-size: 14px; color: #ccc; }
    .conclusion-box { background-color: rgba(46, 204, 113, 0.1); border-left: 3px solid #2ECC71; padding: 12px; margin-top: 5px; font-size: 14px; color: #ddd; }
    .sub-ticker { font-size: 13px; color: #f1c40f; margin-left: 20px; border-left: 1px dashed #555; padding-left: 8px; margin-bottom: 4px;}
</style>
""", unsafe_allow_html=True)

st.title("🧭 宏观定调中心 (Macro Regime Center)")
st.caption("逻辑链：宏观底色/时钟 ➡️ **债市/因子 (可视化验证)** ➡️ **全证据链推演 (四象限裁决)**")

CLOCK_ASSETS = ["XLY", "XLP", "XLI", "XLU", "TIP", "IEF", "TLT", "SHY", "HYG", "UUP", "SPY", "LQD", "DBC"]
FACTOR_ASSETS = ["MTUM", "IWM", "SPHB", "ARKK", "USMV", "QUAL", "VLUE", "VIG"]
TARGETS_A = ["XLK", "XLC", "SMH", "IGV", "AIQ", "ITB", "XRT", "KWEB"] 
TARGETS_B = ["XLE", "XLI", "XOP", "OIH", "CPER", "URA", "PAVE", "PICK", "KRE", "USO"] 
TARGETS_C = ["GLD", "SLV", "DBA", "ITA", "URA"]
TARGETS_D = ["XLV", "XLU", "XLP"]

TOP_HOLDINGS = {
    "XLK": ["AAPL", "MSFT", "NVDA"], "XLC": ["META", "GOOGL", "NFLX"],
    "SMH": ["TSM", "AVGO", "AMD"], "IGV": ["CRM", "ADBE", "INTU"],
    "XLE": ["XOM", "CVX", "COP"], "XLI": ["GE", "CAT", "HON"],
    "XOP": ["EOG", "OXY", "COP"], "OIH": ["SLB", "BKR", "HAL"],
    "GLD": ["NEM", "GOLD", "AEM"], "SLV": ["PAAS", "AG", "HL"],
    "XLV": ["LLY", "UNH", "JNJ", "PFE"], 
    "XLU": ["NEE", "DUK", "SO"],
    "XLP": ["WMT", "COST", "KO", "PEP", "MCD"], 
    "KRE": ["USB", "PNC", "TFC"],
    "ITB": ["DHI", "LEN", "PHM"], "XRT": ["AMZN", "HD", "TGT"], 
    "URA": ["CCJ", "NXE", "UUUU"], "PAVE": ["VMC", "MLM", "URI"],
    "ITA": ["LMT", "NOC", "KTOS"], 
    "PICK": ["BHP", "VALE", "RIO"],
    "CPER": ["FCX", "SCCO", "TECK"], "DBA": ["ADM", "BG", "TSN"]
}

CONSTITUENT_STOCKS = []
for stocks in TOP_HOLDINGS.values(): CONSTITUENT_STOCKS.extend(stocks)
CONSTITUENT_STOCKS = list(set(CONSTITUENT_STOCKS))

ASSET_NAMES = {
    "XLK": "科技", "XLC": "通讯", "SMH": "半导体", "IGV": "软件", "AIQ": "AI", 
    "ITB": "房屋建筑", "XRT": "零售", "KWEB": "中概互联", "NVDA": "英伟达", "MSFT": "微软",
    "XLE": "能源", "XLI": "工业", "XOP": "油气开采", "OIH": "油服", "CPER": "铜", 
    "URA": "铀矿", "PAVE": "基建", "PICK": "矿业", "KRE": "区域银行", "USO": "原油",
    "BHP": "必和必拓", "VALE": "淡水河谷", "RIO": "力拓",
    "GLD": "黄金", "SLV": "白银", "DBA": "农产品", "XOM": "埃克森美孚", "MO": "奥驰亚", 
    "CCJ": "卡梅科", "NEM": "纽蒙特", "XLV": "医疗", "XLU": "公用", "XLP": "必选消费", "MCD": "麦当劳", 
    "WMT": "沃尔玛", "KO": "可口可乐", "PEP": "百事", "JNJ": "强生", "PFE": "辉瑞",
    "AAPL": "苹果", "META": "Meta", "GOOGL": "谷歌", "NFLX": "奈飞", "TSM": "台积电", 
    "AVGO": "博通", "AMD": "超威", "CRM": "赛富时", "ADBE": "Adobe", "INTU": "直觉软件",
    "CVX": "雪佛龙", "COP": "康菲石油", "GE": "通用电气", "CAT": "卡特彼勒", "HON": "霍尼韦尔",
    "EOG": "EOG能源", "OXY": "西方石油", "SLB": "斯伦贝谢", "BKR": "贝克休斯", "HAL": "哈里伯顿",
    "GOLD": "巴里克黄金", "AEM": "伊格尔矿业", "PAAS": "泛美白银", "AG": "First Majestic", "HL": "赫克拉",
    "LLY": "礼来", "UNH": "联合健康", "NEE": "新纪元能源", "DUK": "杜克能源", "SO": "南方公司",
    "PG": "宝洁", "USB": "美国合众银行", "PNC": "PNC金融", "TFC": "Truist",
    "DHI": "霍顿房屋", "LEN": "莱纳建筑", "PHM": "普尔特房屋", "COST": "开市客", "TGT": "塔吉特",
    "NXE": "NexGen", "UUUU": "Energy Fuels", "VMC": "火神材料", "MLM": "马丁玛丽埃塔", "URI": "联合租赁",
    "FCX": "自由港", "SCCO": "南方铜业", "TECK": "泰克资源", "ADM": "阿彻丹尼尔斯", "BG": "邦吉", "TSN": "泰森食品"
}

MACRO_ASSETS_ALL = ["XLY", "XLP", "XLI", "XLU", "TIP", "IEF", "TLT", "SHY", "HYG", "UUP", "LQD", "MTUM", "IWM", "SPHB", "ARKK", "USMV", "QUAL", "VLUE", "VIG", "SPY", "QQQ", "CPER", "USO", "DBC", "KRE", "GLD", "XLK", "RSP", "XLF", "XLB", "XLRE"]
# 核心宏观计算批次：仅 ETF/指数，不含成分股（成分股仅需 2 年，单独拉取以减少 12 年下载量）
MACRO_TICKERS_CORE = list(set(
    CLOCK_ASSETS + FACTOR_ASSETS + TARGETS_A + TARGETS_B + TARGETS_C + TARGETS_D + MACRO_ASSETS_ALL
))
MACRO_TICKERS_CORE.sort()

@st.cache_data(ttl=3600*4)
def get_liquidity_data():
    end_date = datetime.now()
    start_date = end_date - timedelta(days=3650)
    try:
        macro_codes = ['WALCL', 'WTREGEN', 'RRPONTSYD', 'BOGMBASE', 'M1SL', 'M2SL', 'CURRCIR', 'GFDEBTN']
        df_macro = web.DataReader(macro_codes, 'fred', start_date, end_date)
        df_macro = df_macro.resample('D').ffill()
    except:
        df_macro = pd.DataFrame()
    try:
        df_assets = yf.download(["SPY", "TLT", "GLD", "BTC-USD", "USO"], start=start_date, end=end_date, progress=False)['Close']
        df_assets = df_assets.resample('D').ffill()
    except:
        df_assets = pd.DataFrame()
    if not df_macro.empty and df_macro.index.tz is not None: df_macro.index = df_macro.index.tz_localize(None)
    if not df_assets.empty and df_assets.index.tz is not None: df_assets.index = df_assets.index.tz_localize(None)
    df_liq = pd.concat([df_macro, df_assets], axis=1).sort_index().ffill().dropna(how='all')
    if not df_liq.empty:
        if 'WALCL' in df_liq.columns: df_liq['Fed_Assets'] = df_liq['WALCL'] / 1000
        if 'WTREGEN' in df_liq.columns: df_liq['TGA'] = df_liq['WTREGEN'] / 1000
        if 'RRPONTSYD' in df_liq.columns: df_liq['RRP'] = df_liq['RRPONTSYD']
        if 'M2SL' in df_liq.columns: df_liq['M2'] = df_liq['M2SL']
        if 'M1SL' in df_liq.columns: df_liq['M1'] = df_liq['M1SL']
        if 'BOGMBASE' in df_liq.columns: df_liq['M0'] = df_liq['BOGMBASE'] / 1000
        if 'CURRCIR' in df_liq.columns: df_liq['Currency'] = df_liq['CURRCIR'] / 1000
        if 'GFDEBTN' in df_liq.columns:
            df_liq['Total_Debt'] = (df_liq['GFDEBTN'] / 1000).interpolate(method='linear')
            df_liq['Fiscal_Injection'] = df_liq['Total_Debt'].diff(365)
        if all(c in df_liq.columns for c in ['Fed_Assets', 'TGA', 'RRP']):
            df_liq['Net_Liquidity'] = df_liq['Fed_Assets'] - df_liq['TGA'] - df_liq['RRP']
    return df_liq

@st.cache_data(ttl=3600*4)
def get_clock_fred_data():
    """Phase 1: 拉取 FRED 宏观官方数据，构建混合数据管道的官方侧。
    增长侧三锚: INDPRO (工业生产), PAYEMS (非农就业), RSAFS (零售销售) — 均计算 YoY
    通胀侧双锚: CPILFESL (核心CPI), PCEPILFE (核心PCE) — 均计算 YoY
    市场侧:    BAMLH0A0HYM2 (HY信用利差, 日度), T10YIE (10年隐含通胀预期, 日度)
    """
    if web is None:
        raise RuntimeError("pandas_datareader 未安装")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=3650 + 400)
    df_fred = web.DataReader(
        ['CPILFESL', 'PCEPILFE', 'BAMLH0A0HYM2', 'T10YIE', 'INDPRO', 'PAYEMS', 'RSAFS'],
        'fred', start_date, end_date
    )
    if df_fred.index.tz is not None:
        df_fred.index = df_fred.index.tz_localize(None)
    result = pd.DataFrame(index=df_fred.index)
    if 'CPILFESL' in df_fred.columns:
        result['Core_CPI_YoY'] = df_fred['CPILFESL'].pct_change(12) * 100
    if 'PCEPILFE' in df_fred.columns:
        result['Core_PCE_YoY'] = df_fred['PCEPILFE'].pct_change(12) * 100
    if 'BAMLH0A0HYM2' in df_fred.columns:
        result['HY_Spread'] = df_fred['BAMLH0A0HYM2']
    if 'T10YIE' in df_fred.columns:
        result['T10YIE'] = df_fred['T10YIE']
    if 'INDPRO' in df_fred.columns:
        result['INDPRO_YoY'] = df_fred['INDPRO'].pct_change(12) * 100
    if 'PAYEMS' in df_fred.columns:
        result['PAYEMS_YoY'] = df_fred['PAYEMS'].pct_change(12) * 100
    if 'RSAFS' in df_fred.columns:
        result['RSAFS_YoY'] = df_fred['RSAFS'].pct_change(12) * 100
    result = result.dropna(how='all').resample('D').ffill()
    return result

_FRED_EMPTY = pd.DataFrame(columns=['Core_CPI_YoY', 'Core_PCE_YoY', 'HY_Spread', 'T10YIE', 'INDPRO_YoY', 'PAYEMS_YoY', 'RSAFS_YoY'])

with st.spinner(f"⏳ 正在拉取宏观数据管道 ({years_to_fetch}年历史 · {len(MACRO_TICKERS_CORE)} 个 ETF/指数)..."):
    df = get_global_data(MACRO_TICKERS_CORE, years=years_to_fetch)

with st.spinner("📡 正在接入 FRED 官方宏观数据管道 (INDPRO + PAYEMS + RSAFS + CPI + PCE + HY Spread)..."):
    try:
        df_fred_clock = get_clock_fred_data()
        _fred_ok = not df_fred_clock.empty
    except Exception:
        df_fred_clock = _FRED_EMPTY
        _fred_ok = False
    if not _fred_ok:
        st.warning("⚠️ FRED 数据暂时不可用，信用利差与核心CPI将降级为 ETF 代理指标。")

if not df.empty and len(df) > 750:
    
    def get_ret(ticker, days=20): 
        if ticker in df.columns:
            s = df[ticker].dropna()
            if len(s) > days:
                return float((s.iloc[-1] / s.iloc[-1-days] - 1) * 100)
        return 0.0

    def _zscore(series, window=z_window):
        """滚动预期边际差 (窗口={z_window}日)，防零除，保持原始 index。"""
        mu = series.rolling(window=window).mean()
        sigma = series.rolling(window=window).std()
        return (series - mu) / sigma.where(sigma > 0)

    def _ratio_z_curr(a_col, b_col):
        """返回 a/b 比值的 3Y 滚动 Z-Score 当前值（20日均线预平滑）。全页面统一度量衡。"""
        if a_col not in df.columns or b_col not in df.columns:
            return 0.0
        z_s = _zscore((df[a_col] / df[b_col].replace(0, np.nan)).rolling(20).mean()).dropna()
        return float(z_s.iloc[-1]) if not z_s.empty else 0.0

    # ── 横轴：经济预期边际差复合 (三引擎等权合成) ──────────────────
    # 引擎1: 铜金比 CPER/GLD — 全球宏观周期的终极测温枪
    # 铜代表工业需求/增长，黄金代表避险/通缩。比率↑ = 全球增长共振
    z_copper_gold = _zscore(
        (df['CPER'] / df['GLD'].replace(0, np.nan)).rolling(20).mean()
    )
    # 引擎2: 工业实体 XLI/XLU — 美股内部实体复苏信号
    z_industrial = _zscore(
        (df['XLI'] / df['XLU'].replace(0, np.nan)).rolling(20).mean()
    )
    # 引擎3: 信用扩张 — FRED HY Spread 反转（利差↓=经济↑），降级则用 HYG/IEF
    if _fred_ok and 'HY_Spread' in df_fred_clock.columns:
        _hy_raw = df_fred_clock['HY_Spread'].reindex(df.index).ffill().rolling(20).mean()
        z_credit = _zscore(_hy_raw) * -1
        _credit_label = "FRED BAMLH0A0HYM2 利差 (反转)"
    else:
        _hy_raw = (df['HYG'] / df['IEF'].replace(0, np.nan)).rolling(20).mean()
        z_credit = _zscore(_hy_raw)
        _credit_label = "ETF代理 HYG/IEF (FRED降级)"

    growth_z = pd.DataFrame({
        'Z_copper_gold': z_copper_gold,
        'Z_industrial': z_industrial,
        'Z_credit': z_credit,
    }).mean(axis=1)

    # ── 纵轴：通胀预期边际差复合 (三引擎等权合成) ──────────────────────
    # 引擎1: FRED T10YIE 10年期隐含通胀预期 — 债市聪明钱的前瞻锚
    # 降级 fallback: TIP/IEF ETF 代理（当 FRED 不可用时）
    if _fred_ok and 'T10YIE' in df_fred_clock.columns:
        _t10yie_raw = df_fred_clock['T10YIE'].reindex(df.index).ffill().rolling(20).mean()
        z_t10yie = _zscore(_t10yie_raw)
        _t10yie_label = "FRED T10YIE 10年期隐含通胀预期 (前瞻)"
    else:
        _t10yie_raw = (df['TIP'] / df['IEF'].replace(0, np.nan)).rolling(20).mean()
        z_t10yie = _zscore(_t10yie_raw)
        _t10yie_label = "ETF代理 TIP/IEF (FRED T10YIE 降级)"
    # 引擎2: 实物资产溢价 DBC/IEF — 大宗商品 vs 法币债券，盯死当下
    z_commodity = _zscore(
        (df['DBC'] / df['IEF'].replace(0, np.nan)).rolling(20).mean()
    )
    # 引擎3: 官方核心通胀 FRED CPILFESL YoY — 官方后视镜锚点
    _infl_components = {'Z_t10yie': z_t10yie, 'Z_commodity': z_commodity}
    if _fred_ok and 'Core_CPI_YoY' in df_fred_clock.columns:
        _cpi_raw = df_fred_clock['Core_CPI_YoY'].reindex(df.index).ffill()
        z_cpi = _zscore(_cpi_raw)
        _infl_components['Z_cpi'] = z_cpi
        _cpi_label = "FRED CPILFESL 核心CPI YoY"
    else:
        _cpi_label = "N/A (FRED不可用，双引擎降级)"

    inflation_z = pd.DataFrame(_infl_components).mean(axis=1)

    # ── Phase 1: 双星数据管道解耦 ─────────────────────────────────────
    # 🌟 星星 A：市场前瞻星 (Market Leading Star) — 领先官方数据 3-6 个月
    # Growth X: 铜金比 + HY利差反转 + 工业公用比 (纯市场实时定价)
    # Inflation Y: T10YIE + DBC/IEF (债市+大宗前瞻，严格剔除官方CPI)
    star_a_g = growth_z
    star_a_i = pd.DataFrame({'Z_t10yie': z_t10yie, 'Z_commodity': z_commodity}).mean(axis=1)

    # ⬛ 星星 B：政府滞后星 (Gov Lagging Star) — 滞后真实经济 1-3 个月
    # Growth X: 三引擎等权合成 — ① 工业锚 INDPRO  ② 就业锚 PAYEMS  ③ 消费锚 RSAFS
    _gov_growth_components = {}
    if _fred_ok and 'INDPRO_YoY' in df_fred_clock.columns:
        _indpro_raw = df_fred_clock['INDPRO_YoY'].reindex(df.index).ffill().rolling(20).mean()
        _gov_growth_components['Z_indpro'] = _zscore(_indpro_raw)
        _indpro_label = "FRED INDPRO 工业生产指数 YoY"
    else:
        _indpro_label = "N/A (FRED不可用)"
    if _fred_ok and 'PAYEMS_YoY' in df_fred_clock.columns:
        _payems_raw = df_fred_clock['PAYEMS_YoY'].reindex(df.index).ffill().rolling(20).mean()
        _gov_growth_components['Z_payems'] = _zscore(_payems_raw)
        _payems_label = "FRED PAYEMS 非农就业人数 YoY"
    else:
        _payems_label = "N/A (FRED不可用)"
    if _fred_ok and 'RSAFS_YoY' in df_fred_clock.columns:
        _rsafs_raw = df_fred_clock['RSAFS_YoY'].reindex(df.index).ffill().rolling(20).mean()
        _gov_growth_components['Z_rsafs'] = _zscore(_rsafs_raw)
        _rsafs_label = "FRED RSAFS 零售销售总额 YoY"
    else:
        _rsafs_label = "N/A (FRED不可用)"
    if _gov_growth_components:
        star_b_g = pd.DataFrame(_gov_growth_components).mean(axis=1)
    else:
        star_b_g = _zscore((df['XLY'] / df['XLP'].replace(0, np.nan)).rolling(20).mean())
        _indpro_label = "ETF代理 XLY/XLP (所有官方增长数据均不可用)"
        _payems_label = _rsafs_label = "N/A (降级至 ETF 代理)"

    # Inflation Y: 双引擎等权合成 — ① CPI锚 CPILFESL  ② PCE锚 PCEPILFE
    _gov_infl_components = {}
    _star_b_i_series = _infl_components.get('Z_cpi')
    if _star_b_i_series is not None:
        _gov_infl_components['Z_cpi'] = _star_b_i_series
        _gov_cpi_label = "FRED CPILFESL 核心CPI YoY"
    else:
        _gov_cpi_label = "N/A (FRED不可用)"
    if _fred_ok and 'Core_PCE_YoY' in df_fred_clock.columns:
        _pce_raw = df_fred_clock['Core_PCE_YoY'].reindex(df.index).ffill()
        _gov_infl_components['Z_pce'] = _zscore(_pce_raw)
        _gov_pce_label = "FRED PCEPILFE 核心PCE YoY"
    else:
        _gov_pce_label = "N/A (FRED不可用)"
    if _gov_infl_components:
        star_b_i = pd.DataFrame(_gov_infl_components).mean(axis=1)
        _gov_infl_label = "双引擎合成 (CPI + PCE)" if len(_gov_infl_components) == 2 else list(_gov_infl_components.keys())[0]
    else:
        star_b_i = _zscore((df['TIP'] / df['IEF'].replace(0, np.nan)).rolling(20).mean())
        _gov_infl_label = "ETF代理 TIP/IEF (CPI+PCE均不可用)"
        _gov_cpi_label = _gov_pce_label = "N/A (降级至 ETF 代理)"

    # ── 双星当前坐标 ──────────────────────────────────────────────────
    df_z_a = pd.DataFrame({'Growth': star_a_g, 'Inflation': star_a_i}).dropna()
    df_z_b = pd.DataFrame({'Growth': star_b_g, 'Inflation': star_b_i}).dropna()
    star_a_g_curr = float(df_z_a['Growth'].iloc[-1]) if not df_z_a.empty else 0.0
    star_a_i_curr = float(df_z_a['Inflation'].iloc[-1]) if not df_z_a.empty else 0.0
    star_b_g_curr = float(df_z_b['Growth'].iloc[-1]) if not df_z_b.empty else 0.0
    star_b_i_curr = float(df_z_b['Inflation'].iloc[-1]) if not df_z_b.empty else 0.0

    # 向后兼容：主时钟象限裁决与轨迹由市场前瞻星 A 驱动
    df_z = df_z_a
    curr_clock_g = star_a_g_curr
    curr_clock_i = star_a_i_curr

    def _get_quad(g, i):
        if abs(g) < 0.5 and abs(i) < 0.5: return "软着陆"
        elif g > 0 and i <= 0: return "软着陆"
        elif g > 0 and i > 0: return "再通胀"
        elif g <= 0 and i > 0: return "滞胀"
        else: return "衰退"

    _quad_a = _get_quad(star_a_g_curr, star_a_i_curr)
    _quad_b = _get_quad(star_b_g_curr, star_b_i_curr)

    # Phase 3: 象限裁决 — 优先判断"软着陆"中心区（双轴 Z 均在 ±0.5 以内）
    if _quad_a == "软着陆":
        _quadrant_name = "🚗 软着陆 (Soft Landing)"
        _quadrant_color = "#27AE60"
    elif _quad_a == "再通胀":
        _quadrant_name = "🔥 再通胀 (Reflation)"
        _quadrant_color = "#E74C3C"
    elif _quad_a == "滞胀":
        _quadrant_name = "🚨 滞胀 (Stagflation)"
        _quadrant_color = "#F1C40F"
    else:
        _quadrant_name = "❄️ 衰退 (Recession)"
        _quadrant_color = "#3498DB"

    # 宏观底色四维 Z-Score（3Y 滚动基准，与宏观时钟同一度量衡）
    tlt_shy_diff = _ratio_z_curr('TLT', 'SHY')   # 长债/短债 Z-Score (>0=长端历史性强)
    hyg_ief_diff = _ratio_z_curr('HYG', 'IEF')   # 信用/国债 Z-Score (>0=Risk-On)
    tip_ief_diff = _ratio_z_curr('TIP', 'IEF')   # 通胀保值/名义 Z-Score (>0=通胀升温)
    usd_val      = _ratio_z_curr('UUP', 'SHY')   # 美元/现金 Z-Score (>0=美元历史性走强)
    
    # =======================================================
    # 🧠 架构师级更新：实装 SPY 5阶趋势状态机，精准捕捉“力竭”与“回调”
    # =======================================================
    spy_ts = df['SPY'].dropna()
    is_bullish = False
    if len(spy_ts) > 120:
        spy_cur = float(spy_ts.iloc[-1])
        ma20 = float(spy_ts.rolling(20).mean().iloc[-1])
        ma60 = float(spy_ts.rolling(60).mean().iloc[-1])
        ma120 = float(spy_ts.rolling(120).mean().iloc[-1])
        
        if spy_cur > ma20 and ma20 > ma60 and ma60 > ma120:
            spy_status = "🔥 强多头 (完美均线多头排列)"
            is_bullish = True
        elif ma20 > spy_cur > ma60 and ma60 > ma120:
            spy_status = "⚠️ 多头回调 (跌破20日线，短期喘息)"
            is_bullish = True  # 核心趋势未破，仍定性为上升通道
        elif spy_cur < ma60 and ma20 > ma120:
            spy_status = "🌩️ 上涨力竭 (跌破60日生命线/顶背离)"
            is_bullish = False # 核心趋势已破，警报拉响
        elif spy_cur < ma20 and ma20 < ma60 and ma60 < ma120:
            spy_status = "❄️ 强空头 (完美均线空头排列)"
            is_bullish = False
        else:
            spy_status = "⚖️ 震荡分化 (均线交叉纠缠/无趋势)"
            is_bullish = False
    else:
        spy_status = "未知 (数据不足)"
    # =======================================================

    def _fl(label, series_id):
        """将 FRED 序列标签包装为可点击超链接；仅当 label 含 'FRED' 字样时生效。"""
        if series_id and 'FRED' in label:
            url = f"https://fred.stlouisfed.org/series/{series_id}"
            return f'<a href="{url}" target="_blank" style="color:#2ECC71; text-decoration:underline dotted;">{label}</a>'
        return label

    _indpro_label_fl  = _fl(_indpro_label,  'INDPRO')
    _payems_label_fl  = _fl(_payems_label,  'PAYEMS')
    _rsafs_label_fl   = _fl(_rsafs_label,   'RSAFS')
    _gov_cpi_label_fl = _fl(_gov_cpi_label, 'CPILFESL')
    _gov_pce_label_fl = _fl(_gov_pce_label, 'PCEPILFE')
    _t10yie_label_fl  = _fl(_t10yie_label,  'T10YIE')
    _credit_label_fl  = _fl(_credit_label,  'BAMLH0A0HYM2')
    _cpi_label_fl     = _fl(_cpi_label,     'CPILFESL')

    # ─── 大盘趋势状态机 (Market Trend Matrix) ────────────────────────────────
    st.subheader("📊 大盘趋势状态机 (Market Trend Matrix)")
    st.caption("基于 Close / MA60 / MA200 的四象限绝对强弱切割")

    _MTM_COLORS = {
        "主升狂飙": "#2ECC71",
        "颠簸震荡": "#F1C40F",
        "冰面滑行": "#E74C3C",
        "触底抢修": "#3498DB",
    }
    _MTM_EN = {
        "主升狂飙": "Full Throttle",
        "颠簸震荡": "Bumpy Road",
        "冰面滑行": "Slippery Ice",
        "触底抢修": "Bottom Rebound",
    }
    _MTM_DESC = {
        "主升狂飙": "Close > MA60 > MA200：均线完美多头排列，主力趋势全面向上，进攻优先，是持仓最舒适的环境。",
        "颠簸震荡": "Close < MA60，MA60 > MA200：价格跌破 60 日生命线，但长期趋势（MA200）仍上行，属牛市内部震荡回调，需等待重新站上 MA60 确认。",
        "冰面滑行": "Close < MA60 < MA200：均线空头排列，价格在双均线下方滑行，市场处于下跌通道，风险最高，严控仓位。",
        "触底抢修": "Close > MA60，MA60 < MA200：短期动能回归站上 MA60，但 200 日长期趋势仍朝下，属底部修复试探信号，需谨慎观察 MA200 能否被打穿。",
    }
    _MTM_INDEX_OPTIONS = {
        "🇺🇸 SPY (标普500)":     "SPY",
        "📡 QQQ (纳斯达克100)": "QQQ",
    }
    _MTM_INDEX_YLABEL = {"SPY": "SPY 收盘价 ($)", "QQQ": "QQQ 收盘价 ($)"}

    def _classify_mtm(row):
        c, m60, m200 = row['close'], row['ma60'], row['ma200']
        if c > m60 and m60 > m200:   return "主升狂飙"
        elif c < m60 and m60 > m200: return "颠簸震荡"
        elif c < m60 and m60 < m200: return "冰面滑行"
        else:                        return "触底抢修"

    _mtm_tab_spy, _mtm_tab_qqq = st.tabs(["🇺🇸 SPY (标普500)", "📡 QQQ (纳斯达克100)"])

    def _render_mtm_tab(ticker, tab):
        with tab:
            if ticker not in df.columns:
                st.warning(f"⚠️ {ticker} 数据暂不可用")
                return
            _full  = df[ticker].dropna().astype(float)
            _ma60  = _full.rolling(60).mean()
            _ma200 = _full.rolling(200).mean()
            _df = pd.DataFrame({'close': _full, 'ma60': _ma60, 'ma200': _ma200}).dropna()
            _df['phase'] = _df.apply(_classify_mtm, axis=1)

            if _df.empty:
                st.warning(f"⚠️ {ticker} 数据不足（需至少 200 个交易日），无法计算 MA200")
                return
            _latest    = _df.iloc[-1]
            _phase     = _latest['phase']
            _price     = float(_latest['close'])
            _ma60_val  = float(_latest['ma60'])
            _ma200_val = float(_latest['ma200'])
            _color     = _MTM_COLORS.get(_phase, "#888")
            _date_str  = _df.index[-1].strftime('%Y-%m-%d')

            st.markdown(f"""
            <div style='background:#1a1a1a; border-left:5px solid {_color}; border-radius:8px; padding:14px 20px; margin-bottom:12px; display:flex; align-items:center; gap:32px;'>
                <div>
                    <div style='font-size:13px; color:#aaa; margin-bottom:4px;'>当前阶段（{_date_str}）</div>
                    <div style='font-size:28px; font-weight:bold; color:{_color}; margin-bottom:2px;'>{_phase}</div>
                    <div style='font-size:14px; color:#ccc;'>{_MTM_EN.get(_phase, "")}</div>
                </div>
                <div style='font-size:13px; color:#aaa; line-height:2.0; border-left:1px solid #333; padding-left:24px;'>
                    <b>Close &nbsp;</b> <span style='color:#ddd;'>${_price:.2f}</span><br>
                    <b>MA60 &nbsp;&nbsp;</b> <span style='color:#F1C40F;'>${_ma60_val:.2f}</span><br>
                    <b>MA200 &nbsp;</b> <span style='color:#3498DB;'>${_ma200_val:.2f}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            _change_pts = [0]
            for _i in range(1, len(_df)):
                if _df['phase'].iloc[_i] != _df['phase'].iloc[_i - 1]:
                    _change_pts.append(_i)
            _change_pts.append(len(_df))

            _traces = []
            _seen   = set()
            for _j in range(len(_change_pts) - 1):
                _s  = _change_pts[_j]
                _e  = min(_change_pts[_j + 1] + 1, len(_df))
                _seg = _df.iloc[_s:_e]
                _ph  = _df['phase'].iloc[_s]
                _traces.append(go.Scatter(
                    x=_seg.index,
                    y=_seg['close'].astype(float).values,
                    mode='lines',
                    line=dict(color=_MTM_COLORS.get(_ph, '#888'), width=2),
                    name=_ph,
                    showlegend=(_ph not in _seen),
                    legendgroup=_ph,
                ))
                _seen.add(_ph)

            _fig = go.Figure()
            for _tr in _traces:
                _fig.add_trace(_tr)
            _fig.add_trace(go.Scatter(
                x=_df.index, y=_df['ma60'].astype(float),
                mode='lines', name='MA60',
                line=dict(color='rgba(241,196,15,0.5)', width=1, dash='dot'),
            ))
            _fig.add_trace(go.Scatter(
                x=_df.index, y=_df['ma200'].astype(float),
                mode='lines', name='MA200',
                line=dict(color='rgba(52,152,219,0.5)', width=1, dash='dash'),
            ))
            _fig.update_layout(
                height=340,
                margin=dict(l=20, r=20, t=40, b=20),
                plot_bgcolor='#1a1a1a', paper_bgcolor='#1a1a1a',
                font=dict(color='#ddd'),
                showlegend=True,
                legend=dict(orientation="h", y=1.18, x=0.5, xanchor="center", font=dict(size=12)),
                hovermode="x unified",
                xaxis=dict(showgrid=False),
                yaxis=dict(title=_MTM_INDEX_YLABEL.get(ticker, f"{ticker} 收盘价 ($)"), showgrid=True, gridcolor='rgba(255,255,255,0.06)'),
                title=dict(text=f"{ticker} 历史路况：分段染色折线图", font=dict(size=14), x=0.01, xanchor='left'),
            )
            st.plotly_chart(_fig, use_container_width=True)

            _desc = _MTM_DESC.get(_phase, "")
            st.markdown(f"""
            <div style='background:#1a1a1a; border-left:4px solid {_color}; border-radius:6px; padding:12px 16px; margin-top:4px;'>
                <div style='font-size:13px; color:#aaa; margin-bottom:5px;'>🧠 当前阶段白盒解读</div>
                <div style='font-size:14px; color:#ddd; line-height:1.75;'>{_desc}</div>
            </div>
            <div style='background:#111; border:1px solid #2a2a2a; border-radius:6px; padding:14px 18px; margin-top:8px;'>
                <div style='font-size:13px; color:#888; margin-bottom:10px; letter-spacing:0.3px;'>📐 四色染色判断标准（Close / MA60 / MA200）</div>
                <div style='display:grid; grid-template-columns:1fr 1fr; gap:8px;'>
                    <div style='background:#1a1a1a; border-left:3px solid #2ECC71; border-radius:4px; padding:8px 12px;'>
                        <div style='font-size:13px; font-weight:bold; color:#2ECC71; margin-bottom:3px;'>🟢 主升狂飙 · Full Throttle</div>
                        <div style='font-size:13px; color:#aaa; line-height:1.6;'>Close &gt; MA60 &gt; MA200<br>均线完美多头排列，趋势最强</div>
                    </div>
                    <div style='background:#1a1a1a; border-left:3px solid #F1C40F; border-radius:4px; padding:8px 12px;'>
                        <div style='font-size:13px; font-weight:bold; color:#F1C40F; margin-bottom:3px;'>🟡 颠簸震荡 · Bumpy Road</div>
                        <div style='font-size:13px; color:#aaa; line-height:1.6;'>Close &lt; MA60，MA60 &gt; MA200<br>牛市内部回调，长期趋势仍健康</div>
                    </div>
                    <div style='background:#1a1a1a; border-left:3px solid #3498DB; border-radius:4px; padding:8px 12px;'>
                        <div style='font-size:13px; font-weight:bold; color:#3498DB; margin-bottom:3px;'>🔵 触底抢修 · Bottom Rebound</div>
                        <div style='font-size:13px; color:#aaa; line-height:1.6;'>Close &gt; MA60，MA60 &lt; MA200<br>短期动能回归，长期趋势仍朝下</div>
                    </div>
                    <div style='background:#1a1a1a; border-left:3px solid #E74C3C; border-radius:4px; padding:8px 12px;'>
                        <div style='font-size:13px; font-weight:bold; color:#E74C3C; margin-bottom:3px;'>🔴 冰面滑行 · Slippery Ice</div>
                        <div style='font-size:13px; color:#aaa; line-height:1.6;'>Close &lt; MA60 &lt; MA200<br>均线空头排列，风险最高，严控仓位</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

    _render_mtm_tab("SPY", _mtm_tab_spy)
    _render_mtm_tab("QQQ", _mtm_tab_qqq)

    # 供后续 SPY 5阶状态机逻辑继续使用
    _spy_full  = df['SPY'].dropna().astype(float)
    _spy_ma60  = _spy_full.rolling(60).mean()
    _spy_ma200 = _spy_full.rolling(200).mean()
    _df_mtm = pd.DataFrame({'close': _spy_full, 'ma60': _spy_ma60, 'ma200': _spy_ma200}).dropna()
    _df_mtm['phase'] = _df_mtm.apply(_classify_mtm, axis=1)
    _mtm_latest    = _df_mtm.iloc[-1]
    _mtm_phase     = _mtm_latest['phase']
    _mtm_color     = _MTM_COLORS.get(_mtm_phase, "#888")

    st.markdown("---")

    st.header("1️⃣ 宏观底色 (Macro Dashboard)")

    st.markdown("---")
    if tlt_shy_diff > 0: rate_txt = "📉 增长放缓"; rate_cls = "status-red" 
    else: rate_txt = "📈 增长强劲"; rate_cls = "status-green"
    if hyg_ief_diff > 0: risk_txt = "🦁 Risk-On"; risk_cls = "status-green"
    else: risk_txt = "❄️ Risk-Off"; risk_cls = "status-red"
    if tip_ief_diff > 0: inf_txt = "🎈 通胀升温"; inf_cls = "status-red"
    else: inf_txt = "💧 通胀回落"; inf_cls = "status-green"
    if usd_val > 0: usd_txt = "💪 美元走强"; usd_cls = "status-red"
    else: usd_txt = "🍃 美元走弱"; usd_cls = "status-green"

    c1, c2, c3, c4 = st.columns(4)
    def draw_card(col, title, val, txt, cls, desc):
        with col:
            st.markdown(f"**{title}**")
            st.markdown(f"<div class='metric-value'>{val:+.2f}σ</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='{cls}'>{txt}</div>", unsafe_allow_html=True)
            st.caption(desc)
    draw_card(c1, "增长预期 (TLT/SHY Z)", tlt_shy_diff, rate_txt, rate_cls, "Z>0: 长债历史性跑赢短债 → 衰退/降息定价")
    draw_card(c2, "风险偏好 (HYG/IEF Z)", hyg_ief_diff, risk_txt, risk_cls, "Z>0: 信用债历史性领涨 → Risk-On")
    draw_card(c3, "通胀预期 (TIP/IEF Z)", tip_ief_diff, inf_txt, inf_cls, "Z>0: 通胀保值债领跑 → 通胀预期升温")
    draw_card(c4, "美元压力 (UUP/SHY Z)", usd_val, usd_txt, usd_cls, "Z>0: 美元历史性走强 → 流动性收紧")
    
    st.markdown("---")
    
    # api_clock_regime 由本地 3Y Z-Score 象限直接推导（客观真实，不依赖 API 或刷新频率）
    _clock_eng_map = {
        "软着陆": "Recovery (Soft Landing)",
        "再通胀": "Overheat (Reflation)",
        "滞胀":   "Stagflation",
        "衰退":   "Recession",
    }
    api_clock_regime = _clock_eng_map.get(_quad_a, "Recovery")

    st.markdown(f"### 🔭 宏观周期定位 (3Y 中期战略视角): <span style='color:#3498DB'>{api_clock_regime}</span>", unsafe_allow_html=True)

    # Phase 3: 当前坐标与象限裁决横幅
    st.markdown(f"""
    <div style='background-color:#1a1a1a; border-left:4px solid {_quadrant_color}; border-radius:6px; padding:12px 18px; margin-bottom:12px; display:flex; align-items:center; gap:32px;'>
        <div style='font-size:20px; font-weight:bold; color:{_quadrant_color};'>{_quadrant_name}</div>
        <div style='font-size:12px; color:#ccc;'>
            <b style='color:#F1C40F;'>★ 市场前瞻星 A</b>&nbsp;&nbsp;
            Growth=<b>{star_a_g_curr:+.2f}</b> | Infl=<b>{star_a_i_curr:+.2f}</b>
        </div>
        <div style='font-size:12px; color:#ccc;'>
            <b style='color:#3498DB;'>★ 政府滞后星 B</b>&nbsp;&nbsp;
            Growth=<b>{star_b_g_curr:+.2f}</b> | Infl=<b>{star_b_i_curr:+.2f}</b>
        </div>
        <div style='font-size:13px; color:#8E44AD; margin-left:auto; font-weight:bold; letter-spacing:0.3px;'>🔭 中期战略视角 (3Y · 750日)</div>
    </div>
    
    <div style='background-color:#1a1a1a; border:1px solid #E67E22; border-left:4px solid #E67E22; border-radius:6px; padding:14px 16px; margin-bottom:12px;'>
        <div style='font-size:15px; font-weight:bold; color:#E67E22; margin-bottom:10px;'>💡 交易员指南：为什么坐标轴是"预期边际差 (Z-Score)"而不是"绝对经济指标"？</div>
        <div style='font-size:13px; color:#ccc; line-height:1.75;'>
            <span style='color:#aaa;'>📈</span> <b style='color:#ddd;'>一阶（速度）= 资金流向：</b>消费/医疗等底层比值，反映此刻资金偏好<b>进攻</b>还是<b>防守</b>。<br>
            <span style='color:#aaa;'>📊</span> <b style='color:#ddd;'>二阶（加速度）= 预期差（Z-Score）：</b>将今天的资金流速与过去 1 年平均流速对比，衡量<b>变化的变化</b>。<br><br>
            <span style='color:#E67E22; font-weight:bold;'>🎯 实战意义：</span> 股市永远为未来定价。如果经济增速从 <b>120码</b> 降到了 <b>80码</b>，即使绝对经济仍在增长，<b style='color:#E74C3C;'>"加速度（Z-Score）已转负"</b>。系统敏锐捕捉"增速减弱"，并在官方确认经济变差<b>之前</b>，提前将其判定为【衰退/滞胀】倾向，触发调仓防守。
        </div>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("🔬 白盒溯源：双星底层因子完整披露 (点击展开)", expanded=False):
        _wb_a, _wb_b = st.columns(2)
        with _wb_a:
            st.markdown(f"""
            <div class="formula-box" style="height:100%;">
            <b style='color:#F1C40F; font-size:15px;'>🌟 市场前瞻星 (Market Leading Star)</b><br>
            <span style='color:#aaa; font-size:13px;'>领先官方数据 3-6 个月 | 当前象限：<b style='color:#F1C40F;'>{_quad_a}</b> | G={star_a_g_curr:+.2f} / I={star_a_i_curr:+.2f}</span>
            <hr style='border-color:#333; margin:10px 0;'>
            <b style='color:#3498DB;'>📈 经济增长轴 X (三引擎等权合成)</b><br><br>
            <b>① 铜金比</b> <code>CPER / GLD</code> — 20日均线，{z_window}日滚动预期边际差<br>
            <span style='color:#aaa; font-size:13px;'>全球宏观测温枪：铜跑赢黄金 = 工业需求扩张 / Risk-On</span><br><br>
            <b>② 工业实体</b> <code>XLI / XLU</code> — 20日均线，{z_window}日滚动预期边际差<br>
            <span style='color:#aaa; font-size:13px;'>美股内部复苏信号：工业 vs 防御公用事业</span><br><br>
            <b>③ 信用扩张</b> <code>{_credit_label_fl}</code> — 20日均线，{z_window}日滚动预期边际差（已反转）<br>
            <span style='color:#aaa; font-size:13px;'>高收益债利差收窄 = 融资畅通 / 信心充裕</span>
            <hr style='border-color:#333; margin:10px 0;'>
            <b style='color:#E67E22;'>🎈 通胀预期轴 Y (两引擎等权合成)</b><br><br>
            <b>① 隐含通胀预期</b> <code>{_t10yie_label_fl}</code> — 20日均线，{z_window}日滚动预期边际差<br>
            <span style='color:#aaa; font-size:13px;'>债市聪明钱对未来10年通胀的实时定价（名义利率 − TIPS实际利率）</span><br><br>
            <b>② 实物资产溢价</b> <code>DBC / IEF</code> — 20日均线，{z_window}日滚动预期边际差<br>
            <span style='color:#aaa; font-size:13px;'>广义大宗商品 vs 法币国债：当下通胀压力最直接市场证据</span>
            </div>
            """, unsafe_allow_html=True)
        with _wb_b:
            st.markdown(f"""
            <div class="formula-box" style="height:100%;">
            <b style='color:#3498DB; font-size:15px;'>🔵 政府滞后星 (Gov Lagging Star)</b><br>
            <span style='color:#aaa; font-size:13px;'>滞后真实经济 1-3 个月 | 当前象限：<b style='color:#3498DB;'>{_quad_b}</b> | G={star_b_g_curr:+.2f} / I={star_b_i_curr:+.2f}</span>
            <hr style='border-color:#333; margin:10px 0;'>
            <b style='color:#3498DB;'>📈 经济增长轴 X (三引擎等权合成)</b><br><br>
            <b>① 工业锚</b> <code>{_indpro_label_fl}</code> — 20日均线，{z_window}日滚动预期边际差<br>
            <span style='color:#aaa; font-size:13px;'>FRED 月度官方工业产出存量（YoY同比），反映实体制造业景气度。</span><br><br>
            <b>② 就业锚</b> <code>{_payems_label_fl}</code> — 20日均线，{z_window}日滚动预期边际差<br>
            <span style='color:#aaa; font-size:13px;'>FRED 月度非农就业人数（YoY同比），是美联储双重使命中就业端的核心锚点，滞后性强。</span><br><br>
            <b>③ 消费锚</b> <code>{_rsafs_label_fl}</code> — 20日均线，{z_window}日滚动预期边际差<br>
            <span style='color:#aaa; font-size:13px;'>FRED 月度零售销售总额（YoY同比），反映消费端实物需求，是 GDP 中最直接的终端需求信号。</span><br><br>
            <span style='color:#777; font-size:13px;'>注：FRED 月度数据逐日前向填充对齐时间轴。若所有官方数据均不可用，自动降级为 <code>XLY/XLP</code> ETF 代理。</span>
            <hr style='border-color:#333; margin:10px 0;'>
            <b style='color:#E67E22;'>🎈 通胀回溯轴 Y (双引擎等权合成)</b><br><br>
            <b>① CPI锚</b> <code>{_gov_cpi_label_fl}</code> — {z_window}日滚动预期边际差<br>
            <span style='color:#aaa; font-size:13px;'>FRED 核心CPI YoY（剔除食品与能源）：官方货币政策决策锚，属月度滞后统计。</span><br><br>
            <b>② PCE锚</b> <code>{_gov_pce_label_fl}</code> — {z_window}日滚动预期边际差<br>
            <span style='color:#aaa; font-size:13px;'>FRED 核心个人消费支出价格指数 YoY：美联储首选通胀参考指标，与 CPI 互为验证，覆盖更广泛的消费品篮子。</span><br><br>
            <span style='color:#777; font-size:13px;'>当 FRED 不可用时，自动降级为 <code>TIP/IEF</code> ETF 代理。</span>
            <hr style='border-color:#333; margin:10px 0;'>
            <b style='color:#aaa; font-size:13px;'>📐 合成方法</b><br>
            <span style='color:#aaa; font-size:13px;'>所有序列先取20日均线平滑（增长轴），再计算过去 <b style='color:#8E44AD;'>{z_window}日（中期战略视角 · 3Y）</b> 滚动预期边际差，最终等权平均为单轴坐标。防零除：sigma=0 时分母以 NaN 处理，不参与合成。</span>
            </div>
            """, unsafe_allow_html=True)

    fig_clock = go.Figure()
    limit = 3.0
    fig_clock.add_shape(type="rect",x0=0,y0=0,x1=limit,y1=limit,fillcolor="rgba(231,76,60,0.1)",line_width=0) 
    fig_clock.add_shape(type="rect",x0=0,y0=-limit,x1=limit,y1=0,fillcolor="rgba(46,204,113,0.1)",line_width=0) 
    fig_clock.add_shape(type="rect",x0=-limit,y0=-limit,x1=0,y1=0,fillcolor="rgba(52,152,219,0.1)",line_width=0) 
    fig_clock.add_shape(type="rect",x0=-limit,y0=0,x1=0,y1=limit,fillcolor="rgba(241,196,15,0.1)",line_width=0) 
    
    df_track = df_z.iloc[-60:]
    fig_clock.add_trace(go.Scatter(x=df_track['Growth'], y=df_track['Inflation'], mode='lines', name='市场星轨迹(60天)', line=dict(color='rgba(241,196,15,0.25)', width=1, dash='dot')))
    # 🔵 星星 B: 政府滞后星 — 蓝色五角星
    fig_clock.add_trace(go.Scatter(
        x=[star_b_g_curr], y=[star_b_i_curr], mode='markers', name='政府滞后星',
        marker=dict(color='#3498DB', size=18, symbol='star'),
        hovertemplate="<b>🔵 政府滞后星 (官方后视镜)</b><br>Growth Mom: %{x:.2f}<br>Inflation Mom: %{y:.2f}<br><i>⏰ 滞后真实经济 1-3 个月</i><extra></extra>"
    ))
    # 🌟 星星 A: 市场前瞻星 — 金色五角星
    fig_clock.add_trace(go.Scatter(
        x=[star_a_g_curr], y=[star_a_i_curr], mode='markers', name='市场前瞻星',
        marker=dict(color='#F1C40F', size=18, symbol='star'),
        hovertemplate="<b>🌟 市场前瞻星 (聪明钱)</b><br>Growth Mom: %{x:.2f}<br>Inflation Mom: %{y:.2f}<br><i>🚀 领先官方数据 3-6 个月</i><extra></extra>"
    ))
    # 张力虚线: 从政府星(B)指向市场星(A)
    fig_clock.add_shape(type='line', x0=star_b_g_curr, y0=star_b_i_curr, x1=star_a_g_curr, y1=star_a_i_curr, line=dict(color='rgba(200,200,200,0.45)', width=2, dash='dash'))
    fig_clock.add_annotation(x=star_a_g_curr, y=star_a_i_curr, ax=star_b_g_curr, ay=star_b_i_curr, axref='x', ayref='y', arrowhead=3, arrowsize=1.3, arrowwidth=2, arrowcolor='rgba(200,200,200,0.6)', showarrow=True, text="")

    fig_clock.update_layout(height=480, margin=dict(l=20,r=20,t=20,b=60), xaxis=dict(title="<-- 衰退 (Recession) | 软着陆 (Soft Landing) -->", range=[-limit, limit], zeroline=True, zerolinewidth=2), yaxis=dict(title="<-- 通缩 (Inflation -) | 通胀 (Inflation +) -->", range=[-limit, limit], zeroline=True, zerolinewidth=2), showlegend=True, legend=dict(orientation="h", y=-0.14, x=0.5, xanchor="center", font=dict(size=11)), plot_bgcolor='#222', paper_bgcolor='#222', font=dict(color='#ddd'))
    
    fig_clock.add_annotation(x=1.5, y=1.5, text="🔥 再通胀 (Reflation)", showarrow=False, font=dict(color="#E74C3C", size=14))
    fig_clock.add_annotation(x=1.5, y=-1.5, text="🚗 软着陆 (Soft Landing)", showarrow=False, font=dict(color="#2ECC71", size=14))
    fig_clock.add_annotation(x=-1.5, y=-1.5, text="❄️ 衰退 (Recession)", showarrow=False, font=dict(color="#3498DB", size=14))
    fig_clock.add_annotation(x=-1.5, y=1.5, text="🚨 滞胀 (Stagflation)", showarrow=False, font=dict(color="#F1C40F", size=14))
    _col_clock, _col_commentary = st.columns([3, 2])
    with _col_clock:
        st.plotly_chart(fig_clock, use_container_width=True)

    # ── Phase 3: 动态旁白解读引擎 (Dynamic Commentary Engine) ──────────────
    def _get_quad(g, i):
        if abs(g) < 0.5 and abs(i) < 0.5: return "软着陆"
        elif g > 0 and i <= 0: return "软着陆"
        elif g > 0 and i > 0: return "再通胀"
        elif g <= 0 and i > 0: return "滞胀"
        else: return "衰退"

    _QUAD_ASSETS = {
        "软着陆": "科技 (XLK / SMH / IGV) + 成长消费 (XRT / ARKK)",
        "再通胀": "能源 (XLE / XOP) + 工业 (XLI / PAVE) + 铜矿 (CPER / PICK)",
        "滞胀": "黄金 (GLD / SLV) + 广义商品 (DBC) + 防御 (XLP / XLV)",
        "衰退": "长债 (TLT) + 黄金 (GLD) + 必选消费 (XLP) + 公用 (XLU)",
    }
    _DIAGONALS = {("再通胀", "衰退"), ("衰退", "再通胀"), ("软着陆", "滞胀"), ("滞胀", "软着陆")}

    dynamic_recommendations = {
        "Recovery":    "全面进攻 (Risk-On)：宏观基本面加速复苏。建议放大 C 组（时代之王/科技成长）与 B 组敞口，享受主升浪。",
        "Overheat":    "通胀交易 (Inflation Trade)：经济火热且物价飙升。防守型资产将遭抛售，建议超配 D 组强周期资产（能源 XLE/XOP、铜矿 CPER/PICK）及工业制造。",
        "Stagflation": "滞胀防御 (Defensive)：最恶劣的宏观环境（高通胀+低增长）。建议强行压降多头仓位，向 A 组（压舱石/黄金 GLD）转移，保留高现金水位。",
        "Recession":   "衰退避险 (Safe Haven)：需求坍塌。建议切入长端美债（TLT/IEF）、防御性公用事业（XLU），并严格执行 Page 2 的全域均线截断风控。",
    }
    _QUAD_TO_ENG = {"软着陆": "Recovery", "再通胀": "Overheat", "滞胀": "Stagflation", "衰退": "Recession"}

    _quad_a = _get_quad(star_a_g_curr, star_a_i_curr)
    _quad_b = _get_quad(star_b_g_curr, star_b_i_curr)
    _dist = ((star_a_g_curr - star_b_g_curr) ** 2 + (star_a_i_curr - star_b_i_curr) ** 2) ** 0.5
    _dynamic_rec = dynamic_recommendations.get(_QUAD_TO_ENG.get(_quad_a, "Recovery"), dynamic_recommendations["Recovery"])

    # ── 增长轴背离向量：Market_Growth_Mom - Gov_Growth_Mom ──────────────────
    _growth_divergence = star_a_g_curr - star_b_g_curr
    if _growth_divergence > 0.5:
        _growth_divergence_text = (
            f"<br><br><span style='color:#2ECC71; font-weight:bold;'>📈 上修预警：</span>"
            f"市场前瞻增长信号（Market Growth Mom={star_a_g_curr:+.2f}）远强于官方后视镜"
            f"（Gov Growth Mom={star_b_g_curr:+.2f}，差值={_growth_divergence:+.2f}）。"
            f"历史表明，官方滞后的经济指标（如就业/零售/GDP）将在未来几周内面临<b>上修</b>。"
        )
    elif _growth_divergence < -0.5:
        _growth_divergence_text = (
            f"<br><br><span style='color:#E74C3C; font-weight:bold;'>📉 下修预警：</span>"
            f"官方数据仍在强撑（Gov Growth Mom={star_b_g_curr:+.2f}），但市场前瞻真金白银"
            f"已开始计价衰退周期（Market Growth Mom={star_a_g_curr:+.2f}，差值={_growth_divergence:+.2f}）。"
            f"历史表明，就业、零售等官方数据将在未来被<b>大幅下修</b>。"
        )
    else:
        _growth_divergence_text = ""

    if _quad_a == _quad_b and _dist < 1.0:
        _scenario_color = "#27AE60"
        _scenario_title = "✅ 高度共识 (Macro Consensus)"
        _scenario_body = (
            f"当前市场定价与官方数据达成<b>高度共识</b>，两大体系均指向同一个宏观象限："
            f" <b style='color:#F1C40F;'>{_quad_a}</b>。"
            f"趋势确立、共识明确，可顺势重仓周期性资产，无需额外防守。"
            f"{_growth_divergence_text}<br><br>"
            f"<b>🎯 系统建议（永远跟随市场前瞻定位）：</b> {_dynamic_rec}"
        )
    elif (_quad_a, _quad_b) in _DIAGONALS:
        _scenario_color = "#E74C3C"
        _scenario_title = "🚨 极度背离 (Macro Divergence)"
        _scenario_body = (
            f"当前市场正在激进交易 <b style='color:#F1C40F;'>{_quad_a}</b>，"
            f"而官方数据仍被锚定在滞后的 <b style='color:#3498DB;'>{_quad_b}</b> 周期中。"
            f"两套体系出现<b>对角线级别的极度错位</b>，这是历史上最高级别的宏观背离信号。"
            f"{_growth_divergence_text}<br><br>"
            f"<b>🎯 系统建议（永远跟随市场前瞻定位）：</b> {_dynamic_rec}"
        )
    else:
        _scenario_color = "#F39C12"
        _scenario_title = "⚠️ 前瞻转向 (Leading Divergence)"
        _scenario_body = (
            f"官方统计（滞后市场 1-3 个月）仍停留在 <b style='color:#3498DB;'>{_quad_b}</b>，"
            f"但铜金比、HY 利差与债市聪明钱（领先官方 3-6 个月）已悄然转向，"
            f"提前为 <b style='color:#F1C40F;'>{_quad_a}</b> 定价。这是典型的周期拐点信号。"
            f"{_growth_divergence_text}<br><br>"
            f"<b>🎯 系统建议（永远跟随市场前瞻定位）：</b> {_dynamic_rec}"
        )

    with _col_commentary:
        st.markdown(f"""
        <div style='background-color:#1a1a1a; border-left:4px solid {_scenario_color}; border-radius:6px; padding:16px 20px; margin:12px 0 20px 0; height:calc(100% - 24px); box-sizing:border-box;'>
            <div style='font-size:16px; font-weight:bold; color:{_scenario_color}; margin-bottom:10px;'>
                🧠 首席宏观旁白 &nbsp;—&nbsp; {_scenario_title}
            </div>
            <div style='font-size:14px; color:#ddd; line-height:1.9;'>{_scenario_body}</div>
            <div style='font-size:13px; color:#888; margin-top:10px; border-top:1px solid #333; padding-top:8px;'>
                市场前瞻星 → <b style='color:#F1C40F;'>{_quad_a}</b> &nbsp;|&nbsp;
                政府滞后星 → <b style='color:#3498DB;'>{_quad_b}</b> &nbsp;|&nbsp;
                两星距离: <b>{_dist:.2f}</b> 动量单位
            </div>
        </div>
        """, unsafe_allow_html=True)

    def get_z_a_trajectory(df_data, df_fred, window):
        def _z(series):
            mu = series.rolling(window=window).mean()
            sigma = series.rolling(window=window).std()
            return (series - mu) / sigma.where(sigma > 0)
        z_copper_gold = _z((df_data['CPER'] / df_data['GLD'].replace(0, np.nan)).rolling(20).mean())
        z_industrial = _z((df_data['XLI'] / df_data['XLU'].replace(0, np.nan)).rolling(20).mean())
        if not df_fred.empty and 'HY_Spread' in df_fred.columns:
            _hy_raw = df_fred['HY_Spread'].reindex(df_data.index).ffill().rolling(20).mean()
            z_credit = _z(_hy_raw) * -1
        else:
            _hy_raw = (df_data['HYG'] / df_data['IEF'].replace(0, np.nan)).rolling(20).mean()
            z_credit = _z(_hy_raw)
        growth_z = pd.DataFrame({'Z_copper_gold': z_copper_gold, 'Z_industrial': z_industrial, 'Z_credit': z_credit}).mean(axis=1)
        if not df_fred.empty and 'T10YIE' in df_fred.columns:
            _t10yie_raw = df_fred['T10YIE'].reindex(df_data.index).ffill().rolling(20).mean()
            z_t10yie = _z(_t10yie_raw)
        else:
            _t10yie_raw = (df_data['TIP'] / df_data['IEF'].replace(0, np.nan)).rolling(20).mean()
            z_t10yie = _z(_t10yie_raw)
        z_commodity = _z((df_data['DBC'] / df_data['IEF'].replace(0, np.nan)).rolling(20).mean())
        inflation_z = pd.DataFrame({'Z_t10yie': z_t10yie, 'Z_commodity': z_commodity}).mean(axis=1)
        return pd.DataFrame({'经济预期边际差': growth_z, '通胀预期边际差': inflation_z}).dropna()

    def map_to_4_regime(g, i, driving_style=True):
        if abs(g) < 0.5 and abs(i) < 0.5: return "软着陆"
        elif g > 0 and i <= 0: return "软着陆"
        elif g > 0 and i > 0: return "再通胀"
        elif g <= 0 and i > 0: return "滞胀"
        else: return "衰退"

    def generate_history_table(df_traj, driving_style=True):
        try:
            df_monthly = df_traj.resample('ME').last().dropna()
        except Exception:
            df_monthly = df_traj.resample('M').last().dropna()
        df_monthly['平滑经济边际差'] = df_monthly['经济预期边际差'].ewm(alpha=0.5, adjust=False).mean()
        df_monthly['平滑通胀边际差'] = df_monthly['通胀预期边际差'].ewm(alpha=0.5, adjust=False).mean()
        df_monthly['原始剧本'] = df_monthly.apply(lambda row: map_to_4_regime(row['经济预期边际差'], row['通胀预期边际差'], driving_style), axis=1)
        df_monthly['现任剧本'] = df_monthly.apply(lambda row: map_to_4_regime(row['平滑经济边际差'], row['平滑通胀边际差'], driving_style), axis=1)
        df_monthly = df_monthly.tail(120).sort_index(ascending=False)
        df_monthly.index = df_monthly.index.strftime('%Y-%m')
        df_monthly = df_monthly[['现任剧本', '原始剧本', '经济预期边际差', '通胀预期边际差', '平滑经济边际差', '平滑通胀边际差']]
        for col in ['经济预期边际差', '通胀预期边际差', '平滑经济边际差', '平滑通胀边际差']:
            df_monthly[col] = df_monthly[col].astype(float).round(2)
        df_monthly.rename(columns={'现任剧本': '现任剧本(状态机)', '原始剧本': '原始最强剧本'}, inplace=True)
        df_monthly.index.name = '调仓日期'
        return df_monthly

    def style_regime_df(styler):
        def apply_color(val):
            color = ''
            if val == '软着陆': color = '#2ECC71'
            elif val == '再通胀': color = '#E74C3C'
            elif val == '滞胀': color = '#F1C40F'
            elif val == '衰退': color = '#3498DB'
            return f'color: {color}; font-weight: bold;'
        return styler.map(apply_color, subset=['原始最强剧本', '现任剧本(状态机)'])

    with st.spinner("⏳ 正在计算宏观历史轨迹..."):
        df_traj_3y = get_z_a_trajectory(df, df_fred_clock, 750)

    # ── 📈 宏观时钟验证图 · 相对强弱宏观剧本染色图 ──────────────────────────────────────────
    _REGIME_LINE_C = {"软着陆": "#2ECC71", "再通胀": "#E74C3C", "滞胀": "#F1C40F", "衰退": "#3498DB"}
    _REGIME_BG_C   = {"软着陆": "rgba(46,204,113,0.15)", "再通胀": "rgba(231,76,60,0.15)", "滞胀": "rgba(241,196,15,0.15)", "衰退": "rgba(52,152,219,0.15)"}
    _REGIME_EMO    = {"软着陆": "🚗", "再通胀": "🔥", "滞胀": "🚨", "衰退": "❄️"}

    # 四大剧本 24 条件历史裁决（全局复用：染色图 + 历史裁决表）
    def _build_horsemen_history(df_data, df_fred, window=750):
        def _z(s):
            mu = s.rolling(window=window).mean()
            sg = s.rolling(window=window).std()
            return (s - mu) / sg.where(sg > 0)
        _z_cg = _z((df_data['CPER'] / df_data['GLD'].replace(0, np.nan)).rolling(20).mean())
        _z_xi = _z((df_data['XLI']  / df_data['XLU'].replace(0, np.nan)).rolling(20).mean())
        if not df_fred.empty and 'HY_Spread' in df_fred.columns:
            _z_cr = _z(df_fred['HY_Spread'].reindex(df_data.index).ffill().rolling(20).mean()) * -1
        else:
            _z_cr = _z((df_data['HYG'] / df_data['IEF'].replace(0, np.nan)).rolling(20).mean())
        _g = pd.DataFrame({'a': _z_cg, 'b': _z_xi, 'c': _z_cr}).mean(axis=1)
        if not df_fred.empty and 'T10YIE' in df_fred.columns:
            _z_ti = _z(df_fred['T10YIE'].reindex(df_data.index).ffill().rolling(20).mean())
        else:
            _z_ti = _z((df_data['TIP'] / df_data['IEF'].replace(0, np.nan)).rolling(20).mean())
        _z_co = _z((df_data['DBC'] / df_data['IEF'].replace(0, np.nan)).rolling(20).mean())
        _i = pd.DataFrame({'a': _z_ti, 'b': _z_co}).mean(axis=1)
        _z_xlk_xle   = _z((df_data['XLK']  / df_data['XLE'].replace(0, np.nan)).rolling(20).mean())
        _z_xly_xlp   = _z((df_data['XLY']  / df_data['XLP'].replace(0, np.nan)).rolling(20).mean())
        _z_gld_spy   = _z((df_data['GLD']  / df_data['SPY'].replace(0, np.nan)).rolling(20).mean())
        _z_vlue_mtum = _z((df_data['VLUE'] / df_data['MTUM'].replace(0, np.nan)).rolling(20).mean())
        _z_tlt_shy   = _z((df_data['TLT']  / df_data['SHY'].replace(0, np.nan)).rolling(20).mean())
        _z_xlp_spy   = _z((df_data['XLP']  / df_data['SPY'].replace(0, np.nan)).rolling(20).mean())
        _z_ief_hyg   = _z((df_data['IEF']  / df_data['HYG'].replace(0, np.nan)).rolling(20).mean())
        def _quad_h(gv, iv):
            if abs(gv) < 0.5 and abs(iv) < 0.5: return "软着陆"
            elif gv > 0 and iv <= 0:  return "软着陆"
            elif gv > 0 and iv > 0:   return "再通胀"
            elif gv <= 0 and iv > 0:  return "滞胀"
            else:                     return "衰退"
        _ds = pd.DataFrame({
            'g': _g, 'i': _i, 'z_cr': _z_cr, 'z_xlk_xle': _z_xlk_xle, 'z_xly_xlp': _z_xly_xlp,
            'z_cg': _z_cg, 'z_ti': _z_ti, 'z_co': _z_co, 'z_gld_spy': _z_gld_spy,
            'z_vlue_mtum': _z_vlue_mtum, 'z_tlt_shy': _z_tlt_shy, 'z_xlp_spy': _z_xlp_spy,
            'z_ief_hyg': _z_ief_hyg,
        }).dropna()
        _ds['quad'] = _ds.apply(lambda r: _quad_h(r['g'], r['i']), axis=1)
        _ds['score_a'] = ((_ds['quad'] == "软着陆").astype(int) + (_ds['g'] > 0).astype(int) + ((_ds['i'] <= 0) | (_ds['i'].abs() < 0.5)).astype(int) + (_ds['z_xlk_xle'] > 0).astype(int) + (_ds['z_cr'] > 0).astype(int) + (_ds['z_xly_xlp'] > 0).astype(int))
        _ds['score_b'] = ((_ds['quad'] == "再通胀").astype(int) + (_ds['g'] > 0).astype(int) + (_ds['i'] > 0).astype(int) + (_ds['z_cg'] > 0).astype(int) + (_ds['z_ti'] > 0).astype(int) + (_ds['z_co'] > 0).astype(int))
        _ds['score_c'] = ((_ds['quad'] == "滞胀").astype(int) + (_ds['g'] <= 0).astype(int) + (_ds['i'] > 0).astype(int) + (_ds['z_gld_spy'] > 0).astype(int) + (_ds['z_vlue_mtum'] > 0).astype(int) + (_ds['z_xly_xlp'] < 0).astype(int))
        _ds['score_d'] = ((_ds['quad'] == "衰退").astype(int) + (_ds['g'] <= 0).astype(int) + (_ds['i'] <= 0).astype(int) + (_ds['z_tlt_shy'] > 0).astype(int) + (_ds['z_xlp_spy'] > 0).astype(int) + (_ds['z_ief_hyg'] > 0).astype(int))
        _ds['prob_a'] = (_ds['score_a'] / 6 * 100).round().astype(int)
        _ds['prob_b'] = (_ds['score_b'] / 6 * 100).round().astype(int)
        _ds['prob_c'] = (_ds['score_c'] / 6 * 100).round().astype(int)
        _ds['prob_d'] = (_ds['score_d'] / 6 * 100).round().astype(int)
        def _winner(r):
            p = {'软着陆': r['prob_a'], '再通胀': r['prob_b'], '滞胀': r['prob_c'], '衰退': r['prob_d']}
            return max(p, key=p.get)
        _ds['剧本裁决'] = _ds.apply(_winner, axis=1)
        try:
            _dm = _ds.resample('ME').last().dropna()
        except Exception:
            _dm = _ds.resample('M').last().dropna()
        _dm = _dm.tail(120).sort_index(ascending=False)
        _dm.index = _dm.index.strftime('%Y-%m')
        _dm.index.name = '月份'
        out = _dm[['剧本裁决', 'prob_a', 'prob_b', 'prob_c', 'prob_d']].copy()
        out.columns = ['剧本裁决', '软着陆%', '再通胀%', '滞胀%', '衰退%']
        return out, _ds['剧本裁决']

    def _style_horsemen_df(styler):
        def _color(val):
            cmap = {'软着陆': '#2ECC71', '再通胀': '#E74C3C', '滞胀': '#F1C40F', '衰退': '#3498DB'}
            return f'color: {cmap.get(val, "#888")}; font-weight: bold;' if val in cmap else ''
        return styler.map(_color, subset=['剧本裁决'])

    df_hist_horsemen, _horsemen_daily = _build_horsemen_history(df, df_fred_clock, window=z_window)

    _RATIO_OPTIONS = {
        "🔬 科技/能源比 (XLK/XLE)": ("XLK", "XLE", "XLK / XLE 比值"),
        "🌡️ 铜金比 (CPER/GLD)": ("CPER", "GLD", "CPER / GLD 比值"),
        "🛡️ 纯防御/纯进攻比 (XLP/XLY)": ("XLP", "XLY", "XLP / XLY 比值"),
    }
    _RATIO_COMMENTARY = {
        "🔬 科技/能源比 (XLK/XLE)": {
            "软着陆": "📈 科技领跑：金发姑娘环境中，无通胀的增长驱动资金涌入科技成长，能源被冷落。比值应持续走高。",
            "再通胀": "📉 能源接棒：通胀高烧驱动大宗周期，科技估值受利率压制溃败。比值应明显下降，是换仓到 XLE/XOP 的信号。",
            "滞胀": "⚠️ 双杀陷阱：科技跌估值，能源跌需求。能源通常相对更抗跌，比值在低位震荡。应两者均减仓，向黄金撤退。",
            "衰退": "❄️ 双双受压：增长坍塌压垮两者。科技盈利预期下修，能源需求萎靡。比值低位徘徊，正确选择是逃往长债与防御。",
        },
        "🌡️ 铜金比 (CPER/GLD)": {
            "软着陆": "📈 铜跑赢金：工业扩张、需求旺盛，铜作为经济温度计大涨，黄金避险溢价褪去。比值走高是全球经济共振的最强证明。",
            "再通胀": "🔥 铜金共振：工业需求强劲同时通胀升温，铜持续领涨，金也有支撑。比值高位震荡——顺周期资产的天堂。",
            "滞胀": "🚨 金反超铜：经济放缓压制铜需求，通胀高企却让黄金成为最佳避险资产。比值下降是黄金超配的最强入场信号。",
            "衰退": "❄️ 金大幅跑赢：需求坍塌压垮铜，恐慌情绪推升黄金。比值触底是宏观时钟最清晰的衰退认证章。",
        },
        "🛡️ 纯防御/纯进攻比 (XLP/XLY)": {
            "软着陆": "📉 进攻占优：消费者信心高涨，可选消费(XLY)大涨，必选消费(XLP)被冷落。比值下降，持有 XLY 正确。",
            "再通胀": "📊 初期进攻，后期防御切换：通胀初期 XLY 跑赢，随着利率高企侵蚀可支配收入，比值企稳回升——防御切换信号亮起。",
            "滞胀": "📈 防御全面占优：口袋缩水让消费者只买必需品，XLP 大幅跑赢。比值显著上升，是宏观环境恶化的直接写照。",
            "衰退": "🚨 防御彻底躺平：资金全速撤入必选消费避险，比值冲顶——这是资金对经济彻底绝望的终极信号。",
        },
    }

    st.markdown("##### 🔬 宏观时钟验证图 — 在四色剧本背景下，亲眼验证宏观物理定律")
    _selected_ratio = st.selectbox(
        "选择验证指标：",
        options=list(_RATIO_OPTIONS.keys()),
        index=0,
        key="regime_ratio_selector",
        help="这三条线在四种颜色背景下如物理定律般规律起伏，是宏观时钟有效性的终极视觉证明。"
    )
    _tick_a, _tick_b, _ratio_ylabel = _RATIO_OPTIONS[_selected_ratio]

    _ratio_series = (df[_tick_a] / df[_tick_b].replace(0, np.nan)).rolling(20).mean().astype(float).dropna()

    if _ratio_series.empty:
        st.warning(f"⚠️ 所选指标 {_tick_a}/{_tick_b} 数据不足，无法渲染比值图")
        st.stop()

    _reg_aligned_r = _horsemen_daily.reindex(_ratio_series.index).ffill().dropna()
    _traj_start_r = _horsemen_daily.index[0] if not _horsemen_daily.empty else _ratio_series.index[0]
    _ratio_3y = _ratio_series[_ratio_series.index >= _traj_start_r]
    _reg_3y_r  = _reg_aligned_r[_reg_aligned_r.index >= _traj_start_r]

    _shapes_ratio = []
    _traces_ratio = []
    _leg_seen_r   = set()
    _curr_rr      = None
    _seg_start_rr = None

    for _d, _reg in _reg_3y_r.items():
        if _reg != _curr_rr:
            if _curr_rr is not None and _seg_start_rr is not None:
                _shapes_ratio.append(dict(
                    type="rect", x0=_seg_start_rr, x1=_d,
                    y0=0, y1=1, yref="paper",
                    fillcolor=_REGIME_BG_C.get(_curr_rr, "rgba(128,128,128,0.1)"),
                    line_width=0, layer="below"
                ))
                _seg = _ratio_3y[(_ratio_3y.index >= _seg_start_rr) & (_ratio_3y.index < _d)]
                if not _seg.empty:
                    _traces_ratio.append(go.Scatter(
                        x=_seg.index, y=_seg.values, mode='lines',
                        line=dict(color=_REGIME_LINE_C.get(_curr_rr, '#888'), width=2),
                        name=f"{_REGIME_EMO.get(_curr_rr,'')} {_curr_rr}",
                        showlegend=(_curr_rr not in _leg_seen_r),
                        legendgroup=_curr_rr
                    ))
                    _leg_seen_r.add(_curr_rr)
            _curr_rr = _reg
            _seg_start_rr = _d

    if _curr_rr is not None and _seg_start_rr is not None and not _ratio_3y.empty:
        _shapes_ratio.append(dict(
            type="rect", x0=_seg_start_rr, x1=_ratio_3y.index[-1],
            y0=0, y1=1, yref="paper",
            fillcolor=_REGIME_BG_C.get(_curr_rr, "rgba(128,128,128,0.1)"),
            line_width=0, layer="below"
        ))
        _seg = _ratio_3y[_ratio_3y.index >= _seg_start_rr]
        if not _seg.empty:
            _traces_ratio.append(go.Scatter(
                x=_seg.index, y=_seg.values, mode='lines',
                line=dict(color=_REGIME_LINE_C.get(_curr_rr, '#888'), width=2),
                name=f"{_REGIME_EMO.get(_curr_rr,'')} {_curr_rr}",
                showlegend=(_curr_rr not in _leg_seen_r),
                legendgroup=_curr_rr
            ))

    _fig_ratio_regime = go.Figure()
    for _tr in _traces_ratio:
        _fig_ratio_regime.add_trace(_tr)
    _fig_ratio_regime.update_layout(
        height=320,
        shapes=_shapes_ratio,
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor='#1a1a1a', paper_bgcolor='#1a1a1a',
        font=dict(color='#ddd'),
        showlegend=True,
        legend=dict(orientation="h", y=1.16, x=0.5, xanchor="center", font=dict(size=12)),
        hovermode="x unified",
        xaxis=dict(showgrid=False),
        yaxis=dict(title=_ratio_ylabel, showgrid=True, gridcolor='rgba(255,255,255,0.06)'),
        title=dict(
            text=f"{_selected_ratio} · 四大剧本染色图 ({_traj_start_r.strftime('%Y')}-至今) &nbsp;|&nbsp; 当前裁决：{_REGIME_EMO.get(df_hist_horsemen['剧本裁决'].iloc[0],'') if not df_hist_horsemen.empty else ''} {df_hist_horsemen['剧本裁决'].iloc[0] if not df_hist_horsemen.empty else 'N/A'}",
            font=dict(size=14), x=0.01, xanchor='left'
        )
    )
    st.plotly_chart(_fig_ratio_regime, use_container_width=True)

    _horsemen_curr = df_hist_horsemen['剧本裁决'].iloc[0] if not df_hist_horsemen.empty else ""
    _ratio_comment = _RATIO_COMMENTARY.get(_selected_ratio, {}).get(_horsemen_curr, "")
    if _ratio_comment:
        _comment_color = _REGIME_LINE_C.get(_horsemen_curr, "#888")
        st.markdown(f"""
        <div style='background:#1a1a1a; border-left:4px solid {_comment_color}; border-radius:6px; padding:12px 16px; margin-bottom:4px;'>
            <div style='font-size:13px; color:#aaa; margin-bottom:5px;'>
                {_REGIME_EMO.get(_horsemen_curr, "")} 当前剧本 <b style='color:{_comment_color};'>{_horsemen_curr}</b> 下，{_selected_ratio} 的宏观含义：
            </div>
            <div style='font-size:14px; color:#ddd; line-height:1.75;'>{_ratio_comment}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    st.header("🔬 债市阶梯深度透视 (Bond Ladder)")
    # 3Y Z-Score：衡量当前债市走势相对于过去3年历史均值的偏差（与宏观时钟同一度量衡）
    z_bl_tlt_shy = tlt_shy_diff                  # 已在宏观底色中计算
    z_bl_ief_shy = _ratio_z_curr('IEF', 'SHY')   # 中端/短端 Z-Score
    z_bl_hyg_ief = hyg_ief_diff                   # 已在宏观底色中计算
    z_bl_lqd_ief = _ratio_z_curr('LQD', 'IEF')   # 投资级/国债 Z-Score

    if z_bl_tlt_shy > 0.3:
        curve_shape = "🟢 牛陡 (Bull Steepening)"
        curve_desc = "长债相对短债处于3年历史高位。市场正在强烈定价衰退与降息预期，资金涌入长端国债避险。"
    elif z_bl_tlt_shy < -0.3:
        curve_shape = "🔴 熊平 (Bear Flattening)"
        curve_desc = "短端相对强于长端（3年维度）。市场正在定价加息、紧缩或滞胀风险，流动性预期恶化。"
    else:
        curve_shape = "⚖️ 中性震荡 (Neutral)"
        curve_desc = "长短端相对强弱处于3年历史均值附近，市场对未来宏观路径尚无明确共识。"

    if z_bl_hyg_ief > 0.3:
        credit_desc = "信用债相对国债处于3年历史强位。信用利差收窄，资金无惧违约风险，处于历史性 Risk-On 状态。"
    elif z_bl_hyg_ief < -0.3:
        credit_desc = "国债相对信用债处于3年历史强位。信用利差走阔，资金担忧企业违约，处于历史性 Risk-Off 状态。"
    else:
        credit_desc = "信用利差在3年历史均值附近震荡，市场风险偏好处于中性温和状态。"

    c_b1, c_b2 = st.columns(2)
    with c_b1:
        st.info(f"📈 **利率形态：{curve_shape}**")
        rates_data = {"SHY (短端)": 0.0, "IEF (中端)": z_bl_ief_shy, "TLT (长端)": z_bl_tlt_shy}
        fig_r = px.bar(pd.DataFrame(list(rates_data.items()), columns=['期限', 'Z-Score']), x='Z-Score', y='期限', orientation='h', color='Z-Score', color_continuous_scale='RdYlGn', range_color=[-2, 2])
        fig_r.update_layout(height=200, margin=dict(l=0,r=0,t=0,b=0), plot_bgcolor='#1a1a1a', paper_bgcolor='#1a1a1a', font=dict(color='#ddd'))
        st.plotly_chart(fig_r, use_container_width=True)
        st.markdown(f"<div class='conclusion-box'><b>🧠 宏观结论：</b>{curve_desc}</div>", unsafe_allow_html=True)

    with c_b2:
        st.info(f"🦁 **信用风险偏好**")
        credit_data = {"IEF (国债)": 0.0, "LQD (投资级)": z_bl_lqd_ief, "HYG (垃圾债)": z_bl_hyg_ief}
        fig_c = px.bar(pd.DataFrame(list(credit_data.items()), columns=['资产', 'Z-Score']), x='Z-Score', y='资产', orientation='h', color='Z-Score', color_continuous_scale='RdYlGn', range_color=[-2, 2])
        fig_c.update_layout(height=200, margin=dict(l=0,r=0,t=0,b=0), plot_bgcolor='#1a1a1a', paper_bgcolor='#1a1a1a', font=dict(color='#ddd'))
        st.plotly_chart(fig_c, use_container_width=True)
        st.markdown(f"<div class='conclusion-box'><b>🧠 资金行为：</b>{credit_desc}</div>", unsafe_allow_html=True)

    st.markdown("---")

    st.header("2️⃣ 聪明钱因子 (Smart Money Factors)")
    # 3Y Z-Score of factor/SPY：衡量每个因子相对标普500在3年历史维度的超额强度
    off_f = {
        "动量": _ratio_z_curr('MTUM', 'SPY'),
        "小盘": _ratio_z_curr('IWM',  'SPY'),
        "高贝塔": _ratio_z_curr('SPHB', 'SPY'),
        "投机": _ratio_z_curr('ARKK', 'SPY'),
    }
    def_f = {
        "低波": _ratio_z_curr('USMV', 'SPY'),
        "质量": _ratio_z_curr('QUAL', 'SPY'),
        "价值": _ratio_z_curr('VLUE', 'SPY'),
        "红利": _ratio_z_curr('VIG',  'SPY'),
    }

    off_mean = sum(off_f.values()) / len(off_f)
    def_mean = sum(def_f.values()) / len(def_f)
    best_f = max({**off_f, **def_f}, key={**off_f, **def_f}.get)

    if off_mean > def_mean + 0.5:
        factor_desc = "⚔️ **进攻占优 (Risk-On):** 动量、高贝塔等进攻因子在3年历史维度全面跑赢大盘，资金正在历史性追逐高弹性资产。"
    elif def_mean > off_mean + 0.5:
        factor_desc = "🛡️ **防守占优 (Risk-Off):** 红利、低波等防御因子在3年历史维度持续超额，资金正在历史性向安全资产迁移。"
    else:
        factor_desc = "⚖️ **均衡博弈:** 进攻与防守因子在3年历史均值附近均衡分布，市场处于风格切换震荡期，缺乏单边主线。"

    c_f1, c_f2 = st.columns(2)
    with c_f1:
        fig_off = px.bar(pd.DataFrame(list(off_f.items()), columns=['F', 'V']), x='V', y='F', orientation='h', color='V', color_continuous_scale='RdYlGn', range_color=[-2, 2])
        fig_off.update_layout(height=200, plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd'), title="⚔️ 进攻组 相对SPY Z-Score")
        st.plotly_chart(fig_off, use_container_width=True)
    with c_f2:
        fig_def = px.bar(pd.DataFrame(list(def_f.items()), columns=['F', 'V']), x='V', y='F', orientation='h', color='V', color_continuous_scale='RdYlGn', range_color=[-2, 2])
        fig_def.update_layout(height=200, plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd'), title="🛡️ 防守组 相对SPY Z-Score")
        st.plotly_chart(fig_def, use_container_width=True)

    st.markdown(f"<div class='conclusion-box'><b>🧠 因子轮动结论：</b>{factor_desc} (当前3Y历史维度最强单一因子: <b>{best_f}</b>)</div>", unsafe_allow_html=True)

    # ─── 🎯 战术分组映射引擎 (Tactical Group Mapping) ──────────────────────
    _all_f_vals = {**off_f, **def_f}
    _sorted_f = sorted(_all_f_vals.items(), key=lambda x: x[1], reverse=True)
    _top3_f = [f[0] for f in _sorted_f[:3]]
    _spy_vs_iwm = _ratio_z_curr('SPY', 'IWM')   # 大盘 vs 小盘 3Y Z-Score

    # 各战术组因子匹配得分 (满分: C=5, D=6, A=5)
    _score_C = sum([
        2 if '动量'  in _top3_f else 0,
        1 if '投机'  in _top3_f else 0,
        1 if off_mean > def_mean + 0.5 else 0,   # 进攻风格占优
        1 if _spy_vs_iwm > 0 else 0,              # 大盘跑赢小盘
    ])
    _score_D = sum([
        2 if '价值'  in _top3_f else 0,
        2 if '小盘'  in _top3_f else 0,
        1 if '高贝塔' in _top3_f else 0,
        1 if _spy_vs_iwm < 0 else 0,              # 小盘跑赢大盘
        1 if off_f.get('高贝塔', 0) > 0 else 0,  # 高贝塔本身为正
    ])
    _score_A = sum([
        2 if '低波'  in _top3_f else 0,
        1 if '质量'  in _top3_f else 0,
        1 if '红利'  in _top3_f else 0,
        1 if def_mean > off_mean + 0.5 else 0,   # 防守风格占优
    ])

    _group_scores = {'C': _score_C, 'D': _score_D, 'A': _score_A}
    _winner_group = max(_group_scores, key=_group_scores.get)
    _winner_score = _group_scores[_winner_group]
    _top2_f_str = ' + '.join(_top3_f[:2])

    if _winner_score < 2:
        # 信号过弱 → 均衡核心配置 B组
        _map_color, _map_badge = '#95A5A6', '⚖️'
        _map_title = 'B 组 (均衡核心)'
        _map_body = ('当前因子信号混杂，进攻与防守均无明确共振主线。建议维持均衡核心配置，'
                     '持有优质宽基资产，等待因子方向明确后再加大方向性押注。')
        _map_etfs = 'SPY · QQQ · QUAL · VIG'
        _map_confidence = '低'
    elif _winner_group == 'C':
        _map_color, _map_badge = '#E74C3C', '👑'
        _map_title = 'C 组 (时代之王)'
        _map_body = (f'资金正向流动性极佳的头部资产抱团。<b>{_top2_f_str}</b> 因子领衔，'
                     f'大盘成长全面压制价值小盘。建议超配 <b>C 组（时代之王）</b>，'
                     f'享受科技、AI、半导体的趋势主升浪。')
        _map_etfs = 'XLK · SMH · IGV · AIQ · NVDA · MSFT'
        _map_confidence = '高' if _winner_score >= 4 else '中'
    elif _winner_group == 'D':
        _map_color, _map_badge = '#F39C12', '⛏️'
        _map_title = 'D 组 (预备队·强周期)'
        _map_body = (f'典型再通胀/价值轮动信号共振。<b>{_top2_f_str}</b> 因子霸榜，'
                     f'小盘与强周期承接主力资金。建议重点狙击 <b>D 组（预备队·强周期）</b>，'
                     f'关注能源、基础材料与区域银行的爆发行情。')
        _map_etfs = 'XLE · XOP · KRE · CPER · PICK · URA'
        _map_confidence = '高' if _winner_score >= 4 else '中'
    else:   # A
        _map_color, _map_badge = '#3498DB', '🛡️'
        _map_title = 'A 组 (压舱石·防御)'
        _map_body = (f'避险情绪升温，资金躲入防空洞。<b>{_top2_f_str}</b> 因子主导，'
                     f'防御风格全面压制进攻。建议收缩进攻敞口，向 <b>A 组（压舱石）</b>转移——'
                     f'公用事业、优质红利与黄金提供安全边际。')
        _map_etfs = 'XLU · XLP · VIG · GLD · USMV · QUAL'
        _map_confidence = '高' if _winner_score >= 4 else '中'

    _confidence_color = {'高': '#2ECC71', '中': '#F39C12', '低': '#95A5A6'}[_map_confidence]
    _score_bar = ''.join(['█' if i < _winner_score else '░' for i in range(6)])

    st.markdown(f"""
    <div style='background:{_map_color}18; border:1px solid {_map_color}50; border-left:5px solid {_map_color};
                border-radius:8px; padding:18px 22px; margin-top:14px;'>
        <div style='display:flex; align-items:center; gap:14px; margin-bottom:10px;'>
            <div style='font-size:26px; line-height:1;'>{_map_badge}</div>
            <div>
                <div style='font-size:16px; font-weight:bold; color:{_map_color};'>
                    🎯 战术分组映射 &nbsp;→&nbsp; {_map_title}
                </div>
                <div style='font-size:13px; color:#aaa; margin-top:3px;'>
                    信号强度：<span style='color:{_confidence_color}; font-weight:bold;'>{_map_confidence}</span>
                    &nbsp;<span style='color:{_confidence_color}; font-family:monospace; letter-spacing:1px;'>[{_score_bar}]</span>
                    &nbsp;·&nbsp; 触发因子 Top-3：<b style='color:#F1C40F;'>{" · ".join(_top3_f)}</b>
                    &nbsp;·&nbsp; 进攻均值 <b>{off_mean:+.2f}σ</b> | 防守均值 <b>{def_mean:+.2f}σ</b>
                </div>
            </div>
        </div>
        <div style='font-size:14px; color:#ddd; line-height:1.9;'>{_map_body}</div>
        <div style='margin-top:10px; padding-top:8px; border-top:1px solid {_map_color}30; font-size:13px; color:#888;'>
            🗂️ 参考标的：<span style='color:#ccc;'>{_map_etfs}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    st.header("3️⃣ 四大剧本推演 (The Four Horsemen)")

    def check(condition, desc_pass, desc_fail):
        if condition: return f"<div class='ev-item'><span class='ev-pass'>✅</span> <span>{desc_pass}</span></div>"
        else: return f"<div class='ev-item'><span class='ev-fail'>⚪</span> <span>{desc_fail}</span></div>"

    # =======================================================
    # 🧠 四大剧本证据链：全部升级为 3Y Z-Score（与宏观时钟同一时间维度）
    # =======================================================

    def _4h_ratio_z(a_col, b_col):
        """3Y 滚动 Z-Score of ratio a/b, 20日均线预平滑。"""
        if a_col not in df.columns or b_col not in df.columns:
            return 0.0
        z_s = _zscore((df[a_col] / df[b_col].replace(0, np.nan)).rolling(20).mean()).dropna()
        return float(z_s.iloc[-1]) if not z_s.empty else 0.0

    # 直接复用宏观时钟已计算的 Z-Score（避免重复计算）
    z_4h_cper_gld  = float(z_copper_gold.dropna().iloc[-1]) if not z_copper_gold.dropna().empty else 0.0
    z_4h_tip_ief   = float(z_t10yie.dropna().iloc[-1])      if not z_t10yie.dropna().empty      else 0.0
    z_4h_dbc_ief   = float(z_commodity.dropna().iloc[-1])   if not z_commodity.dropna().empty   else 0.0
    z_4h_hyg_ief   = float(z_credit.dropna().iloc[-1])      if not z_credit.dropna().empty      else 0.0
    # 额外计算四大剧本专属比值
    z_4h_xlk_xle   = _4h_ratio_z('XLK',  'XLE')    # 科技/能源: 成长 vs 通胀溢价
    z_4h_xly_xlp   = _4h_ratio_z('XLY',  'XLP')    # 可选/必选消费: 进攻 vs 防御
    z_4h_gld_spy   = _4h_ratio_z('GLD',  'SPY')    # 黄金/美股: 避险溢价
    z_4h_tlt_shy   = _4h_ratio_z('TLT',  'SHY')    # 长债/短债: 衰退买盘
    z_4h_xlp_spy   = _4h_ratio_z('XLP',  'SPY')    # 防御/大盘: 防御超配
    z_4h_vlue_mtum = _4h_ratio_z('VLUE', 'MTUM')   # 价值/动量: 成长预期下修
    z_4h_ief_hyg   = _4h_ratio_z('IEF',  'HYG')    # 国债/垃圾债: 利差走阔(衰退信号)

    # ── 证据条件布尔列表（双用：驱动概率 + 渲染勾选）────────────────────
    _cond_a = [
        "Recovery" in api_clock_regime or "Soft" in api_clock_regime,
        curr_clock_g > 0,
        curr_clock_i <= 0 or abs(curr_clock_i) < 0.5,
        z_4h_xlk_xle > 0,
        z_4h_hyg_ief > 0,
        z_4h_xly_xlp > 0,
    ]
    _cond_b = [
        "Overheat" in api_clock_regime,
        curr_clock_g > 0,
        curr_clock_i > 0,
        z_4h_cper_gld > 0,
        z_4h_tip_ief > 0,
        z_4h_dbc_ief > 0,
    ]
    _cond_c = [
        "Stagflation" in api_clock_regime,
        curr_clock_g <= 0,
        curr_clock_i > 0,
        z_4h_gld_spy > 0,
        z_4h_vlue_mtum > 0,
        z_4h_xly_xlp < 0,
    ]
    _cond_d = [
        "Recession" in api_clock_regime,
        curr_clock_g <= 0,
        curr_clock_i <= 0,
        z_4h_tlt_shy > 0,
        z_4h_xlp_spy > 0,
        z_4h_ief_hyg > 0,
    ]

    # 概率 = 通过的证据条数 / 总条数（打几个钩 = 显示几成概率）
    prob_a = round(sum(_cond_a) / len(_cond_a) * 100)
    prob_b = round(sum(_cond_b) / len(_cond_b) * 100)
    prob_c = round(sum(_cond_c) / len(_cond_c) * 100)
    prob_d = round(sum(_cond_d) / len(_cond_d) * 100)

    # 全局宏观剧本写入 session_state — 以四大剧本历史裁决表为唯一数据源 (SSOT)
    # df_hist_horsemen 已在本页宏观时钟染色图前统一计算，月度频率，最新行 = iloc[0]
    _cn_to_en = {"软着陆": "Soft", "再通胀": "Hot", "滞胀": "Stag", "衰退": "Rec"}
    if df_hist_horsemen.empty:
        _horsemen_en_winner = "Soft"
        _horsemen_probs = {"Soft": 1.0, "Hot": 0.0, "Stag": 0.0, "Rec": 0.0}
    else:
        _horsemen_en_winner = _cn_to_en.get(df_hist_horsemen['剧本裁决'].iloc[0], "Soft")
        _horsemen_probs = {
            "Soft": df_hist_horsemen['软着陆%'].iloc[0] / 100.0,
            "Hot":  df_hist_horsemen['再通胀%'].iloc[0] / 100.0,
            "Stag": df_hist_horsemen['滞胀%'].iloc[0] / 100.0,
            "Rec":  df_hist_horsemen['衰退%'].iloc[0] / 100.0,
        }
    # D 组剧本规则：第二高概率若 >60% 则用之，否则同 B/C（最高概率剧本）
    _sorted_for_d = sorted(_horsemen_probs.items(), key=lambda x: x[1], reverse=True)
    _d_raw_regime = (
        _sorted_for_d[1][0]
        if len(_sorted_for_d) >= 2 and _sorted_for_d[1][1] > 0.60
        else _horsemen_en_winner
    )
    # Page 4 读取: current_macro_regime / current_macro_regime_raw (宏观剧本设定 selectbox 默认值)
    st.session_state["current_macro_regime"]     = _horsemen_en_winner
    st.session_state["current_macro_regime_raw"] = _d_raw_regime
    # Page 6 读取: smoothed_regime_probs (驱动卫星池激活门控) / live_regime_label (现任剧本标签)
    st.session_state["smoothed_regime_probs"]    = _horsemen_probs
    st.session_state["live_regime_label"]        = _horsemen_en_winner
    # Page 6 回测引擎读取: horsemen_monthly_probs — 月度历史裁决表概率查找表
    # 格式: {"YYYY-MM": {"Soft": f, "Hot": f, "Stag": f, "Rec": f}}
    # 回测在每个历史月份用此表代替 calculate_macro_scores，确保两边信号源一致
    st.session_state["horsemen_monthly_probs"] = {
        month_str: {
            "Soft": float(row["软着陆%"]) / 100.0,
            "Hot":  float(row["再通胀%"]) / 100.0,
            "Stag": float(row["滞胀%"])   / 100.0,
            "Rec":  float(row["衰退%"])   / 100.0,
        }
        for month_str, row in df_hist_horsemen.iterrows()
    }

    # 持久化月度裁决（与上方「四大剧本历史裁决表」同一套月度 resample 结果），供 Page 4 历史榜并列展示
    _horsemen_verdict_file = os.path.join(os.path.dirname(__file__), "..", "data", "horsemen_monthly_verdict.json")
    try:
        _verdict_months = {}
        if not df_hist_horsemen.empty:
            for month_str, row in df_hist_horsemen.iterrows():
                _verdict_months[str(month_str)] = {
                    "verdict_cn": str(row["剧本裁决"]),
                    "verdict_en": _cn_to_en.get(row["剧本裁决"], "Soft"),
                    "Soft": float(row["软着陆%"]) / 100.0,
                    "Hot": float(row["再通胀%"]) / 100.0,
                    "Stag": float(row["滞胀%"]) / 100.0,
                    "Rec": float(row["衰退%"]) / 100.0,
                }
        _verdict_payload = {
            "source": "macro_page_four_horsemen_monthly",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "months": _verdict_months,
        }
        os.makedirs(os.path.dirname(_horsemen_verdict_file), exist_ok=True)
        with open(_horsemen_verdict_file, "w", encoding="utf-8") as _hvf:
            json.dump(_verdict_payload, _hvf, ensure_ascii=False, indent=2)
    except Exception:
        pass

    items_a = [
        check(_cond_a[0], "时钟指向复苏/软着陆", f"时钟不符 ({api_clock_regime})"),
        check(_cond_a[1], f"增长 Z={star_a_g_curr:+.2f}↑ (3Y视角: 经济动能扩张)", f"增长 Z={star_a_g_curr:+.2f}↓ (3Y视角: 增长动能收缩)"),
        check(_cond_a[2], f"通胀 Z={star_a_i_curr:+.2f} (3Y视角: 无通胀压力)", f"通胀 Z={star_a_i_curr:+.2f}↑ (3Y视角: 通胀压力残余)"),
        check(_cond_a[3], f"科技/能源比 Z={z_4h_xlk_xle:+.2f}↑ 成长主导，无通胀溢价", f"科技/能源比 Z={z_4h_xlk_xle:+.2f}↓ 能源抢镜，通胀交易回归"),
        check(_cond_a[4], f"信用/国债比 Z={z_4h_hyg_ief:+.2f}↑ Risk-On: 信用利差收窄", f"信用/国债比 Z={z_4h_hyg_ief:+.2f}↓ Risk-Off: 信用利差走阔"),
        check(_cond_a[5], f"可选/必选消费 Z={z_4h_xly_xlp:+.2f}↑ 消费信心足，进攻占优", f"可选/必选消费 Z={z_4h_xly_xlp:+.2f}↓ 防御转强，消费降级"),
    ]
    items_b = [
        check(_cond_b[0], "时钟指向再通胀/过热", f"时钟不符 ({api_clock_regime})"),
        check(_cond_b[1], f"增长 Z={star_a_g_curr:+.2f}↑ (3Y视角: 需求旺盛)", f"增长 Z={star_a_g_curr:+.2f}↓ (3Y视角: 需求不足)"),
        check(_cond_b[2], f"通胀 Z={star_a_i_curr:+.2f}↑ (3Y视角: 通胀超历史均值)", f"通胀 Z={star_a_i_curr:+.2f} (3Y视角: 通胀压力不足，成色不纯)"),
        check(_cond_b[3], f"铜/金比 Z={z_4h_cper_gld:+.2f}↑ 铜跑赢金，工业需求强劲", f"铜/金比 Z={z_4h_cper_gld:+.2f}↓ 金跑赢铜，工业需求转弱"),
        check(_cond_b[4], f"通胀预期 Z={z_4h_tip_ief:+.2f}↑ 债市定价通胀持续", f"通胀预期 Z={z_4h_tip_ief:+.2f}↓ 债市通胀定价消退"),
        check(_cond_b[5], f"大宗/债券 Z={z_4h_dbc_ief:+.2f}↑ 实物通胀压力仍在", f"大宗/债券 Z={z_4h_dbc_ief:+.2f}↓ 大宗承压，通胀交易退潮"),
    ]
    items_c = [
        check(_cond_c[0], "时钟指向滞胀", f"时钟不符 ({api_clock_regime})"),
        check(_cond_c[1], f"增长 Z={star_a_g_curr:+.2f}↓ (3Y视角: 经济动能衰竭)", f"增长 Z={star_a_g_curr:+.2f}↑ (3Y视角: 增长仍正，滞胀不纯)"),
        check(_cond_c[2], f"通胀 Z={star_a_i_curr:+.2f}↑ (3Y视角: 通胀高于历史均值)", f"通胀 Z={star_a_i_curr:+.2f} (3Y视角: 通胀压力不足)"),
        check(_cond_c[3], f"黄金/美股 Z={z_4h_gld_spy:+.2f}↑ 避险溢价涌现，黄金超额表现", f"黄金/美股 Z={z_4h_gld_spy:+.2f}↓ 美股仍强，黄金避险需求低"),
        check(_cond_c[4], f"价值/动量 Z={z_4h_vlue_mtum:+.2f}↑ 成长预期下修，价值防御抗跌", f"价值/动量 Z={z_4h_vlue_mtum:+.2f}↓ 成长动量仍强，滞胀特征不纯"),
        check(_cond_c[5], f"可选/必选消费 Z={z_4h_xly_xlp:+.2f}↓ 防御全面占优，消费降级确立", f"可选/必选消费 Z={z_4h_xly_xlp:+.2f}↑ 消费仍旺，防御切换不彻底"),
    ]
    items_d = [
        check(_cond_d[0], "时钟指向衰退", f"时钟不符 ({api_clock_regime})"),
        check(_cond_d[1], f"增长 Z={star_a_g_curr:+.2f}↓ (3Y视角: 需求坍塌)", f"增长 Z={star_a_g_curr:+.2f}↑ (3Y视角: 增长仍正，衰退深度存疑)"),
        check(_cond_d[2], f"通胀 Z={star_a_i_curr:+.2f} (3Y视角: 通缩压力出现)", f"通胀 Z={star_a_i_curr:+.2f}↑ (3Y视角: 通胀尚存，非纯衰退)"),
        check(_cond_d[3], f"长债/短债 Z={z_4h_tlt_shy:+.2f}↑ 牛陡: 衰退买盘汹涌", f"长债/短债 Z={z_4h_tlt_shy:+.2f}↓ 长债未受追捧，衰退交易未启动"),
        check(_cond_d[4], f"防御/大盘 Z={z_4h_xlp_spy:+.2f}↑ 必选消费超配，资金抱团防守", f"防御/大盘 Z={z_4h_xlp_spy:+.2f}↓ 大盘仍强，防御溢价低"),
        check(_cond_d[5], f"国债/垃圾债 Z={z_4h_ief_hyg:+.2f}↑ 信用利差走阔，企业违约风险升温", f"国债/垃圾债 Z={z_4h_ief_hyg:+.2f}↓ 信用尚好，衰退认证不足"),
    ]

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown(f"<div class='scenario-card'><b>🚗 软着陆 ({prob_a}%)</b><div class='evidence-list'>{''.join(items_a)}</div></div>", unsafe_allow_html=True)
    with c2: st.markdown(f"<div class='scenario-card'><b>🔥 再通胀 ({prob_b}%)</b><div class='evidence-list'>{''.join(items_b)}</div></div>", unsafe_allow_html=True)
    with c3: st.markdown(f"<div class='scenario-card'><b>🚨 滞胀 ({prob_c}%)</b><div class='evidence-list'>{''.join(items_c)}</div></div>", unsafe_allow_html=True)
    with c4: st.markdown(f"<div class='scenario-card'><b>❄️ 衰退 ({prob_d}%)</b><div class='evidence-list'>{''.join(items_d)}</div></div>", unsafe_allow_html=True)

    with st.expander("📋 四大剧本历史裁决表 (月度 · 24条件证据链)", expanded=False):
        st.caption("每月打钩得分 → 四个概率 → 最终裁决，即上方三大比例染色图背景色的决策来源。")
        st.dataframe(df_hist_horsemen.style.pipe(_style_horsemen_df), use_container_width=True, height=400)

    st.markdown("---")

    st.header("4️⃣ 分场景实战推荐 (Sector & Stock Picks)")
    st.caption("穿透板块表面：当板块强势时，自动为您展开其底层三大权重龙头股进行精确制导。")
    with st.spinner(f"📈 正在拉取成分股近期行情 ({len(CONSTITUENT_STOCKS)} 只个股 · 2年)..."):
        df_stocks = get_global_data(CONSTITUENT_STOCKS, years=2)
    with st.expander("🛡️ 白盒化声明：为什么 XLF, XLB, XLRE, XLY 等常见大宽基被系统剔除？"):
        st.markdown("""
        根据 **《Moltbot 白盒化设计第一基本法》**，本系统拒绝黑盒逻辑。以下传统宽基 ETF 因宏观特征不纯、弹性不足或逻辑冲突，已被剥夺“战术统帅”资格，由更锋利的特种部队替代：
        
        * 🚫 **XLF (大金融)**：内部逻辑打架（商业银行吃息差盼加息 vs 投行发债盼降息），走势温吞。**👉 战术替代：由对利率和经济复苏极度敏感的 `KRE (区域银行)` 填补。**
        * 🚫 **XLB (大材料)**：成分极其不纯（包含造纸箱、卖涂料等无通胀避险属性的伪周期股）。**👉 战术替代：由纯血通胀斗士 `CPER (铜)`、`PICK (矿业)`、`URA (铀矿)` 填补。**
        * 🚫 **XLRE (大地产)**：被居家办公(WFH)摧毁的商业地产(写字楼)严重拖累，降息也无法挽救其空置率。**👉 战术替代：由纯粹反映住宅供需短缺的 `ITB (房屋建筑)` 填补。**
        * 🚫 **XLY (可选消费)**：寡头垄断严重失真（AMZN 和 TSLA 两家占比近 40%），买 XLY 等同于赌财报，无法反映宏观消费全貌。**👉 战术替代：由等权重的 `XRT (零售)` 填补。**
        
        *💡 战术纪律：在宏观对冲的战场上，“平庸与模糊”就是最大的风险。宁可留白，绝不收录温吞水资产。如果未来以上宏观压制因素解除，主理人可随时将其重新编入字典。*
        """)
    def render_picks_with_stocks(targets, col):
        for t in targets:
            if t not in df.columns: continue
            try:
                ts = df[t].dropna()
                if len(ts) < 200: continue
                
                curr = float(ts.iloc[-1])
                ma20 = float(ts.rolling(20).mean().iloc[-1])
                ma60 = float(ts.rolling(60).mean().iloc[-1])
                
                roll_mean = float(ts.rolling(250).mean().iloc[-1])
                roll_std = float(ts.rolling(250).std().iloc[-1])
                z_score = (curr - roll_mean) / roll_std if roll_std != 0 else 0.0
                
                is_active = ma20 > ma60
                display_name = ASSET_NAMES.get(t, t)
                
                if is_active: 
                    col.markdown(f"✅ **{t} ({display_name})**<br><span style='font-size:12px;color:#aaa'>Mom: {z_score:.2f} | 强势</span>", unsafe_allow_html=True)
                else: 
                    col.markdown(f"<span style='color:#555'>🔒 {t} ({display_name})</span><br><span style='font-size:12px;color:#444'>Mom: {z_score:.2f} | 观察 (板块休整)</span>", unsafe_allow_html=True)
                
                if t in TOP_HOLDINGS:
                    for sub_t in TOP_HOLDINGS[t]:
                        if sub_t not in df_stocks.columns: continue
                        sub_ts = df_stocks[sub_t].dropna()
                        if len(sub_ts) < 200: continue
                        sub_curr = float(sub_ts.iloc[-1])
                        sub_rm = float(sub_ts.rolling(250).mean().iloc[-1])
                        sub_rs = float(sub_ts.rolling(250).std().iloc[-1])
                        sub_z = (sub_curr - sub_rm) / sub_rs if sub_rs != 0 else 0.0
                        
                        sub_m20 = float(sub_ts.rolling(20).mean().iloc[-1])
                        sub_m60 = float(sub_ts.rolling(60).mean().iloc[-1])
                        sub_icon = "🔥" if sub_m20 > sub_m60 else "⏱️"
                        
                        opacity_style = "opacity: 1.0;" if is_active else "opacity: 0.4;"
                        col.markdown(f"<div class='sub-ticker' style='{opacity_style}'>{sub_icon} <b>{sub_t}</b> ({ASSET_NAMES.get(sub_t, sub_t)}) | Mom: {sub_z:.1f}</div>", unsafe_allow_html=True)
            except: continue

    col_pa, col_pb, col_pc, col_pd = st.columns(4)
    with col_pa:
        st.subheader("🚗 买入：软着陆")
        render_picks_with_stocks(TARGETS_A, col_pa)
    with col_pb:
        st.subheader("🔥 买入：再通胀")
        render_picks_with_stocks(TARGETS_B, col_pb)
    with col_pc:
        st.subheader("🚨 买入：滞胀")
        render_picks_with_stocks(TARGETS_C, col_pc)
    with col_pd:
        st.subheader("❄️ 买入：衰退")
        render_picks_with_stocks(TARGETS_D, col_pd)

    st.markdown("---")
    st.header("5️⃣ 市场分化证据链 (Market Differentiation)")
    st.caption("共振 (大家都一样) vs 分化 (只有少数人赢) — 结构性机会的早期预警")

    sector_disp_cols = [t for t in ['XLK', 'XLF', 'XLV', 'XLY', 'XLP', 'XLE', 'XLI', 'XLB', 'XLU', 'XLRE', 'XLC'] if t in df.columns]
    _spy_valid = 'SPY' in df.columns and df['SPY'].dropna().shape[0] > 0
    _rsp_valid = 'RSP' in df.columns and df['RSP'].dropna().shape[0] > 0
    if _spy_valid and _rsp_valid and len(sector_disp_cols) >= 5:
        df_disp = df[['SPY', 'RSP'] + sector_disp_cols].dropna(how='all').copy()
        spy_base = df_disp['SPY'].dropna().iloc[0]
        rsp_base = df_disp['RSP'].dropna().iloc[0]
        df_disp['SPY_Norm'] = (df_disp['SPY'] / spy_base - 1) * 100
        df_disp['RSP_Norm'] = (df_disp['RSP'] / rsp_base - 1) * 100
        df_disp['Dispersion'] = df_disp[sector_disp_cols].pct_change().std(axis=1) * 100
        df_disp['Dispersion_MA20'] = df_disp['Dispersion'].rolling(20).mean()

        c_d1, c_d2 = st.columns(2)
        with c_d1:
            st.markdown("**🛠️ 抱团指数：市值加权(红) vs 等权(蓝)**")
            fig_d1 = go.Figure()
            fig_d1.add_trace(go.Scatter(x=df_disp.index, y=df_disp['SPY_Norm'], name="SPY (市值) %", line=dict(color='#E74C3C', width=2)))
            fig_d1.add_trace(go.Scatter(x=df_disp.index, y=df_disp['RSP_Norm'], name="RSP (等权) %", line=dict(color='#3498DB', width=2), fill='tonexty'))
            fig_d1.update_layout(height=350, hovermode="x unified", legend=dict(orientation="h", y=1.1), plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd'))
            st.plotly_chart(fig_d1, use_container_width=True)
        with c_d2:
            st.markdown("**🌊 板块离散度 (Dispersion)**")
            fig_d2 = go.Figure()
            fig_d2.add_trace(go.Scatter(x=df_disp.index, y=df_disp['Dispersion_MA20'], name="离散度 (MA20)", line=dict(color='#8E44AD', width=2), fill='tozeroy'))
            fig_d2.add_hline(y=1.5, line_dash="dot", line_color="red", annotation_text="混乱")
            fig_d2.add_hline(y=0.5, line_dash="dot", line_color="green", annotation_text="一致")
            fig_d2.update_layout(height=350, hovermode="x unified", legend=dict(orientation="h", y=1.1), plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd'))
            st.plotly_chart(fig_d2, use_container_width=True)

    st.markdown("---")
    st.header("6️⃣ 全球流动性大项 (Liquidity Machine)")
    st.caption("数据来自美联储 FRED，首次加载约需 10-30 秒，加载后缓存 4 小时。")
    if st.button("📡 加载流动性数据 (FRED)", key="load_liquidity"):
        st.session_state["liquidity_loaded"] = True
    if st.session_state.get("liquidity_loaded"):
        df_liq = get_liquidity_data()
        if not df_liq.empty and 'Net_Liquidity' in df_liq.columns:
            tab_treemap, tab_waterfall, tab_corr = st.tabs(["🏰 市值时光机", "🏭 货币流水线", "📈 趋势叠加 (对决模式)"])

            df_weekly = df_liq.resample('W-FRI').last().iloc[-52:]
            latest_row_liq = df_liq.iloc[-1]

            with tab_treemap:
                ids = ["root","cat_source","cat_valve","cat_asset","m0","fed","m2","m1","m2_other","tga","rrp","spy","tlt","gld","btc","uso"]
                parents = ["","root","root","root","cat_source","cat_source","cat_source","m2","m2","cat_valve","cat_valve","cat_asset","cat_asset","cat_asset","cat_asset","cat_asset"]
                labels = ["全球资金池","Source","Valve","Asset","🌱 M0","🖨️ Fed","💰 M2","💧 M1","🏦 定存","👜 TGA","♻️ RRP","🇺🇸 SPY","📜 TLT","🥇 GLD","₿ BTC","🛢️ USO"]
                colors = ["#333","#2E86C1","#8E44AD","#D35400","#1ABC9C","#5DADE2","#2980B9","#3498DB","#AED6F1","#AF7AC5","#AF7AC5","#E59866","#E59866","#E59866","#E59866","#E59866"]
                LATEST_CAPS = {"M2": 22300, "SPY": 55000, "TLT": 52000, "GLD": 14000, "BTC-USD": 2500, "USO": 2000}
                frames = []
                steps = []
                for date in df_weekly.index:
                    date_str = date.strftime('%Y-%m-%d')
                    row = df_weekly.loc[date]
                    def get_val(col): return float(row.get(col, 0)) if not pd.isna(row.get(col)) else 0.0
                    def get_asset_size(col):
                        curr = get_val(col)
                        last = float(latest_row_liq.get(col, 1))
                        base = LATEST_CAPS.get(col, 100)
                        return base * (curr / last) if last != 0 else base
                    vals = {}
                    vals['m0'] = get_val('M0'); vals['m1'] = get_val('M1'); vals['m2'] = get_val('M2'); vals['fed'] = get_val('Fed_Assets')
                    vals['m2_other'] = max(0, vals['m2'] - vals['m1']); vals['m2'] = vals['m1'] + vals['m2_other']
                    vals['tga'] = abs(get_val('TGA')); vals['rrp'] = abs(get_val('RRP'))
                    vals['spy'] = get_asset_size('SPY'); vals['tlt'] = get_asset_size('TLT'); vals['gld'] = get_asset_size('GLD')
                    vals['btc'] = get_asset_size('BTC-USD'); vals['uso'] = get_asset_size('USO')
                    vals['cat_source'] = vals['m0'] + vals['fed'] + vals['m2']
                    vals['cat_valve'] = vals['tga'] + vals['rrp']
                    vals['cat_asset'] = vals['spy'] + vals['tlt'] + vals['gld'] + vals['btc'] + vals['uso']
                    vals['root'] = vals['cat_source'] + vals['cat_valve'] + vals['cat_asset']
                    final_values = [vals['root'],vals['cat_source'],vals['cat_valve'],vals['cat_asset'],vals['m0'],vals['fed'],vals['m2'],vals['m1'],vals['m2_other'],vals['tga'],vals['rrp'],vals['spy'],vals['tlt'],vals['gld'],vals['btc'],vals['uso']]
                    text_list = [f"${v/1000:.1f}T" if v > 1000 else f"${v:,.0f}B" for v in final_values]
                    frames.append(go.Frame(name=date_str, data=[go.Treemap(ids=ids, parents=parents, values=final_values, labels=labels, text=text_list, branchvalues="total")]))
                    steps.append(dict(method="animate", args=[[date_str], dict(mode="immediate", frame=dict(duration=300, redraw=True), transition=dict(duration=300))], label=date_str))
                if frames:
                    fig_tree = go.Figure(
                        data=[go.Treemap(ids=ids, parents=parents, labels=labels, values=frames[-1].data[0].values, text=frames[-1].data[0].text, textinfo="label+text", branchvalues="total", marker=dict(colors=colors), hovertemplate="<b>%{label}</b><br>%{text}<extra></extra>", pathbar=dict(visible=False))],
                        frames=frames
                    )
                    fig_tree.update_layout(height=600, margin=dict(t=0,l=0,r=0,b=0), sliders=[dict(active=len(steps)-1, currentvalue={"prefix":"📅 历史: "}, pad={"t":50}, steps=steps)], updatemenus=[dict(type="buttons", showactive=False, visible=False)])
                    st.plotly_chart(fig_tree, use_container_width=True)

            with tab_waterfall:
                available_dates = df_weekly.index.strftime('%Y-%m-%d').tolist()
                sankey_date_str = st.select_slider("选择时间点：", options=available_dates, value=available_dates[-1], key="sankey_slider_p1")
                curr_date = pd.to_datetime(sankey_date_str)
                idx = df_liq.index.get_indexer([curr_date], method='pad')[0]
                row = df_liq.iloc[idx]
                fed_assets = float(row.get('Fed_Assets', 0)); tga = float(row.get('TGA', 0)); rrp = float(row.get('RRP', 0))
                m0 = float(row.get('M0', 0)); currency = float(row.get('Currency', 0)); reserves = m0 - currency
                m1 = float(row.get('M1', 0)); m2 = float(row.get('M2', 0))
                fiscal_injection = float(row.get('Fiscal_Injection', 0)); bank_credit = m2 - currency - max(0, fiscal_injection)
                spy_price = float(row.get('SPY', 0)); latest_spy_liq = float(latest_row_liq.get('SPY', 1))
                asset_pool_base = 100000; asset_pool_curr = asset_pool_base * (spy_price / latest_spy_liq) if latest_spy_liq else asset_pool_base
                valuation_leverage = asset_pool_curr - m2 * 0.5
                label_list = [f"🏛️ 央行 (Fed)<br>${fed_assets/1000:.1f}T", f"🦅 财政部 (Fiscal)<br>赤字注入 ${fiscal_injection/1000:.1f}T/yr", f"🔒 损耗 (TGA/RRP)<br>${(tga+rrp)/1000:.1f}T", f"🌱 基础货币 (M0)<br>${m0/1000:.1f}T", f"💵 现金<br>${currency/1000:.1f}T", f"🏦 准备金<br>${reserves/1000:.1f}T", f"⚡ 银行信贷创造<br>+${bank_credit/1000:.1f}T", f"🌊 广义货币 (M2)<br>${m2/1000:.1f}T", f"📈 市场情绪溢价<br>+${valuation_leverage/1000:.1f}T", f"🏙️ 资产终局<br>${asset_pool_curr/1000:.1f}T"]
                node_x = [0.001, 0.4, 0.2, 0.2, 0.4, 0.4, 0.4, 0.7, 0.7, 0.999]
                node_y = [0.5, 0.1, 0.9, 0.4, 0.3, 0.6, 0.9, 0.5, 0.1, 0.5]
                color_list = ["#F1C40F","#E74C3C","#8E44AD","#2ECC71","#1ABC9C","#95A5A6","#BDC3C7","#2E86C1","#BDC3C7","#E74C3C"]
                fig_sankey = go.Figure(data=[go.Sankey(
                    arrangement="snap",
                    node=dict(pad=10, thickness=20, line=dict(color="black", width=0.5), label=label_list, color=color_list, x=node_x, y=node_y),
                    link=dict(source=[0,0,3,3,4,6,1,7,7,8], target=[2,3,4,5,7,7,7,9,9,9], value=[tga+rrp, m0, currency, reserves, currency, bank_credit, max(0, fiscal_injection), m2*0.5, m2*0.5, valuation_leverage], label=["损耗","M0","现金","准备金","现金","信贷扩张","赤字支出","实体经济","金融分流","估值放大"], color=["#D7BDE2","#ABEBC6","#A2D9CE","#D5DBDB","#A2D9CE","#D5DBDB","#F5B7B1","#AED6F1","#AED6F1","#E6B0AA"])
                )])
                fig_sankey.update_layout(height=650, font=dict(size=14))
                st.plotly_chart(fig_sankey, use_container_width=True)

            with tab_corr:
                st.markdown('##### 📈 寻找"鳄鱼嘴"：资金与资产的背离')
                col_ctrl1, col_ctrl2 = st.columns([1, 3])
                with col_ctrl1:
                    lookback_days = st.selectbox("📅 观测周期", [365, 730, 1095, 1825, 3650], index=3, format_func=lambda x: f"过去 {x//365} 年", key="liq_lookback")
                    chart_mode = st.radio("👀 观测模式", ["双轴叠加 (看背离)", "央行 vs 财政 (看对决)", "归一化跑分 (看强弱)"], index=1, key="liq_mode")
                df_chart = df_liq.iloc[-lookback_days:].copy()
                fig_trend = make_subplots(specs=[[{"secondary_y": True}]])
                if chart_mode == "双轴叠加 (看背离)":
                    fig_trend.add_trace(go.Scatter(x=df_chart.index, y=df_chart['Net_Liquidity'], name="💧 净流动性 (左轴)", fill='tozeroy', line=dict(color='rgba(46, 204, 113, 0.5)', width=0)), secondary_y=False)
                    fig_trend.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SPY'], name="🇺🇸 美股 SPY (右轴)", line=dict(color='#E74C3C', width=2)), secondary_y=True)
                    fig_trend.update_yaxes(title_text="净流动性 ($B)", secondary_y=False)
                elif chart_mode == "央行 vs 财政 (看对决)":
                    fig_trend.add_trace(go.Scatter(x=df_chart.index, y=df_chart['Fed_Assets'], name="🏛️ 美联储资产 (央行)", line=dict(color='#F1C40F', width=3)), secondary_y=False)
                    fig_trend.add_trace(go.Scatter(x=df_chart.index, y=df_chart['Total_Debt'], name="🦅 美国国债总额 (财政)", line=dict(color='#E74C3C', width=3, dash='dash')), secondary_y=True)
                    fig_trend.update_yaxes(title_text="美联储资产 (缩表) 📉", secondary_y=False)
                    fig_trend.update_yaxes(title_text="美国国债总额 (扩表) 📈", secondary_y=True)
                else:
                    def normalize(series): return (series / series.dropna().iloc[0] - 1) * 100
                    fig_trend.add_trace(go.Scatter(x=df_chart.index, y=normalize(df_chart['Net_Liquidity']), name="💧 净流动性 %", line=dict(color='#2ECC71', width=3)))
                    fig_trend.add_trace(go.Scatter(x=df_chart.index, y=normalize(df_chart['Total_Debt']), name="🦅 国债总额 %", line=dict(color='#E74C3C', width=3, dash='dash')))
                    fig_trend.add_trace(go.Scatter(x=df_chart.index, y=normalize(df_chart['SPY']), name="🇺🇸 美股 %", line=dict(color='#3498DB', width=2)))
                    fig_trend.update_yaxes(title_text="累计涨跌幅 (%)")
                fig_trend.update_layout(height=500, hovermode="x unified", legend=dict(orientation="h", y=1.1, x=0.5, xanchor="center"), margin=dict(t=0,l=10,r=10,b=10))
                st.plotly_chart(fig_trend, use_container_width=True)
                with col_ctrl2:
                    if chart_mode == "央行 vs 财政 (看对决)":
                        st.error("**🔥 宏观核心视角：** 红色线斜率 > 黄色线斜率 = 财政部的放水速度超过了美联储的抽水速度，这解释了为什么市场不缺钱。")
        else:
            st.info("⏳ 正在拉取美联储 FRED 流动性数据，首次加载约需 10-20 秒...")

else:
    st.info("⏳ 正在计算宏观时钟与全证据链数据 (Fetching Data)...")