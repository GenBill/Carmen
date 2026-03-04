from openai import OpenAI
from datetime import datetime
import json
import pytz
from typing import Optional, List, Dict, Any

# LangChain imports (稳定接口 - 仅用于工具定义和 LLM)
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

# 股票数据和搜索
import yfinance as yf
import pandas as pd
from ddgs import DDGS

# A 股数据（akshare，与 basic_analysis 共用逻辑，避免重复）
try:
    import akshare as ak
    import requests
    from bs4 import BeautifulSoup
    import re
    _AKSHARE_AVAILABLE = True
except ImportError:
    _AKSHARE_AVAILABLE = False


# ============== A 股数据获取（与 basic_analysis 共用，以 akshare 为准） ==============

def _is_a_share(symbol: str) -> bool:
    """判断是否为 A 股代码（6 位数字或 .SS/.SZ 后缀）"""
    s = str(symbol).strip().upper()
    if s.endswith(".SS") or s.endswith(".SZ"):
        return len(s) >= 8
    if s.isdigit() and len(s) == 6:
        return True
    return False


def _normalize_a_share_code(symbol: str) -> str:
    """提取 A 股 6 位代码"""
    s = str(symbol).strip()
    if s.endswith(".SS") or s.endswith(".SZ"):
        return s[:6]
    return s if s.isdigit() and len(s) == 6 else ""


def _to_yfinance_a_share(symbol: str) -> str:
    """转换为 yfinance 所需格式（如 300935.SZ）"""
    code = _normalize_a_share_code(symbol)
    if not code:
        return symbol
    return f"{code}.SZ" if code.startswith(("0", "3")) else f"{code}.SS"


def _fetch_a_share_holder_count(code: str) -> str:
    """从 akshare 获取最新股东户数"""
    if not _AKSHARE_AVAILABLE:
        return "N/A"
    try:
        df = ak.stock_zh_a_gdhs_detail_em(symbol=code)
        if df.empty or len(df) < 1:
            return "N/A"
        latest = df.iloc[-1]
        count = latest.get("股东户数-本次", latest.get("股东户数", "N/A"))
        if pd.isna(count):
            return "N/A"
        cnt = float(count)
        return f"{cnt/10000:.2f}万" if cnt >= 10000 else f"{int(cnt)}"
    except Exception:
        return "N/A"


def _fetch_a_share_profit_forecast(code: str) -> str:
    """从 akshare 获取最新业绩预告"""
    if not _AKSHARE_AVAILABLE:
        return "暂无"
    dates = ["20241231", "20240930", "20240630", "20231231"]
    for date in dates:
        try:
            df = ak.stock_yjyg_em(date=date)
            if df.empty:
                continue
            col_code = "股票代码" if "股票代码" in df.columns else "代码"
            if col_code not in df.columns:
                continue
            sub = df[df[col_code].astype(str) == str(code)]
            if sub.empty:
                continue
            row = sub.iloc[0]
            pred = row.get("预测指标", row.get("业绩变动", ""))
            change = row.get("业绩变动", row.get("业绩变动幅度", ""))
            return f"{pred}: {change}"[:80]
        except Exception:
            continue
    return "暂无"


def _fetch_a_share_concepts(code: str) -> list:
    """从东方财富页面提取概念标签"""
    if not _AKSHARE_AVAILABLE:
        return []
    try:
        prefix = "sz" if code.startswith("3") or code.startswith("0") else "sh"
        url = f"https://quote.eastmoney.com/{prefix}{code}.html"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        soup = BeautifulSoup(resp.text, "html.parser")
        tags = soup.find_all("span", class_="tag")
        return [t.get_text(strip=True) for t in tags if t.get_text(strip=True)][:5]
    except Exception:
        return []


def fetch_a_share_data(code: str, name: str = None) -> Dict[str, Any]:
    """
    获取 A 股完整基本面数据（akshare 为准）。
    供 basic_analysis 和 Agent 工具复用，避免重复载入。
    """
    if not _AKSHARE_AVAILABLE:
        return {}
    try:
        spot = ak.stock_zh_a_spot_em()
        match = spot[spot["代码"] == code]
        if match.empty:
            return {}
        current = match.iloc[0]
        price = current["最新价"]
        change = current["涨跌幅"]
        turnover = current["换手率"]
        vol_ratio_raw = current.get("量比")
        vol_ratio = round(float(vol_ratio_raw), 2) if pd.notna(vol_ratio_raw) else "N/A"

        if vol_ratio == "N/A":
            try:
                hist = ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=(datetime.now() - pd.Timedelta(days=90)).strftime("%Y%m%d"),
                )
                hist = hist.sort_values("日期")
                if len(hist) >= 5:
                    roll_mean = hist["成交量"].rolling(5).mean().iloc[-1]
                    vol_ratio = round(hist["成交量"].iloc[-1] / roll_mean, 2) if roll_mean and roll_mean > 0 else "N/A"
            except Exception:
                pass

        roe, pe, pb, revenue_growth = "N/A", "N/A", "N/A", "N/A"
        try:
            financials = ak.stock_financial_analysis_indicator(symbol=code)
            if not financials.empty:
                latest_fin = financials.iloc[-1]
                roe = latest_fin.get("ROE", "N/A")
                pe = latest_fin.get("PE", "N/A")
                pb = latest_fin.get("PB", "N/A")
                revenue_growth = latest_fin.get("营业总收入同比增长率", "N/A")
        except Exception:
            pass

        if pe == "N/A" and pd.notna(current.get("市盈率-动态")):
            pe = current["市盈率-动态"]
        if pb == "N/A" and pd.notna(current.get("市净率")):
            pb = current["市净率"]

        industry = "N/A"
        try:
            info_df = ak.stock_individual_info_em(symbol=code)
            if not info_df.empty:
                info = dict(zip(info_df["item"], info_df["value"]))
                industry = info.get("行业", "N/A")
        except Exception:
            pass

        holders = _fetch_a_share_holder_count(code)
        forecast = _fetch_a_share_profit_forecast(code)
        concepts = _fetch_a_share_concepts(code)
        if not concepts:
            concepts = [industry] if industry != "N/A" else []

        return {
            "代码": code,
            "名称": name or current["名称"],
            "最新价": price,
            "涨跌幅": change,
            "换手率": turnover,
            "量比": vol_ratio,
            "ROE": roe,
            "PE": pe,
            "PB": pb,
            "营收同比增长": revenue_growth,
            "行业": industry,
            "股东户数": holders,
            "概念": concepts[:5],
            "最新预告": forecast,
        }
    except Exception:
        return {}


# ============== 工具定义 ==============

@tool
def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    """获取指定时区的当前时间。用于了解市场开盘/收盘状态。
    
    Args:
        timezone: 时区名称，如 "Asia/Shanghai", "America/New_York", "UTC"
    """
    try:
        tz = pytz.timezone(timezone)
        current_time = datetime.now(tz)
        return f"当前时间 ({timezone}): {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    except Exception as e:
        return f"获取时间失败: {str(e)}"


@tool
def search_company_news(query: str, max_results: int = 5) -> str:
    """搜索公司相关的最新新闻和信息。
    
    Args:
        query: 搜索关键词，如 "苹果公司最新新闻" 或 "AAPL stock news"
        max_results: 返回结果数量，默认5条
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results))
        
        if not results:
            return f"未找到关于 '{query}' 的新闻"
        
        news_text = f"关于 '{query}' 的最新新闻:\n\n"
        for i, r in enumerate(results, 1):
            news_text += f"{i}. **{r.get('title', 'N/A')}**\n"
            news_text += f"   来源: {r.get('source', 'N/A')} | 日期: {r.get('date', 'N/A')}\n"
            news_text += f"   摘要: {r.get('body', 'N/A')[:200]}...\n\n"
        
        return news_text
    except Exception as e:
        return f"搜索新闻失败: {str(e)}"


@tool
def search_web(query: str, max_results: int = 5) -> str:
    """通用网络搜索，获取公司信息、行业分析等。
    
    Args:
        query: 搜索关键词
        max_results: 返回结果数量，默认5条
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        
        if not results:
            return f"未找到关于 '{query}' 的结果"
        
        search_text = f"搜索 '{query}' 的结果:\n\n"
        for i, r in enumerate(results, 1):
            search_text += f"{i}. **{r.get('title', 'N/A')}**\n"
            search_text += f"   链接: {r.get('href', 'N/A')}\n"
            search_text += f"   摘要: {r.get('body', 'N/A')[:300]}...\n\n"
        
        return search_text
    except Exception as e:
        return f"搜索失败: {str(e)}"


@tool
def get_stock_data_comprehensive(symbol: str, period: str = "1mo") -> str:
    """获取股票完整数据（价格+财务+基本面）。A 股优先使用 akshare（含股东户数、业绩预告、行业、概念），港股/美股使用 yfinance。一次调用即可，避免重复获取。
    
    Args:
        symbol: 股票代码，如 "AAPL", "0700.HK", "600519", "300935.SZ"
        period: 时间范围（仅港股/美股生效），可选: "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"
    """
    try:
        if _is_a_share(symbol):
            code = _normalize_a_share_code(symbol)
            if not code:
                return f"无效的 A 股代码: {symbol}"
            data = fetch_a_share_data(code)
            if not data:
                return f"未找到 A 股 {symbol} 的数据"
            return f"**{data.get('名称', '')} ({data.get('代码', '')}) A 股数据**\n\n" + json.dumps(data, ensure_ascii=False, indent=2)
    
        stock = yf.Ticker(symbol)
        hist = stock.history(period=period)
        info = stock.info
        
        if hist.empty:
            return f"未找到股票 {symbol} 的数据，请检查代码是否正确"
        
        current_price = hist['Close'].iloc[-1]
        open_price = hist['Open'].iloc[-1]
        high = hist['High'].iloc[-1]
        low = hist['Low'].iloc[-1]
        volume = hist['Volume'].iloc[-1]
        
        if len(hist) > 1:
            prev_close = hist['Close'].iloc[-2]
            change = ((current_price - prev_close) / prev_close) * 100
            change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
        else:
            change_str = "N/A"
        
        period_start = hist['Close'].iloc[0]
        period_change = ((current_price - period_start) / period_start) * 100
        period_change_str = f"+{period_change:.2f}%" if period_change > 0 else f"{period_change:.2f}%"
        
        result = f"**{symbol} 股票数据** (周期: {period})\n\n"
        result += f"当前价格: ${current_price:.2f}\n"
        result += f"今日开盘: ${open_price:.2f}\n"
        result += f"今日最高: ${high:.2f}\n"
        result += f"今日最低: ${low:.2f}\n"
        result += f"成交量: {volume:,.0f}\n"
        result += f"日涨跌: {change_str}\n"
        result += f"周期涨跌 ({period}): {period_change_str}\n"
        
        if info and info.get('symbol'):
            result += f"\n**财务数据**\n"
            result += f"交易所: {info.get('fullExchangeName', info.get('exchange', 'N/A'))}\n"
            result += f"货币: {info.get('currency', 'N/A')}\n"
            result += f"行业: {info.get('industry', 'N/A')}\n"
            result += f"市值: ${info.get('marketCap', 0):,.0f}\n"
            result += f"市盈率 (PE): {info.get('trailingPE', 'N/A')}\n"
            result += f"市净率 (PB): {info.get('priceToBook', 'N/A')}\n"
            result += f"每股收益 (EPS): ${info.get('trailingEps', 'N/A')}\n"
            result += f"股息率: {info.get('dividendYield', 0) * 100 if info.get('dividendYield') else 0:.2f}%\n"
            result += f"52周最高: ${info.get('fiftyTwoWeekHigh', 'N/A')}\n"
            result += f"52周最低: ${info.get('fiftyTwoWeekLow', 'N/A')}\n"
            if info.get('longBusinessSummary'):
                result += f"\n**业务简介:**\n{info.get('longBusinessSummary', 'N/A')[:500]}...\n"
        
        return result
    except Exception as e:
        return f"获取股票数据失败: {str(e)}"


@tool
def calculate_technical_indicators(symbol: str, period: str = "3mo") -> str:
    """计算股票的技术指标，包括 MA、RSI、MACD、布林带等。
    
    Args:
        symbol: 股票代码，如 "AAPL", "0700.HK", "300935"
        period: 数据周期，建议至少 "3mo" 以获得足够数据计算指标
    """
    try:
        yf_symbol = _to_yfinance_a_share(symbol) if _is_a_share(symbol) else symbol
        stock = yf.Ticker(yf_symbol)
        df = stock.history(period=period)
        
        if df.empty or len(df) < 20:
            return f"数据不足，无法计算 {symbol} 的技术指标"
        
        close = df['Close']
        
        # 移动平均线
        ma5 = close.rolling(window=5).mean().iloc[-1]
        ma10 = close.rolling(window=10).mean().iloc[-1]
        ma20 = close.rolling(window=20).mean().iloc[-1]
        ma60 = close.rolling(window=60).mean().iloc[-1] if len(close) >= 60 else None
        
        # RSI (14日)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        rsi_value = rsi.iloc[-1]
        
        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        macd_hist = macd - signal
        
        # 布林带 (20日)
        bb_middle = close.rolling(window=20).mean()
        bb_std = close.rolling(window=20).std()
        bb_upper = bb_middle + (bb_std * 2)
        bb_lower = bb_middle - (bb_std * 2)
        
        current_price = close.iloc[-1]
        
        # 趋势判断
        trend = "上涨趋势 📈" if current_price > ma20 > ma60 else ("下跌趋势 📉" if current_price < ma20 < ma60 else "震荡整理 ↔️") if ma60 else ("上涨趋势 📈" if current_price > ma20 else "下跌趋势 📉")
        
        # RSI 解读
        rsi_signal = "超买 ⚠️" if rsi_value > 70 else ("超卖 ⚠️" if rsi_value < 30 else "正常")
        
        # MACD 金叉/死叉：比较前后两根 K 线判断是否已发生穿越
        macd_now, signal_now = macd.iloc[-1], signal.iloc[-1]
        macd_prev, signal_prev = macd.iloc[-2], signal.iloc[-2]
        ema12_now, ema26_now = ema12.iloc[-1], ema26.iloc[-1]
        golden_cross = macd_prev <= signal_prev and macd_now > signal_now
        death_cross = macd_prev >= signal_prev and macd_now < signal_now

        # 预期金叉/死叉：按下一日收盘价=当前价估算 MACD、信号线，判断是否将发生穿越
        close_next = current_price
        alpha12, alpha26, alpha9 = 2 / 13, 2 / 27, 2 / 10
        ema12_next = alpha12 * close_next + (1 - alpha12) * ema12_now
        ema26_next = alpha26 * close_next + (1 - alpha26) * ema26_now
        macd_next = ema12_next - ema26_next
        signal_next = alpha9 * macd_next + (1 - alpha9) * signal_now
        expect_golden = macd_now < signal_now and macd_next > signal_next
        expect_death = macd_now > signal_now and macd_next < signal_next

        if golden_cross:
            macd_signal = "金叉（MACD上穿信号线）🟢"
        elif death_cross:
            macd_signal = "死叉（MACD下穿信号线）🔴"
        elif expect_golden:
            macd_signal = "预期金叉（明日MACD将上穿信号线）🟢"
        elif expect_death:
            macd_signal = "预期死叉（明日MACD将下穿信号线）🔴"
        else:
            macd_signal = "MACD 在信号线上方-偏多" if macd_now > signal_now else "MACD 在信号线下方-偏空"
        
        result = f"**{symbol} 技术指标分析**\n\n"
        result += f"当前价格: ${current_price:.2f}\n\n"
        result += f"**移动平均线:**\n"
        result += f"  MA5: ${ma5:.2f} {'↑' if current_price > ma5 else '↓'}\n"
        result += f"  MA10: ${ma10:.2f} {'↑' if current_price > ma10 else '↓'}\n"
        result += f"  MA20: ${ma20:.2f} {'↑' if current_price > ma20 else '↓'}\n"
        if ma60:
            result += f"  MA60: ${ma60:.2f} {'↑' if current_price > ma60 else '↓'}\n"
        result += f"\n**RSI (14日):** {rsi_value:.2f} - {rsi_signal}\n"
        result += f"\n**MACD:**\n"
        result += f"  MACD线: {macd.iloc[-1]:.4f}\n"
        result += f"  信号线: {signal.iloc[-1]:.4f}\n"
        result += f"  柱状图: {macd_hist.iloc[-1]:.4f}\n"
        result += f"  信号: {macd_signal}\n"
        result += f"\n**布林带 (20日):**\n"
        result += f"  上轨: ${bb_upper.iloc[-1]:.2f}\n"
        result += f"  中轨: ${bb_middle.iloc[-1]:.2f}\n"
        result += f"  下轨: ${bb_lower.iloc[-1]:.2f}\n"
        result += f"\n**综合趋势:** {trend}\n"
        
        return result
    except Exception as e:
        return f"计算技术指标失败: {str(e)}"


# ============== Agent 工具列表 ==============

# 全部工具（独立调用时使用）
# 使用 get_stock_data_comprehensive 替代 get_stock_price + get_stock_financials，避免重复载入
FULL_TOOLS = [
    get_current_time,
    search_company_news,
    search_web,
    get_stock_data_comprehensive,
    calculate_technical_indicators,
]

# 仅搜索工具（已有预处理数据时使用，避免重复获取）
SEARCH_ONLY_TOOLS = [
    get_current_time,
    search_company_news,
    search_web,
]


# ============== DeepSeek API 类 ==============

class DeepSeekAPI:
    def __init__(
        self, 
        token_path="agent/deepseek.token", 
        system_prompt="You are a helpful assistant", 
        model_type="deepseek-chat"
    ):
        # Load DeepSeek API key from file
        with open(token_path, "r") as file:
            self.mytoken = file.read().strip()
        self.client = OpenAI(
            api_key = self.mytoken,
            base_url = "https://api.deepseek.com")
        
        self.system_prompt = system_prompt
        self.dialog = []
        self.dialog.append({"role": "system", "content": system_prompt})
        self.model_type = model_type
        
        # LangChain Agent 初始化
        self._chat_history = []
        self._llm = None
    
    def _get_llm(self):
        """获取 LLM 实例（惰性初始化）"""
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=self.model_type,
                api_key=self.mytoken,
                base_url="https://api.deepseek.com",
                temperature=0.7,
            )
        return self._llm
    
    def _build_system_prompt(self, base_prompt: str, tools: list) -> str:
        """构建带工具说明的系统提示词"""
        if tools == SEARCH_ONLY_TOOLS:
            tool_instruction = """

你可以使用以下工具辅助分析：
- get_current_time: 获取当前时间，了解市场开盘状态
- search_company_news: 搜索公司最新新闻和事件
- search_web: 搜索公司信息、行业分析、政策新闻等

重要提示：
对于中国股票（A股/港股），yfinance 可能返回英文名。请务必先使用 search_web 搜索该代码对应的中文简称（例如搜索 '0700.HK 中文名'），然后使用中文名进行新闻和信息搜索，以获得更准确的中文资讯。

如果需要补充新闻、政策或事件信息来增强分析，请主动使用工具检索。"""
        else:
            tool_instruction = """

你可以使用以下工具来帮助分析：
- get_current_time: 获取当前时间，了解市场状态
- search_company_news: 搜索公司最新新闻
- search_web: 搜索公司信息、行业分析等
- get_stock_data_comprehensive: 获取股票完整数据（价格+财务+基本面），一次调用即可，A 股含股东户数、业绩预告、行业、概念
- calculate_technical_indicators: 计算技术指标（MA、RSI、MACD、布林带）

分析原则：
1. 收集信息：
   - 优先调用 get_stock_data_comprehensive 获取完整数据，无需再单独获取价格和财务。
   - 如需技术指标，再调用 calculate_technical_indicators。
   - 【关键】对于中国股票（A股/港股），请先使用 search_web 搜索代码对应的中文简称（如 "0700.HK 中文名"），再用中文名搜索新闻和深度分析。
2. 综合多维度数据进行分析
3. 给出明确的投资建议（买入/持有/卖出）和理由
4. 提示风险点"""
        
        return base_prompt + tool_instruction
    
    def _run_agent_loop(self, system_prompt: str, user_prompt: str, tools: list, max_iterations: int = 10) -> str:
        """
        使用 bind_tools + 循环实现 ReAct Agent（稳定接口，不依赖任何 Agent 工厂函数）
        
        Args:
            system_prompt: 系统提示词
            user_prompt: 用户输入
            tools: 工具列表
            max_iterations: 最大迭代次数
        
        Returns:
            最终响应内容
        """
        llm = self._get_llm()
        
        # 将工具绑定到 LLM
        llm_with_tools = llm.bind_tools(tools)
        
        # 构建工具字典（用于执行）
        tool_map = {t.name: t for t in tools}
        
        # 初始化消息列表
        full_system_prompt = self._build_system_prompt(system_prompt, tools)
        messages = [
            SystemMessage(content=full_system_prompt),
            HumanMessage(content=user_prompt),
        ]
        
        # ReAct 循环
        for _ in range(max_iterations):
            # 调用 LLM
            response = llm_with_tools.invoke(messages)
            messages.append(response)
            
            # 检查是否有工具调用
            if not response.tool_calls:
                # 没有工具调用，返回最终响应
                return response.content
            
            # 执行工具调用
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                
                if tool_name in tool_map:
                    try:
                        result = tool_map[tool_name].invoke(tool_args)
                    except Exception as e:
                        result = f"工具执行错误: {str(e)}"
                else:
                    result = f"未知工具: {tool_name}"
                
                # 添加工具结果消息
                messages.append(ToolMessage(
                    content=str(result),
                    tool_call_id=tool_call["id"],
                ))
        
        # 达到最大迭代，返回当前响应
        return messages[-1].content if hasattr(messages[-1], 'content') else "分析完成"
    
    def recursive_call(self, user_prompt):
        self.dialog.append({"role": "user", "content": user_prompt})
        response = self.client.chat.completions.create(
            model = self.model_type, 
            messages = self.dialog,
            stream = False
        )
        response_content = response.choices[0].message.content
        self.dialog.append({"role": "assistant", "content": response_content})
        return response_content
    
    def single_call(self, user_prompt):
        response = self.client.chat.completions.create(
            model = self.model_type,
            messages = [{"role": "user", "content": user_prompt}],
            stream = False
        )
        response_content = response.choices[0].message.content
        return response_content
    
    def agent_call(
        self, 
        user_prompt: str, 
        injection_prompt: str = None,
        tools_mode: str = "full",
        enable_debate: bool = False
    ) -> str:
        """
        使用 LangChain Agent 进行股票分析。
        
        Args:
            user_prompt: 用户的分析请求/问题
            injection_prompt: 注入的完整 prompt（包含角色定义+预处理数据+任务说明）
                            如果提供，将作为 Agent 的 System Prompt
            tools_mode: 工具模式
                - "full": 使用全部工具（默认，适合独立调用）
                - "search_only": 仅使用搜索工具（适合已有预处理数据的场景）
            enable_debate: 是否启用多轮辩论模式（牛熊双方辩论）
        
        Returns:
            分析结果
        """
        # 确定系统提示词
        if injection_prompt:
            system_prompt = injection_prompt
        else:
            system_prompt = """你是一个专业的股票分析师 AI Agent，擅长基本面分析和技术分析。
请用中文回答，分析要有条理，结论要明确。"""
        
        # 确定工具集
        tools = SEARCH_ONLY_TOOLS if tools_mode == "search_only" else FULL_TOOLS
        
        if enable_debate:
            return self._debate_analysis(user_prompt, system_prompt, tools)
        
        # 使用 Agent 循环执行
        response_content = self._run_agent_loop(system_prompt, user_prompt, tools)
        
        # 更新对话历史
        self._chat_history.append(HumanMessage(content=user_prompt))
        self._chat_history.append(AIMessage(content=response_content))
        
        return response_content
    
    def _debate_analysis(self, user_prompt: str, system_prompt: str, tools: list) -> str:
        """
        多轮辩论分析模式：牛方（看多）和熊方（看空）进行辩论，最后给出综合结论。
        
        Args:
            user_prompt: 用户的分析请求
            system_prompt: 系统提示词
            tools: 工具列表
        """
        # 首先收集基础数据
        data_collection_prompt = f"""请针对以下请求收集必要的数据（使用工具获取价格、财务、新闻等信息），但暂时不要给出投资建议：
        
{user_prompt}

请只收集和整理数据，不要分析。"""
        
        collected_data = self._run_agent_loop(system_prompt, data_collection_prompt, tools)
        
        # 牛方分析
        bull_prompt = f"""基于以下收集的数据，请你扮演【牛方分析师】，从看多的角度分析：

收集的数据：
{collected_data}

原始问题：{user_prompt}

请从以下角度论证为什么应该【买入/看多】：
1. 基本面优势
2. 技术面利好信号
3. 市场情绪和新闻面利好
4. 潜在上涨空间

注意：你是牛方，要尽可能找到看多的理由，但也要基于事实。"""
        
        bull_analysis = self._run_agent_loop(system_prompt, bull_prompt, tools)
        
        # 熊方分析
        bear_prompt = f"""基于以下收集的数据，请你扮演【熊方分析师】，从看空的角度分析：

收集的数据：
{collected_data}

原始问题：{user_prompt}

请从以下角度论证为什么应该【卖出/观望/看空】：
1. 基本面风险
2. 技术面利空信号
3. 市场情绪和新闻面风险
4. 潜在下跌风险

注意：你是熊方，要尽可能找到看空的理由，但也要基于事实。"""
        
        bear_analysis = self._run_agent_loop(system_prompt, bear_prompt, tools)
        
        # 综合裁决
        judge_prompt = f"""你是一位资深的投资顾问，现在需要综合牛熊双方的观点，给出最终投资建议。

原始问题：{user_prompt}

【牛方观点】：
{bull_analysis}

【熊方观点】：
{bear_analysis}

请综合以上双方观点，给出：
1. 双方论点的评估（哪些有道理，哪些证据不足）
2. 最终投资建议（明确买入/持有/卖出）
3. 建议的仓位比例
4. 止盈止损建议
5. 需要关注的风险点

请给出客观、平衡、可执行的投资建议。"""
        
        judge_analysis = self._run_agent_loop(system_prompt, judge_prompt, tools)
        final_result = f"""
# 📊 股票分析报告（辩论模式）

## 🐂 牛方观点（看多）
{bull_analysis}

---

## 🐻 熊方观点（看空）
{bear_analysis}

---

## ⚖️ 综合裁决
{judge_analysis}
"""
        return final_result
    
    def clear_agent_history(self):
        """清除 Agent 对话历史"""
        self._chat_history = []

    def __call__(
        self, 
        user_prompt, 
        agent_mode=True, 
        injection_prompt=None,
        tools_mode="full",
        enable_debate=True
    ):
        if agent_mode:
            return self.agent_call(
                user_prompt, 
                injection_prompt=injection_prompt,
                tools_mode=tools_mode,
                enable_debate=enable_debate
            )
        else:
            return self.single_call(user_prompt)


if __name__ == "__main__":
    
    deepseek = DeepSeekAPI()

    print('Token Test OK!')
    
    # 测试 Agent 辩论模式
    # response = deepseek("分析一下 Tesla 公司 TSLA 的股票，给出投资建议", agent_mode=True, enable_debate=True)
    # print(response)

    # response = deepseek("分析 腾讯 0700.HK 是否值得投资", agent_mode=True, enable_debate=False)
    # print(response)

    response = deepseek("分析一下 A股股票603090，给出投资建议", agent_mode=True, enable_debate=True)
    print(response)
