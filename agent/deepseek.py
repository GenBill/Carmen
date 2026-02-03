from openai import OpenAI
from datetime import datetime
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
def get_stock_price(symbol: str, period: str = "1mo") -> str:
    """获取股票的历史价格数据和当前价格。
    
    Args:
        symbol: 股票代码，如 "AAPL", "0700.HK", "600519.SS"
        period: 时间范围，可选值: "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"
    """
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period=period)
        
        if hist.empty:
            return f"未找到股票 {symbol} 的数据，请检查代码是否正确"
        
        current_price = hist['Close'].iloc[-1]
        open_price = hist['Open'].iloc[-1]
        high = hist['High'].iloc[-1]
        low = hist['Low'].iloc[-1]
        volume = hist['Volume'].iloc[-1]
        
        # 计算涨跌幅
        if len(hist) > 1:
            prev_close = hist['Close'].iloc[-2]
            change = ((current_price - prev_close) / prev_close) * 100
            change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
        else:
            change_str = "N/A"
        
        # 计算周期内表现
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
        
        return result
    except Exception as e:
        return f"获取股票数据失败: {str(e)}"


@tool
def get_stock_financials(symbol: str) -> str:
    """获取公司的财务数据，包括市值、PE、EPS等关键指标。
    
    Args:
        symbol: 股票代码，如 "AAPL", "0700.HK", "600519.SS"
    """
    try:
        stock = yf.Ticker(symbol)
        info = stock.info
        
        if not info or 'symbol' not in info:
            return f"未找到 {symbol} 的财务数据"
        
        result = f"**{symbol} - {info.get('longName', 'N/A')} 财务数据**\n\n"
        result += f"行业: {info.get('industry', 'N/A')}\n"
        result += f"市值: ${info.get('marketCap', 0):,.0f}\n"
        result += f"企业价值: ${info.get('enterpriseValue', 0):,.0f}\n"
        result += f"市盈率 (PE): {info.get('trailingPE', 'N/A')}\n"
        result += f"远期市盈率: {info.get('forwardPE', 'N/A')}\n"
        result += f"市净率 (PB): {info.get('priceToBook', 'N/A')}\n"
        result += f"每股收益 (EPS): ${info.get('trailingEps', 'N/A')}\n"
        result += f"股息率: {info.get('dividendYield', 0) * 100 if info.get('dividendYield') else 0:.2f}%\n"
        result += f"52周最高: ${info.get('fiftyTwoWeekHigh', 'N/A')}\n"
        result += f"52周最低: ${info.get('fiftyTwoWeekLow', 'N/A')}\n"
        result += f"50日均线: ${info.get('fiftyDayAverage', 'N/A')}\n"
        result += f"200日均线: ${info.get('twoHundredDayAverage', 'N/A')}\n"
        result += f"\n**业务简介:**\n{info.get('longBusinessSummary', 'N/A')[:500]}...\n"
        
        return result
    except Exception as e:
        return f"获取财务数据失败: {str(e)}"


@tool
def calculate_technical_indicators(symbol: str, period: str = "3mo") -> str:
    """计算股票的技术指标，包括 MA、RSI、MACD、布林带等。
    
    Args:
        symbol: 股票代码
        period: 数据周期，建议至少 "3mo" 以获得足够数据计算指标
    """
    try:
        stock = yf.Ticker(symbol)
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
        
        # MACD 解读
        macd_signal = "金叉/多头 🟢" if macd.iloc[-1] > signal.iloc[-1] else "死叉/空头 🔴"
        
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
FULL_TOOLS = [
    get_current_time,
    search_company_news,
    search_web,
    get_stock_price,
    get_stock_financials,
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

如果需要补充新闻、政策或事件信息来增强分析，请主动使用工具检索。"""
        else:
            tool_instruction = """

你可以使用以下工具来帮助分析：
- get_current_time: 获取当前时间，了解市场状态
- search_company_news: 搜索公司最新新闻
- search_web: 搜索公司信息、行业分析等
- get_stock_price: 获取股票价格数据
- get_stock_financials: 获取公司财务数据
- calculate_technical_indicators: 计算技术指标

分析原则：
1. 先收集信息（新闻、价格、财务数据、技术指标）
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
    
    # 测试 Agent 模式
    response = deepseek("分析一下 Tesla 公司 TSLA 的股票，给出投资建议", agent_mode=True, enable_debate=True)
    print(response)
    
    # 测试辩论模式
    response = deepseek("分析 腾讯 0700.HK 是否值得投资", agent_mode=True, enable_debate=False)
    print(response)
