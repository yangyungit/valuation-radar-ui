# cn_names.py
# 接力图/持仓表统一中文名字典。所有页面的股票/ETF 标签一律 "中文名(代码)"，查不到就只显示代码，
# 绝不回退显示后端返回的英文全称或英文 sector 标签。
#
# 来源合并（后写覆盖先写，冲突时人工挑更完整/更常见的译名）：
#   1. valuation-radar/my_stock_pool.py 的 MY_POOL + Z_SEED_POOL（主理人自选战术池，含 ETF/债券）
#   2. pages/20_FCF进攻.py 原 _TICKER_CN_NAME（纯科技子池曾用票）
#   3. pages/23_科技龙头.py 原 _TICKER_CN_NAME（标普500+纳指100合并池曾用票）
#
# 新增覆盖不到的 ticker：直接在这里加一行，所有页面立即生效，不用逐页改。

CN_NAMES: dict[str, str] = {
    # ── 防守/稳健 ──
    "GLD": "黄金ETF", "XLU": "公用事业ETF", "XLP": "必选消费ETF", "XLV": "医疗保健ETF",
    "WMT": "沃尔玛", "TJX": "TJX百货", "RSG": "共和废品", "LLY": "礼来制药",
    "COST": "好市多", "KO": "可口可乐", "V": "Visa", "BRK-B": "伯克希尔",
    "ISRG": "直觉外科", "LMT": "洛克希德", "WM": "废物管理", "JNJ": "强生",
    "LIN": "林德气体", "UNH": "联合健康", "NEE": "新纪元能源", "DUK": "杜克能源",
    "SO": "南方公司", "PG": "宝洁", "PEP": "百事", "PFE": "辉瑞",
    "TGT": "塔吉特", "MCD": "麦当劳",

    # ── 核心/基石 ──
    "GOOGL": "谷歌", "MSFT": "微软", "AMZN": "亚马逊", "AAPL": "苹果",
    "PWR": "广达服务", "CACI": "CACI国际", "MNST": "怪兽饮料", "XOM": "埃克森美孚",
    "CVX": "雪佛龙", "META": "Meta", "NFLX": "奈飞",

    # ── 时代之王 ──
    "TSLA": "特斯拉", "NVDA": "英伟达", "PLTR": "帕兰提尔", "VRT": "维谛技术",
    "NOC": "诺斯罗普", "XAR": "航空国防ETF", "MS": "摩根士丹利", "GS": "高盛",
    "ANET": "Arista网络", "ETN": "伊顿电力", "BTC-USD": "比特币", "ETH-USD": "以太坊",
    "GOLD": "巴里克黄金", "TSM": "台积电", "AVGO": "博通", "AMD": "超威半导体",
    "CRM": "赛富时", "ADBE": "奥多比", "INTU": "直觉软件",

    # ── 观察/潜力 ──
    "FCX": "自由港铜金", "AG": "First Majestic", "HL": "赫克拉矿业", "BHP": "必和必拓",
    "VALE": "淡水河谷", "RIO": "力拓", "MU": "美光科技", "SPIR": "Spire Global",
    "APPS": "Digital Turbine", "WDC": "西部数据", "NET": "Cloudflare", "ITA": "航空国防ETF",
    "KTOS": "Kratos防务", "BKR": "贝克休斯", "BAH": "博思艾伦", "TDW": "泰德威特",
    "TRGP": "Targa资源", "UEC": "铀能源公司", "CCJ": "Cameco铀矿", "URA": "铀矿ETF",
    "BTI": "英美烟草", "MO": "奥驰亚", "FIGS": "Figs医疗服饰", "COP": "康菲石油",
    "EOG": "EOG能源", "OXY": "西方石油", "SLB": "斯伦贝谢", "HAL": "哈里伯顿",
    "GE": "通用电气", "CAT": "卡特彼勒", "HON": "霍尼韦尔", "SCCO": "南方铜业",
    "TECK": "泰克资源", "VMC": "火神材料", "MLM": "马丁玛丽埃塔", "URI": "联合租赁",
    "DHI": "霍顿房屋", "LEN": "莱纳建筑", "PHM": "普尔特房屋", "USB": "美国合众银行",
    "PNC": "PNC金融", "TFC": "Truist", "NEM": "纽蒙特", "AEM": "伊格尔矿业",
    "PAAS": "泛美白银", "ADM": "阿彻丹尼尔斯", "BG": "邦吉", "TSN": "泰森食品",
    "NXE": "NexGen", "UUUU": "Energy Fuels", "COIN": "Coinbase", "BLK": "贝莱德",
    "SMH": "半导体ETF", "IGV": "软件ETF", "AIQ": "AI主题ETF", "PICK": "矿业ETF",
    "PAVE": "基建ETF", "PBR": "巴西石油", "HD": "家得宝", "XRT": "零售ETF",

    # ── Z级种子池：生息资产 ──
    "BIL": "1-3月超短期国债ETF", "SGOV": "0-3月国债ETF", "SHV": "短期国债ETF",
    "SHY": "1-3年期国债ETF", "IEF": "7-10年期国债ETF", "TLT": "20+年长期国债ETF",
    "GOVT": "全谱美债ETF", "AGG": "美国综合债券ETF", "LQD": "投资级公司债ETF",
    "HYG": "高收益公司债ETF", "EMB": "新兴市场美元债ETF", "SCHD": "Schwab高息ETF",
    "VYM": "Vanguard高股息ETF", "JEPI": "JPM权益增强收益ETF", "JEPQ": "JPM纳指增强收益ETF",
    "DVY": "iShares精选红利ETF", "HDV": "iShares高股息ETF", "NOBL": "股息贵族ETF",
    "O": "Realty Income月度分红REIT", "VNQ": "Vanguard REIT ETF", "STAG": "STAG工业地产REIT",
    "PFF": "iShares优先股ETF", "STRF": "Strategy 10%永续优先股", "STRK": "Strategy 8%可转换优先股",
    "ARCC": "Ares资本BDC", "MAIN": "Main Street资本BDC",

    # ── 纯科技子池曾用票（原 page20 _TICKER_CN_NAME）──
    "AKAM": "阿卡迈", "AMAT": "应用材料", "ANSS": "ANSYS(仿真软件)", "APH": "安费诺",
    "AZPN1": "阿斯本技术", "CDNS": "铿腾电子", "CLGX": "CoreLogic", "CPAY": "Corpay",
    "CRUS": "凌云逻辑", "CSCO": "思科", "CTXS": "思杰", "DBX": "Dropbox",
    "FFIV": "F5网络", "FISV": "费哲金融服务", "FLIR": "菲力尔", "FTNT": "飞塔",
    "GDDY": "戈达迪", "GLW": "康宁", "INTC": "英特尔", "IT": "高德纳",
    "JKHY": "杰克亨利", "KEYS": "是德科技", "KLAC": "科磊", "LRCX": "泛林集团",
    "MANH": "曼哈顿软件", "MXIM": "美信集成", "NTAP": "网存", "NUAN": "纽昂斯通讯",
    "NXPI": "恩智浦", "ORCL": "甲骨文", "QCOM": "高通", "QRVO": "威讯联合半导体",
    "RHT": "红帽", "RMBS": "兰博士", "SWKS": "思佳讯", "TDC": "天睿",
    "TER": "泰瑞达", "TXN": "德州仪器", "UI": "优比快", "VMW": "威睿",
    "XLNX": "赛灵思",

    # ── 标普500+纳指100合并池曾用票（原 page23 _TICKER_CN_NAME）──
    "ABMD": "雅培诊断", "ALGN": "爱齐科技", "APA": "阿帕奇", "APP": "AppLovin",
    "ARM": "ARM", "BA": "波音", "BBBY": "Bed Bath & Beyond", "BBWI": "Bath & Body Works",
    "BMRN": "百傲维昂医药", "CEG": "星座能源", "CHKAQ": "切萨皮克能源", "CMG": "奇波雷",
    "CRWD": "CrowdStrike", "CSX": "CSX运输", "CVC": "Cablevision", "DINO": "HF Sinclair",
    "DOCU": "DocuSign", "DVN": "德文能源", "DXCM": "德康医疗", "EA": "艺电",
    "ENPH": "Enphase", "EQT": "EQT能源", "EW": "爱德华兹生命科学", "FSLR": "第一太阳能",
    "HOOD": "罗宾汉", "LBTYA": "自由全球", "LBTYK": "自由全球", "LITE": "Lumentum",
    "LULU": "露露乐蒙", "LUV": "西南航空", "MELI": "美客多", "MKTX": "MarketAxess",
    "MOS": "美盛", "MRNA": "莫德纳", "MRO": "马拉松石油", "NKTR": "Nektar",
    "NRG": "NRG能源", "OKE": "Oneok", "PDD": "拼多多", "PTON": "Peloton",
    "PYPL": "PayPal", "RCL": "皇家加勒比", "SGEN": "Seagen", "SHPG": "夏尔制药",
    "SMCI": "美超微", "SNDK": "闪迪", "SPLK": "Splunk", "STX": "希捷",
    "TE1": "TECO能源", "TPR": "泰佩思琦", "TRI": "汤森路透", "TRIP": "猫途鹰",
    "TTWO": "Take-Two", "TWTR": "推特", "UA": "安德玛", "VOD": "沃达丰",
    "VST": "Vistra", "WDAY": "Workday", "ZM": "Zoom",

    # ── 回购股股东回报率池曾用票（原 page18 用后端英文 name 兜底，改用中文名）──
    "AZO": "汽车地带", "ORLY": "奥莱利", "NVR": "NVR", "DPZ": "达美乐",
    "BKNG": "缤客", "MA": "万事达卡", "MCO": "穆迪", "SPGI": "标普全球",
    "MSCI": "明晟", "AXP": "美国运通", "SBUX": "星巴克", "LOW": "劳氏",
    "NKE": "耐克", "YUM": "百胜餐饮", "PM": "菲利普莫里斯国际",
    "ITW": "伊利诺伊工具", "SHW": "宣伟涂料", "UNP": "联合太平洋",

    # ── 黄金带鱼规则池曾用票（原 page14 只手写了4只，其余英文兜底）──
    "AJG": "亚瑟加拉格尔", "AMT": "美国铁塔", "CME": "芝商所", "GWW": "固安捷",
    "MRSH": "威达信集团", "PGR": "前进保险", "TMO": "赛默飞世尔", "ZTS": "硕腾",

    # ── 动量双龙/戴金龙头曾用票（标普板块龙头）──
    "BAC": "美国银行", "JPM": "摩根大通", "BRK.B": "伯克希尔",
}


def cn_name(ticker: str) -> str:
    """查不到就返回空串——调用方应回退到只显示代码，不准回退到英文名/英文 sector。"""
    return CN_NAMES.get(ticker, "")


def cn_name_map(tickers) -> dict[str, str]:
    """批量版，用于给 render_group/build_stitched_fig 的 grade_map 传参。"""
    return {tk: CN_NAMES.get(tk, "") for tk in tickers}
