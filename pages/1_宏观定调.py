import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime, timedelta
import pandas_datareader.data as web
from api_client import fetch_core_data, get_global_data, fetch_macro_scores

# 1. 动态向云端 API 请求核心机密字典
core_data = fetch_core_data()
TIC_MAP = core_data.get("TIC_MAP", {})
REGIME_MAP = core_data.get("REGIME_MAP", {})
MACRO_TAGS_MAP = core_data.get("MACRO_TAGS_MAP", {})
USER_GROUPS_DEF = core_data.get("USER_GROUPS_DEF", {})

ALL_TICKERS = list(TIC_MAP.keys())
# --- 架构师注释: 宏观定调中心 v13.37 (终极量化逻辑升级版) ---
# 1. 实装 SPY 5阶状态机（强多头/多头回调/上涨力竭/强空头/震荡）。
# 2. SSOT 对齐缓存，消除 Z-Score 漂移与缩进报错。

st.set_page_config(page_title="宏观定调中心", layout="wide", page_icon="🧭")

with st.sidebar:
    st.header("🛠️ 系统维护")
    if st.button("🔄 清理缓存并重新下载数据"):
        st.cache_data.clear()
        st.success("缓存已清除！正在重新拉取最新数据...")
        st.rerun()

# 读取上一次 rerun 写入的时钟尺度状态（首次为默认值战术之眼）
_tf_mode_state = st.session_state.get("clock_timeframe", "tactical")
if _tf_mode_state == "structural":
    z_window = 2500
    years_to_fetch = 12
    _tf_label = "战略之眼"
    _tf_horizon = "基准10年 · 展望1-2年"
    _tf_badge_color = "#8E44AD"
else:
    z_window = 750
    years_to_fetch = 4
    _tf_label = "战术之眼"
    _tf_horizon = "基准3年 · 展望3-6个月"
    _tf_badge_color = "#E67E22"

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
ALL_TICKERS = list(set(CLOCK_ASSETS + FACTOR_ASSETS + TARGETS_A + TARGETS_B + TARGETS_C + TARGETS_D + CONSTITUENT_STOCKS))

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

MACRO_ASSETS_ALL = ["XLY", "XLP", "XLI", "XLU", "TIP", "IEF", "TLT", "SHY", "HYG", "UUP", "LQD", "MTUM", "IWM", "SPHB", "ARKK", "USMV", "QUAL", "VLUE", "VIG", "SPY", "CPER", "USO", "DBC", "KRE", "GLD", "XLK", "RSP", "XLF", "XLB", "XLRE"]
UNIVERSAL_TICKERS = list(set(ALL_TICKERS + MACRO_ASSETS_ALL + list(TIC_MAP.keys()) + list(REGIME_MAP.keys())))
UNIVERSAL_TICKERS.sort() 

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
    end_date = datetime.now()
    start_date = end_date - timedelta(days=3650 + 400)
    try:
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
    except Exception:
        return pd.DataFrame(columns=['Core_CPI_YoY', 'Core_PCE_YoY', 'HY_Spread', 'T10YIE', 'INDPRO_YoY', 'PAYEMS_YoY', 'RSAFS_YoY'])

with st.spinner(f"⏳ 正在拉取 [{_tf_label}] 数据管道 ({years_to_fetch}年历史)..."):
    df = get_global_data(UNIVERSAL_TICKERS, years=years_to_fetch)

with st.spinner("📡 正在接入 FRED 官方宏观数据管道 (INDPRO + PAYEMS + RSAFS + CPI + PCE + HY Spread)..."):
    df_fred_clock = get_clock_fred_data()
    _fred_ok = not df_fred_clock.empty
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
        """滚动 Z-Score (窗口={z_window}日)，防零除，保持原始 index。"""
        mu = series.rolling(window=window).mean()
        sigma = series.rolling(window=window).std()
        return (series - mu) / sigma.where(sigma > 0)

    # ── 横轴：经济增长复合 Z-Score (三引擎等权合成) ──────────────────
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

    # ── 纵轴：通胀复合 Z-Score (三引擎等权合成) ──────────────────────
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

    # Phase 3: 象限裁决 — 优先判断"软着陆"中心区（双轴 Z 均在 ±0.5 以内）
    if abs(curr_clock_g) < 0.5 and abs(curr_clock_i) < 0.5:
        _quadrant_name = "🌤️ 软着陆 (Soft Landing)"
        _quadrant_color = "#27AE60"
    elif curr_clock_g > 0 and curr_clock_i > 0:
        _quadrant_name = "🔥 过热 (Overheat)"
        _quadrant_color = "#E74C3C"
    elif curr_clock_g > 0 and curr_clock_i <= 0:
        _quadrant_name = "🟢 复苏 (Recovery)"
        _quadrant_color = "#2ECC71"
    elif curr_clock_g <= 0 and curr_clock_i > 0:
        _quadrant_name = "🌧️ 滞胀 (Stagflation)"
        _quadrant_color = "#F1C40F"
    else:
        _quadrant_name = "❄️ 衰退/再通胀 (Reflation)"
        _quadrant_color = "#3498DB"

    tlt_shy_diff = get_ret('TLT') - get_ret('SHY')
    hyg_ief_diff = get_ret('HYG') - get_ret('IEF')
    tip_ief_diff = get_ret('TIP') - get_ret('IEF')
    usd_val = get_ret('UUP')
    
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

    st.header("1️⃣ 宏观底色 (Macro Dashboard)")
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
            st.markdown(f"<div class='metric-value'>{val:.2f}%</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='{cls}'>{txt}</div>", unsafe_allow_html=True)
            st.caption(desc)
    draw_card(c1, "增长预期 (TLT-SHY)", tlt_shy_diff, rate_txt, rate_cls, "长债跑赢 = 衰退预期")
    draw_card(c2, "风险偏好 (HYG-IEF)", hyg_ief_diff, risk_txt, risk_cls, "利差收窄 = 追逐风险")
    draw_card(c3, "通胀预期 (TIP-IEF)", tip_ief_diff, inf_txt, inf_cls, "抗通胀债跑赢 = 预期抬头")
    draw_card(c4, "美元压力 (UUP)", usd_val, usd_txt, usd_cls, "美元上涨 = 流动性收紧")
    
    st.markdown("---")
    
    # 获取云端时钟状态以对齐显示
    raw_probs, api_clock_regime = fetch_macro_scores(df, curr_clock_g, curr_clock_i)

    _clock_hdr_col, _clock_toggle_col = st.columns([3, 2])
    with _clock_hdr_col:
        st.markdown(f"### 🕰️ 宏观周期定位: <span style='color:#3498DB'>{api_clock_regime}</span>", unsafe_allow_html=True)
    with _clock_toggle_col:
        _tf_options = ["⚔️ 战术之眼 (Tactical · 3Y)", "🔭 战略之眼 (Structural · 10Y)"]
        _tf_default_idx = 1 if _tf_mode_state == "structural" else 0
        _tf_picked = st.radio(
            "🕐 时钟尺度",
            _tf_options,
            index=_tf_default_idx,
            horizontal=True,
            key="clock_timeframe_widget",
            help="仅影响宏观时钟的 Z-Score 基准窗口，页面其余部分不变。"
        )
        # 写入 session_state，下次 rerun 顶部读取后重新计算
        _new_state = "structural" if "战略" in _tf_picked else "tactical"
        if _new_state != _tf_mode_state:
            st.session_state["clock_timeframe"] = _new_state
            st.rerun()
        # 时间尺度语义标注
        _tf_desc = {
            "tactical":   ("⚔️ **战术之眼**", "基准窗口 **3年 (750日)**", "展望未来 **3–6 个月**", "#E67E22"),
            "structural": ("🔭 **战略之眼**", "基准窗口 **10年 (2500日)**", "展望未来 **1–2 年**",   "#8E44AD"),
        }[_tf_mode_state]
        st.markdown(
            f"<div style='font-size:13px; color:#aaa; margin-top:2px; line-height:1.7;'>"
            f"<span style='color:{_tf_desc[3]}; font-weight:bold;'>{_tf_desc[0].replace('**','')}</span>"
            f"&nbsp;&nbsp;|&nbsp;&nbsp;{_tf_desc[1].replace('**','')}"
            f"&nbsp;&nbsp;→&nbsp;&nbsp;<span style='color:{_tf_desc[3]};'>{_tf_desc[2].replace('**','')}</span>"
            f"</div>",
            unsafe_allow_html=True
        )

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
        <div style='font-size:13px; color:{_tf_badge_color}; margin-left:auto; font-weight:bold; letter-spacing:0.3px;'>🕐 {_tf_label}</div>
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
        hovertemplate="<b>🔵 政府滞后星 (官方后视镜)</b><br>Growth Z: %{x:.2f}<br>Inflation Z: %{y:.2f}<br><i>⏰ 滞后真实经济 1-3 个月</i><extra></extra>"
    ))
    # 🌟 星星 A: 市场前瞻星 — 金色五角星
    fig_clock.add_trace(go.Scatter(
        x=[star_a_g_curr], y=[star_a_i_curr], mode='markers', name='市场前瞻星',
        marker=dict(color='#F1C40F', size=18, symbol='star'),
        hovertemplate="<b>🌟 市场前瞻星 (聪明钱)</b><br>Growth Z: %{x:.2f}<br>Inflation Z: %{y:.2f}<br><i>🚀 领先官方数据 3-6 个月</i><extra></extra>"
    ))
    # 张力虚线: 从政府星(B)指向市场星(A)
    fig_clock.add_shape(type='line', x0=star_b_g_curr, y0=star_b_i_curr, x1=star_a_g_curr, y1=star_a_i_curr, line=dict(color='rgba(200,200,200,0.45)', width=2, dash='dash'))
    fig_clock.add_annotation(x=star_a_g_curr, y=star_a_i_curr, ax=star_b_g_curr, ay=star_b_i_curr, axref='x', ayref='y', arrowhead=3, arrowsize=1.3, arrowwidth=2, arrowcolor='rgba(200,200,200,0.6)', showarrow=True, text="")

    fig_clock.update_layout(height=480, margin=dict(l=20,r=20,t=20,b=60), xaxis=dict(title="<-- 衰退 (Growth -) | 复苏 (Growth +) -->", range=[-limit, limit], zeroline=True, zerolinewidth=2), yaxis=dict(title="<-- 通缩 (Inflation -) | 通胀 (Inflation +) -->", range=[-limit, limit], zeroline=True, zerolinewidth=2), showlegend=True, legend=dict(orientation="h", y=-0.14, x=0.5, xanchor="center", font=dict(size=11)), plot_bgcolor='#222', paper_bgcolor='#222', font=dict(color='#ddd'))
    
    fig_clock.add_annotation(x=1.5, y=1.5, text="🔥 过热 (Overheat)", showarrow=False, font=dict(color="#E74C3C", size=14))
    fig_clock.add_annotation(x=1.5, y=-1.5, text="🟢 复苏 (Recovery)", showarrow=False, font=dict(color="#2ECC71", size=14))
    fig_clock.add_annotation(x=-1.5, y=-1.5, text="❄️ 衰退 (Reflation)", showarrow=False, font=dict(color="#3498DB", size=14))
    fig_clock.add_annotation(x=-1.5, y=1.5, text="🌧️ 滞胀 (Stagflation)", showarrow=False, font=dict(color="#F1C40F", size=14))
    _col_clock, _col_commentary = st.columns([3, 2])
    with _col_clock:
        st.plotly_chart(fig_clock, use_container_width=True)

    # ── Phase 3: 动态旁白解读引擎 (Dynamic Commentary Engine) ──────────────
    def _get_quad(g, i):
        if abs(g) < 0.5 and abs(i) < 0.5: return "软着陆"
        elif g > 0 and i > 0: return "过热"
        elif g > 0 and i <= 0: return "复苏"
        elif g <= 0 and i > 0: return "滞胀"
        else: return "衰退"

    _QUAD_ASSETS = {
        "软着陆": "科技 (XLK / SMH / IGV) + 成长消费 (XRT / ARKK)",
        "过热":   "能源 (XLE / XOP) + 工业 (XLI / PAVE) + 铜矿 (CPER / PICK)",
        "复苏":   "科技 (XLK) + 区域银行 (KRE) + 工业 (XLI) + 消费 (XRT)",
        "滞胀":   "黄金 (GLD / SLV) + 广义商品 (DBC) + 防御 (XLP / XLV)",
        "衰退":   "长债 (TLT) + 黄金 (GLD) + 必选消费 (XLP) + 公用 (XLU)",
    }
    _DIAGONALS = {("过热", "衰退"), ("衰退", "过热"), ("复苏", "滞胀"), ("滞胀", "复苏")}

    dynamic_recommendations = {
        "Recovery":    "全面进攻 (Risk-On)：宏观基本面加速复苏。建议放大 C 组（时代之王/科技成长）与 B 组敞口，享受主升浪。",
        "Overheat":    "通胀交易 (Inflation Trade)：经济火热且物价飙升。防守型资产将遭抛售，建议超配 D 组强周期资产（能源 XLE/XOP、铜矿 CPER/PICK）及工业制造。",
        "Stagflation": "滞胀防御 (Defensive)：最恶劣的宏观环境（高通胀+低增长）。建议强行压降多头仓位，向 A 组（压舱石/黄金 GLD）转移，保留高现金水位。",
        "Recession":   "衰退避险 (Safe Haven)：需求坍塌。建议切入长端美债（TLT/IEF）、防御性公用事业（XLU），并严格执行 Page 2 的全域均线截断风控。",
    }
    _QUAD_TO_ENG = {"复苏": "Recovery", "过热": "Overheat", "滞胀": "Stagflation", "衰退": "Recession", "软着陆": "Recovery"}

    _quad_a = _get_quad(star_a_g_curr, star_a_i_curr)
    _quad_b = _get_quad(star_b_g_curr, star_b_i_curr)
    _dist = ((star_a_g_curr - star_b_g_curr) ** 2 + (star_a_i_curr - star_b_i_curr) ** 2) ** 0.5
    _dynamic_rec = dynamic_recommendations.get(_QUAD_TO_ENG.get(_quad_a, "Recovery"), dynamic_recommendations["Recovery"])

    # ── 增长轴背离向量：Market_Z_Growth - Gov_Z_Growth ──────────────────
    _growth_divergence = star_a_g_curr - star_b_g_curr
    if _growth_divergence > 0.5:
        _growth_divergence_text = (
            f"<br><br><span style='color:#2ECC71; font-weight:bold;'>📈 上修预警：</span>"
            f"市场前瞻增长信号（Market Growth Z={star_a_g_curr:+.2f}）远强于官方后视镜"
            f"（Gov Growth Z={star_b_g_curr:+.2f}，差值={_growth_divergence:+.2f}）。"
            f"历史表明，官方滞后的经济指标（如就业/零售/GDP）将在未来几周内面临<b>上修</b>。"
        )
    elif _growth_divergence < -0.5:
        _growth_divergence_text = (
            f"<br><br><span style='color:#E74C3C; font-weight:bold;'>📉 下修预警：</span>"
            f"官方数据仍在强撑（Gov Growth Z={star_b_g_curr:+.2f}），但市场前瞻真金白银"
            f"已开始计价衰退（Market Growth Z={star_a_g_curr:+.2f}，差值={_growth_divergence:+.2f}）。"
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
                两星距离: <b>{_dist:.2f}</b> Z 单位
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Phase 4: 白盒化呈现 (White-Box Factor Transparency) ────────────────
    def _fl(label, series_id):
        """将 FRED 序列标签包装为可点击超链接；仅当 label 含 'FRED' 字样时生效。"""
        if series_id and 'FRED' in label:
            url = f"https://fred.stlouisfed.org/series/{series_id}"
            return f'<a href="{url}" target="_blank" style="color:#2ECC71; text-decoration:underline dotted;">{label}</a>'
        return label

    _indpro_label  = _fl(_indpro_label,  'INDPRO')
    _payems_label  = _fl(_payems_label,  'PAYEMS')
    _rsafs_label   = _fl(_rsafs_label,   'RSAFS')
    _gov_cpi_label = _fl(_gov_cpi_label, 'CPILFESL')
    _gov_pce_label = _fl(_gov_pce_label, 'PCEPILFE')
    _t10yie_label  = _fl(_t10yie_label,  'T10YIE')
    _credit_label  = _fl(_credit_label,  'BAMLH0A0HYM2')
    _cpi_label     = _fl(_cpi_label,     'CPILFESL')

    with st.expander("🔬 白盒溯源：双星底层因子完整披露 (点击展开)", expanded=False):
        _wb_a, _wb_b = st.columns(2)
        with _wb_a:
            st.markdown(f"""
            <div class="formula-box" style="height:100%;">
            <b style='color:#F1C40F; font-size:15px;'>🌟 市场前瞻星 (Market Leading Star)</b><br>
            <span style='color:#aaa; font-size:13px;'>领先官方数据 3-6 个月 | 当前象限：<b style='color:#F1C40F;'>{_quad_a}</b> | G={star_a_g_curr:+.2f} / I={star_a_i_curr:+.2f}</span>
            <hr style='border-color:#333; margin:10px 0;'>
            <b style='color:#3498DB;'>📈 经济增长轴 X (三引擎等权合成)</b><br><br>
            <b>① 铜金比</b> <code>CPER / GLD</code> — 20日均线，{z_window}日滚动 Z-Score<br>
            <span style='color:#aaa; font-size:13px;'>全球宏观测温枪：铜跑赢黄金 = 工业需求扩张 / Risk-On</span><br><br>
            <b>② 工业实体</b> <code>XLI / XLU</code> — 20日均线，{z_window}日滚动 Z-Score<br>
            <span style='color:#aaa; font-size:13px;'>美股内部复苏信号：工业 vs 防御公用事业</span><br><br>
            <b>③ 信用扩张</b> <code>{_credit_label}</code> — 20日均线，{z_window}日滚动 Z-Score（已反转）<br>
            <span style='color:#aaa; font-size:13px;'>高收益债利差收窄 = 融资畅通 / 信心充裕</span>
            <hr style='border-color:#333; margin:10px 0;'>
            <b style='color:#E67E22;'>🎈 通胀预期轴 Y (两引擎等权合成)</b><br><br>
            <b>① 隐含通胀预期</b> <code>{_t10yie_label}</code> — 20日均线，{z_window}日滚动 Z-Score<br>
            <span style='color:#aaa; font-size:13px;'>债市聪明钱对未来10年通胀的实时定价（名义利率 − TIPS实际利率）</span><br><br>
            <b>② 实物资产溢价</b> <code>DBC / IEF</code> — 20日均线，{z_window}日滚动 Z-Score<br>
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
            <b>① 工业锚</b> <code>{_indpro_label}</code> — 20日均线，{z_window}日滚动 Z-Score<br>
            <span style='color:#aaa; font-size:13px;'>FRED 月度官方工业产出存量（YoY同比），反映实体制造业景气度。</span><br><br>
            <b>② 就业锚</b> <code>{_payems_label}</code> — 20日均线，{z_window}日滚动 Z-Score<br>
            <span style='color:#aaa; font-size:13px;'>FRED 月度非农就业人数（YoY同比），是美联储双重使命中就业端的核心锚点，滞后性强。</span><br><br>
            <b>③ 消费锚</b> <code>{_rsafs_label}</code> — 20日均线，{z_window}日滚动 Z-Score<br>
            <span style='color:#aaa; font-size:13px;'>FRED 月度零售销售总额（YoY同比），反映消费端实物需求，是 GDP 中最直接的终端需求信号。</span><br><br>
            <span style='color:#777; font-size:13px;'>注：FRED 月度数据逐日前向填充对齐时间轴。若所有官方数据均不可用，自动降级为 <code>XLY/XLP</code> ETF 代理。</span>
            <hr style='border-color:#333; margin:10px 0;'>
            <b style='color:#E67E22;'>🎈 通胀回溯轴 Y (双引擎等权合成)</b><br><br>
            <b>① CPI锚</b> <code>{_gov_cpi_label}</code> — {z_window}日滚动 Z-Score<br>
            <span style='color:#aaa; font-size:13px;'>FRED 核心CPI YoY（剔除食品与能源）：官方货币政策决策锚，属月度滞后统计。</span><br><br>
            <b>② PCE锚</b> <code>{_gov_pce_label}</code> — {z_window}日滚动 Z-Score<br>
            <span style='color:#aaa; font-size:13px;'>FRED 核心个人消费支出价格指数 YoY：美联储首选通胀参考指标，与 CPI 互为验证，覆盖更广泛的消费品篮子。</span><br><br>
            <span style='color:#777; font-size:13px;'>当 FRED 不可用时，自动降级为 <code>TIP/IEF</code> ETF 代理。</span>
            <hr style='border-color:#333; margin:10px 0;'>
            <b style='color:#aaa; font-size:13px;'>📐 合成方法</b><br>
            <span style='color:#aaa; font-size:13px;'>所有序列先取20日均线平滑（增长轴），再计算过去 <b style='color:{_tf_badge_color};'>{z_window}日（当前：{_tf_label}）</b> 滚动 Z-Score，最终等权平均为单轴坐标。防零除：sigma=0 时分母以 NaN 处理，不参与合成。</span>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")

    st.header("🔬 债市阶梯深度透视 (Bond Ladder)")
    r_tlt, r_ief, r_shy = get_ret('TLT'), get_ret('IEF'), get_ret('SHY')
    
    if r_tlt > r_ief > r_shy: 
        curve_shape = "🟢 牛陡 (Bull Steepening)"
        curve_desc = "长债大幅跑赢短债。市场正在强烈定价衰退与未来的降息预期，资金涌入长端国债避险。"
    elif r_shy > r_ief > r_tlt: 
        curve_shape = "🔴 熊平 (Bear Flattening)"
        curve_desc = "短端承压大于长端。市场正在定价加息、紧缩或滞胀风险，流动性预期恶化。"
    else: 
        curve_shape = "⚖️ 混合震荡 (Mixed)"
        curve_desc = "长短端收益率变化不一致，市场对未来宏观路径存在分歧，缺乏单边趋势。"

    c_hyg, c_lqd, c_ief = get_ret('HYG'), get_ret('LQD'), get_ret('IEF')
    
    if c_hyg > c_lqd > c_ief:
        credit_desc = "垃圾债跑赢投资级和国债。信用利差收窄，资金无惧违约风险，处于极度 Risk-On 追逐收益的状态。"
    elif c_ief > c_lqd > c_hyg:
        credit_desc = "国债大幅跑赢信用债。信用利差走阔，资金担忧企业违约风险，处于极度 Risk-Off 的避险状态。"
    else:
        credit_desc = "信用利差保持平稳，市场风险偏好处于中性温和状态。"
    
    c_b1, c_b2 = st.columns(2)
    with c_b1:
        st.info(f"📈 **利率形态：{curve_shape}**")
        rates_data = {"SHY (短)": r_shy, "IEF (中)": r_ief, "TLT (长)": r_tlt}
        fig_r = px.bar(pd.DataFrame(list(rates_data.items()), columns=['期限', '涨跌']), x='涨跌', y='期限', orientation='h', color='涨跌', color_continuous_scale='RdYlGn')
        fig_r.update_layout(height=200, margin=dict(l=0,r=0,t=0,b=0), plot_bgcolor='#1a1a1a', paper_bgcolor='#1a1a1a', font=dict(color='#ddd'))
        st.plotly_chart(fig_r, use_container_width=True)
        st.markdown(f"<div class='conclusion-box'><b>🧠 宏观结论：</b>{curve_desc}</div>", unsafe_allow_html=True)

    with c_b2:
        st.info(f"🦁 **信用风险偏好**")
        credit_data = {"HYG (垃圾)": c_hyg, "LQD (投资)": c_lqd, "IEF (国债)": c_ief}
        fig_c = px.bar(pd.DataFrame(list(credit_data.items()), columns=['资产', '涨跌']), x='涨跌', y='资产', orientation='h', color='涨跌', color_continuous_scale='RdYlGn')
        fig_c.update_layout(height=200, margin=dict(l=0,r=0,t=0,b=0), plot_bgcolor='#1a1a1a', paper_bgcolor='#1a1a1a', font=dict(color='#ddd'))
        st.plotly_chart(fig_c, use_container_width=True)
        st.markdown(f"<div class='conclusion-box'><b>🧠 资金行为：</b>{credit_desc}</div>", unsafe_allow_html=True)

    st.markdown("---")

    st.header("2️⃣ 聪明钱因子 (Smart Money Factors)")
    off_f = {"动量": get_ret('MTUM'), "小盘": get_ret('IWM'), "高贝塔": get_ret('SPHB'), "投机": get_ret('ARKK')}
    def_f = {"低波": get_ret('USMV'), "质量": get_ret('QUAL'), "价值": get_ret('VLUE'), "红利": get_ret('VIG')}
    
    off_mean = sum(off_f.values()) / len(off_f)
    def_mean = sum(def_f.values()) / len(def_f)
    best_f = max({**off_f, **def_f}, key={**off_f, **def_f}.get)
    
    if off_mean > def_mean + 0.5:
        factor_desc = "⚔️ **进攻占优 (Risk-On):** 动量、高贝塔等高弹性因子整体领涨，资金疯狂追逐利润，市场情绪较为亢奋。"
    elif def_mean > off_mean + 0.5:
        factor_desc = "🛡️ **防守占优 (Risk-Off):** 红利、低波等防御因子抗跌，资金正在进行避险调仓，防范下行风险。"
    else:
        factor_desc = "⚖️ **均衡博弈:** 进攻与防守因子整体表现差异不大，市场处于风格切换的震荡期或缺乏主线。"
    
    c_f1, c_f2 = st.columns(2)
    with c_f1:
        fig_off = px.bar(pd.DataFrame(list(off_f.items()), columns=['F', 'V']), x='V', y='F', orientation='h', color='V', color_continuous_scale='RdYlGn', range_color=[-5,5])
        fig_off.update_layout(height=200, plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd'), title="⚔️ 进攻组 (Risk)")
        st.plotly_chart(fig_off, use_container_width=True)
    with c_f2:
        fig_def = px.bar(pd.DataFrame(list(def_f.items()), columns=['F', 'V']), x='V', y='F', orientation='h', color='V', color_continuous_scale='RdYlGn', range_color=[-5,5])
        fig_def.update_layout(height=200, plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd'), title="🛡️ 防守组 (Safety)")
        st.plotly_chart(fig_def, use_container_width=True)

    st.markdown(f"<div class='conclusion-box'><b>🧠 因子轮动结论：</b>{factor_desc} (当前市场最强单一因子为: <b>{best_f}</b>)</div>", unsafe_allow_html=True)

    st.markdown("---")

    st.header("3️⃣ 四大剧本推演 (The Four Horsemen)")

    prob_a = int(raw_probs.get("Soft", 0) * 100)
    prob_b = int(raw_probs.get("Hot", 0) * 100)
    prob_c = int(raw_probs.get("Stag", 0) * 100)
    prob_d = int(raw_probs.get("Rec", 0) * 100)

    def check(condition, desc_pass, desc_fail):
        if condition: return f"<div class='ev-item'><span class='ev-pass'>✅</span> <span>{desc_pass}</span></div>"
        else: return f"<div class='ev-item'><span class='ev-fail'>⚪</span> <span>{desc_fail}</span></div>"

    # =======================================================
    # 🧠 将全新的 5阶 SPY 状态深度融入白盒化推演中
    # =======================================================
    items_a = [
        check("Recovery" in api_clock_regime or "Soft" in api_clock_regime, "时钟指向复苏/软着陆", f"时钟不符 ({api_clock_regime})"),
        check(is_bullish, f"美股维持上升通道 ({spy_status})", f"美股动能破坏 ({spy_status})"),
        check(get_ret('XLY') > get_ret('XLP'), f"消费信心强 (XLY收益 > XLP)", f"消费防御占优 (XLY弱于XLP)"),
        check(get_ret('XLK') > 0, f"科技领涨 (+{get_ret('XLK'):.1f}%)", f"科技走弱 ({get_ret('XLK'):.1f}%)"),
        check(hyg_ief_diff > -0.5, f"信用风险低 (HYG-IEF利差: {hyg_ief_diff:.2f}%)", f"信用利差走阔 ({hyg_ief_diff:.2f}%)")
    ]
    items_b = [
        check("Overheat" in api_clock_regime, "时钟指向过热/再通胀", f"时钟不符 ({api_clock_regime})"),
        check(get_ret('CPER') > 0 or get_ret('USO') > 0, f"大宗商品上涨 (铜{get_ret('CPER'):.1f}%, 油{get_ret('USO'):.1f}%)", f"大宗走弱 (铜{get_ret('CPER'):.1f}%, 油{get_ret('USO'):.1f}%)"),
        check(get_ret('XLI') > get_ret('SPY'), "工业/制造跑赢大盘 (XLI > SPY)", "工业跑输大盘"),
        check(tip_ief_diff > 0, f"通胀预期抬头 (TIP-IEF: {tip_ief_diff:.2f}%)", f"通胀预期平稳 ({tip_ief_diff:.2f}%)"),
        check(get_ret('KRE') > 0, f"银行/金融活跃 (+{get_ret('KRE'):.1f}%)", f"银行走弱 ({get_ret('KRE'):.1f}%)")
    ]
    items_c = [
        check("Stagflation" in api_clock_regime, "时钟指向滞胀", f"时钟不符 ({api_clock_regime})"),
        check("熊平" in curve_shape, f"曲线熊平 (短端利率上行抗通胀)", f"形态不符 ({curve_shape})"),
        check(get_ret('GLD') > get_ret('SPY'), "黄金跑赢美股 (GLD > SPY)", "黄金未跑赢"),
        check(get_ret('VLUE') > get_ret('MTUM'), "价值跑赢成长 (VLUE > MTUM)", "成长跑赢价值"),
        check(not is_bullish, f"美股上升趋势破坏 ({spy_status})", f"美股仍具韧性 ({spy_status})")
    ]
    items_d = [
        check("Reflation" in api_clock_regime, "时钟指向衰退", f"时钟不符 ({api_clock_regime})"),
        check("牛陡" in curve_shape, f"曲线牛陡 (长债买盘汹涌/衰退交易)", f"形态不符 ({curve_shape})"),
        check(tlt_shy_diff > 1.5, f"长债大涨避险 (TLT-SHY: {tlt_shy_diff:.2f}%)", f"长债平淡 ({tlt_shy_diff:.2f}%)"),
        check(get_ret('XLP') > get_ret('SPY'), "必选消费/公用抗跌 (XLP > SPY)", "防御板块未跑赢"),
        check(get_ret('HYG') < -1, f"信用利差崩塌 ({get_ret('HYG'):.1f}%)", f"信用尚可 ({get_ret('HYG'):.1f}%)")
    ]

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown(f"<div class='scenario-card'><b>🌤️ 软着陆 ({prob_a}%)</b><div class='evidence-list'>{''.join(items_a)}</div></div>", unsafe_allow_html=True)
    with c2: st.markdown(f"<div class='scenario-card'><b>🔥 再通胀 ({prob_b}%)</b><div class='evidence-list'>{''.join(items_b)}</div></div>", unsafe_allow_html=True)
    with c3: st.markdown(f"<div class='scenario-card'><b>🌧️ 滞胀 ({prob_c}%)</b><div class='evidence-list'>{''.join(items_c)}</div></div>", unsafe_allow_html=True)
    with c4: st.markdown(f"<div class='scenario-card'><b>❄️ 衰退 ({prob_d}%)</b><div class='evidence-list'>{''.join(items_d)}</div></div>", unsafe_allow_html=True)

    st.markdown("---")

    st.header("4️⃣ 分场景实战推荐 (Sector & Stock Picks)")
    st.caption("穿透板块表面：当板块强势时，自动为您展开其底层三大权重龙头股进行精确制导。")
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
                    col.markdown(f"✅ **{t} ({display_name})**<br><span style='font-size:12px;color:#aaa'>Z: {z_score:.2f} | 强势</span>", unsafe_allow_html=True)
                else: 
                    col.markdown(f"<span style='color:#555'>🔒 {t} ({display_name})</span><br><span style='font-size:12px;color:#444'>Z: {z_score:.2f} | 观察 (板块休整)</span>", unsafe_allow_html=True)
                
                if t in TOP_HOLDINGS:
                    for sub_t in TOP_HOLDINGS[t]:
                        if sub_t in df.columns:
                            sub_ts = df[sub_t].dropna()
                            if len(sub_ts) < 200: continue
                            sub_curr = float(sub_ts.iloc[-1])
                            sub_rm = float(sub_ts.rolling(250).mean().iloc[-1])
                            sub_rs = float(sub_ts.rolling(250).std().iloc[-1])
                            sub_z = (sub_curr - sub_rm) / sub_rs if sub_rs != 0 else 0.0
                            
                            sub_m20 = float(sub_ts.rolling(20).mean().iloc[-1])
                            sub_m60 = float(sub_ts.rolling(60).mean().iloc[-1])
                            sub_icon = "🔥" if sub_m20 > sub_m60 else "⏱️"
                            
                            opacity_style = "opacity: 1.0;" if is_active else "opacity: 0.4;"
                            col.markdown(f"<div class='sub-ticker' style='{opacity_style}'>{sub_icon} <b>{sub_t}</b> ({ASSET_NAMES.get(sub_t, sub_t)}) | Z: {sub_z:.1f}</div>", unsafe_allow_html=True)
            except: continue

    col_pa, col_pb, col_pc, col_pd = st.columns(4)
    with col_pa:
        st.subheader("🟢 买入：软着陆")
        render_picks_with_stocks(TARGETS_A, col_pa)
    with col_pb:
        st.subheader("🟡 买入：再通胀")
        render_picks_with_stocks(TARGETS_B, col_pb)
    with col_pc:
        st.subheader("🟠 买入：滞胀")
        render_picks_with_stocks(TARGETS_C, col_pc)
    with col_pd:
        st.subheader("🔴 买入：衰退")
        render_picks_with_stocks(TARGETS_D, col_pd)

    st.markdown("---")
    st.header("5️⃣ 市场分化证据链 (Market Differentiation)")
    st.caption("共振 (大家都一样) vs 分化 (只有少数人赢) — 结构性机会的早期预警")

    sector_disp_cols = [t for t in ['XLK', 'XLF', 'XLV', 'XLY', 'XLP', 'XLE', 'XLI', 'XLB', 'XLU', 'XLRE', 'XLC'] if t in df.columns]
    if 'RSP' in df.columns and len(sector_disp_cols) >= 5:
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