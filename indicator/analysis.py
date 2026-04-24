"""
AI股票分析模块 - 使用DeepSeek进行股票技术分析
基于agent/log.txt中的指标分析模式，提供短线分析、建仓建议和买卖点
"""
import pytz
import yfinance as yf
import pandas as pd
import numpy as np
import os
import json
import hashlib
import threading
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from agent.deepseek import DeepSeekAPI

# 缓存配置
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'analysis_cache')
CACHE_EXPIRE_HOURS = 24  # 缓存过期时间（小时）
CACHE_FORMAT_VERSION = 3

_symbol_lock_registry: Dict[str, threading.Lock] = {}
_symbol_lock_registry_guard = threading.Lock()


def _get_symbol_lock(symbol: str) -> threading.Lock:
    with _symbol_lock_registry_guard:
        if symbol not in _symbol_lock_registry:
            _symbol_lock_registry[symbol] = threading.Lock()
        return _symbol_lock_registry[symbol]


def empty_refined_info() -> Dict[str, Any]:
    return {
        'min_buy_price': None,
        'max_buy_price': None,
        'buy_time': None,
        'target_price': None,
        'stop_loss': None,
        'win_rate': None,
        'refined_text': '',
    }


def infer_market_from_symbol(symbol: str) -> str:
    if symbol.endswith('.HK') or symbol.endswith('.SS') or symbol.endswith('.SZ'):
        return 'HKA'
    return 'US'


def compress_summary_with_ai(full_text: str, symbol: str, market: str) -> str:
    """
    由 full_analysis 经模型压缩得到 summary_analysis。
    禁止在本函数内按字符数截断；失败时返回空字符串。
    """
    if not full_text or not str(full_text).strip():
        return ''
    sym_line = f"标的代码: {symbol}\n" if symbol else ""
    prompt = f"""{sym_line}请将下面「完整技术分析报告」改写为更短的执行摘要，保留：多空/观望结论、关键价位与数字、风险提示。
要求：
- 必须通读并概括全文语义，禁止只做首尾截取、复制前若干字或机械截断。
- 篇幅明显短于原文，可用小标题或列表。
- 保持与原文一致的标的与数据含义。

——完整报告——
{full_text}
"""
    try:
        deepseek = DeepSeekAPI(
            system_prompt="你是摘要助手，只输出压缩后的中文摘要正文，不要客套开场白。",
            model_type="deepseek-chat",
        )
        out = deepseek(prompt, agent_mode=False, enable_debate=False)
        return (out or "").strip()
    except Exception as e:
        print(f"⚠️ AI 压缩摘要失败: {e}")
        return ""


def _price_deviation_too_large(price_value: float, live_price: float, tolerance: float = 0.2) -> bool:
    if live_price is None or live_price <= 0 or price_value is None or price_value <= 0:
        return False
    lower = live_price * (1 - tolerance)
    upper = live_price * (1 + tolerance)
    return price_value < lower or price_value > upper


def _legacy_analysis_text_dirty(analysis_text: str, current_price: Optional[float]) -> bool:
    """Heuristic dirty-cache detection on analysis body (legacy + new)."""
    if not analysis_text:
        return False
    price_patterns = [
        r'当前价格[：:]\s*\$?([\d.]+)',
        r'当前价格\$([\d.]+)',
        r'当前价[：:]\s*\$?([\d.]+)',
        r'当前价格([\d.]+)',
    ]
    suspicious_patterns = [
        r'EMA\(20\)[=：:]\s*\$?([\d.]+)',
        r'EMA\(50\)[=：:]\s*\$?([\d.]+)',
        r'买入价格区间[：:]\s*\$?([\d.]+)\s*[-~到至 ]+\s*\$?([\d.]+)',
        r'买入区间[：:]\s*\$?([\d.]+)\s*[-~到至 ]+\s*\$?([\d.]+)',
        r'目标价位?[：:]\s*\$?([\d.]+)',
        r'止损位?[：:]\s*\$?([\d.]+)',
        r'第一止盈[：:]\s*\$?([\d.]+)',
    ]
    for pattern in price_patterns:
        m = re.search(pattern, analysis_text)
        if m:
            try:
                cached_price = float(m.group(1))
                if cached_price < 5:
                    return True
                if _price_deviation_too_large(cached_price, current_price):
                    return True
            except (TypeError, ValueError):
                pass
            break
    for pattern in suspicious_patterns:
        m = re.search(pattern, analysis_text)
        if not m:
            continue
        try:
            prices = [float(g) for g in m.groups() if g is not None]
            for p in prices:
                if p < 5:
                    return True
                if _price_deviation_too_large(p, current_price):
                    return True
        except (TypeError, ValueError):
            pass
    return False


def normalize_cache_entry(raw: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    """Normalize cache entry to current schema (full / summary / refine 三份正文)."""
    if not raw:
        return {}
    out = dict(raw)
    out.pop('analysis', None)
    out['symbol'] = raw.get('symbol') or symbol
    fa = (out.get('full_analysis') or '') or ''
    out['full_analysis'] = fa
    if not out.get('summary_analysis'):
        out['summary_analysis'] = ''
    ri = out.get('refined_info')
    if not isinstance(ri, dict):
        out['refined_info'] = empty_refined_info()
    else:
        base = empty_refined_info()
        base.update(ri)
        out['refined_info'] = base
    ra_s = str(out.get('refine_analysis') or '').strip()
    out['refine_analysis'] = ra_s
    out['refined_info']['refined_text'] = ''
    st = out.get('status')
    if not st:
        out['status'] = 'completed' if fa.strip() else 'failed'
    if 'cache_version' not in out:
        out['cache_version'] = 1
    if 'market' not in out:
        out['market'] = infer_market_from_symbol(symbol)
    if 'data_hash' not in out:
        out['data_hash'] = ''
    if 'current_price' not in out or out['current_price'] is None:
        out['current_price'] = 0.0
    if 'is_dirty' not in out:
        out['is_dirty'] = False
    if 'error' not in out:
        out['error'] = ''
    if 'timestamp' not in out:
        out['timestamp'] = datetime.now().isoformat()
    return out


def read_analysis_cache_entry(symbol: str) -> Optional[Dict[str, Any]]:
    """Read cache file for symbol; normalize; does not validate freshness."""
    try:
        cache_file = get_cache_file_path(symbol)
        if not os.path.exists(cache_file):
            return None
        with open(cache_file, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        if raw.get('symbol') and raw.get('symbol') != symbol:
            print(f"⚠️ {symbol} 磁盘缓存 symbol 不匹配({raw.get('symbol')})，拒绝读取")
            return None
        return normalize_cache_entry(raw, symbol)
    except Exception as e:
        print(f"⚠️ 读取 {symbol} 分析缓存失败: {e}")
        return None


def validate_cache_for_use(
    entry: Dict[str, Any],
    symbol: str,
    data_hash: str,
    current_price: float,
) -> bool:
    """Strict cache hit: symbol, completed, hash, price, not dirty."""
    if not entry:
        return False
    if entry.get('symbol') != symbol:
        return False
    if entry.get('status') != 'completed':
        return False
    if entry.get('data_hash') != data_hash:
        return False
    if entry.get('is_dirty'):
        return False
    cached_price = entry.get('current_price')
    try:
        cp = float(cached_price) if cached_price is not None else None
    except (TypeError, ValueError):
        cp = None
    if cp is not None and cp > 0 and current_price is not None and current_price > 0:
        if _price_deviation_too_large(cp, float(current_price)):
            return False
    text = (entry.get('full_analysis') or '')
    if _legacy_analysis_text_dirty(text, current_price):
        return False
    cache_time = entry.get('timestamp')
    if cache_time:
        try:
            ct = datetime.fromisoformat(cache_time)
            if datetime.now() - ct > timedelta(hours=CACHE_EXPIRE_HOURS):
                return False
        except Exception:
            pass
    return True


def get_analysis_context(symbol: str, period_days: int = 250) -> Optional[Dict[str, Any]]:
    """Fetch OHLCV, hash, live price, inferred market for one symbol."""
    daily_data, hourly_data = get_stock_data(symbol, period_days)
    if daily_data is None or daily_data.empty:
        return None
    data_hash = calculate_data_hash(symbol, daily_data, hourly_data)
    current_price = float(_last_row_scalar(_ensure_1d_series(daily_data['Close'])))
    return {
        'symbol': symbol,
        'daily_data': daily_data,
        'hourly_data': hourly_data,
        'data_hash': data_hash,
        'current_price': current_price,
        'market': infer_market_from_symbol(symbol),
    }


def try_load_completed_analysis_for_symbol(symbol: str, period_days: int = 250) -> Optional[Dict[str, Any]]:
    """Read-only: return completed cache entry if hash/price/dirty checks pass (no AI)."""
    ctx = get_analysis_context(symbol, period_days)
    if not ctx:
        return None
    entry = read_analysis_cache_entry(symbol)
    if not entry:
        return None
    if validate_cache_for_use(
        entry, symbol, ctx['data_hash'], ctx['current_price'],
    ):
        return entry
    return None


def save_analysis_cache_entry(symbol: str, entry: Dict[str, Any]) -> None:
    """Atomic write per symbol; caller should hold symbol lock for consistency."""
    try:
        ensure_cache_dir()
        out = dict(entry)
        out['symbol'] = symbol
        out['cache_version'] = CACHE_FORMAT_VERSION
        out.pop('analysis', None)
        fa = out.get('full_analysis') or ''
        out['full_analysis'] = fa
        if 'refine_analysis' not in out:
            out['refine_analysis'] = ''
        if 'refined_info' not in out or not isinstance(out.get('refined_info'), dict):
            out['refined_info'] = empty_refined_info()

        to_save = dict(out)
        to_save.pop('analysis', None)
        ri = to_save.get('refined_info') if isinstance(to_save.get('refined_info'), dict) else {}
        ri_save = dict(ri) if ri else {}
        ri_save['refined_text'] = ''
        to_save['refined_info'] = ri_save
        rtop = (to_save.get('refine_analysis') or '').strip()
        if not rtop:
            to_save.pop('refine_analysis', None)

        cache_file = get_cache_file_path(symbol)
        tmp = cache_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(to_save, f, ensure_ascii=False, indent=2)
        os.replace(tmp, cache_file)
    except Exception as e:
        print(f"⚠️ 保存 {symbol} 分析缓存失败: {e}")


def _base_ai_result(
    symbol: str,
    market: str,
    status: str,
    data_hash: str,
    current_price: float,
) -> Dict[str, Any]:
    return {
        'cache_version': CACHE_FORMAT_VERSION,
        'symbol': symbol,
        'market': market,
        'status': status,
        'data_hash': data_hash,
        'current_price': float(current_price) if current_price is not None else 0.0,
        'is_dirty': False,
        'error': '',
        'timestamp': datetime.now().isoformat(),
        'full_analysis': '',
        'summary_analysis': '',
        'refine_analysis': '',
        'refined_info': empty_refined_info(),
    }


def ai_result_to_html_row(
    symbol: str,
    price: float,
    score_buy: float,
    entry: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Single stock row for HTML report; rejects symbol mismatch."""
    row = {
        'symbol': symbol,
        'score_buy': score_buy,
        'price': price,
        'ai_result': None,
    }
    if not entry:
        row['ai_result'] = {
            **_base_ai_result(symbol, infer_market_from_symbol(symbol), 'missing', '', price),
            'status': 'missing',
            'error': '无分析任务结果或缓存',
        }
        return row
    if entry.get('symbol') != symbol:
        row['ai_result'] = {
            **_base_ai_result(symbol, entry.get('market') or infer_market_from_symbol(symbol), 'missing', '', price),
            'status': 'missing',
            'error': 'AI 结果 symbol 与当前股票不一致，已拒绝展示',
        }
        return row
    row['ai_result'] = entry
    return row


def build_ai_analysis_results_for_html(buy_signal_stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """HTML 阶段只合并内存结果与磁盘 completed 缓存，不调用 AI。"""
    out: List[Dict[str, Any]] = []
    for stock in buy_signal_stocks:
        sym = stock.get('symbol') or ''
        if not sym:
            continue
        entry = stock.get('_ai_result')
        if (not entry) or (entry.get('symbol') != sym):
            entry = try_load_completed_analysis_for_symbol(sym)
        out.append(
            ai_result_to_html_row(
                sym,
                float(stock.get('price', 0) or 0),
                float(stock.get('score_buy', 0) or 0),
                entry,
            )
        )
    return out


def ensure_cache_dir():
    """确保缓存目录存在"""
    os.makedirs(CACHE_DIR, exist_ok=True)

def get_cache_file_path(symbol: str) -> str:
    """获取缓存文件路径"""
    return os.path.join(CACHE_DIR, f"{symbol}_analysis.json")


def _last_row_scalar(series_or_col):
    """
    取最后一行标量。yfinance 在部分标的下 Close 最后一格可能非严格标量，.item() 会抛 ValueError。
    """
    last = series_or_col.iloc[-1]
    if isinstance(last, pd.Series):
        return last.iloc[0]
    if isinstance(last, np.ndarray):
        return np.asarray(last).reshape(-1)[0]
    if hasattr(last, 'item'):
        try:
            return last.item()
        except ValueError:
            return np.asarray(last).reshape(-1)[0]
    return last


def _ensure_1d_series(x: Any) -> pd.Series:
    """yfinance 列可能是单列 DataFrame 或 Series，统一成 Series。"""
    if isinstance(x, pd.DataFrame):
        return x.iloc[:, 0]
    return x


_YF_DOWNLOAD_LOCK = threading.Lock()


def _normalize_yf_dataframe(df: Optional[pd.DataFrame], symbol: str) -> pd.DataFrame:
    """
    串行 download 仍可能因 MultiIndex 列混用导致错列；按请求 symbol 取列并 copy，避免与其它 ticker 混淆。
    """
    if df is None:
        return df
    out = df.copy()
    if out.empty:
        return out
    sym_u = str(symbol).strip().upper()
    if isinstance(out.columns, pd.MultiIndex):
        try:
            level = out.columns.get_level_values(-1)
            tickers = [str(x).upper() for x in level.unique()]
        except Exception:
            tickers = []
        if sym_u in tickers:
            out = out.xs(sym_u, axis=1, level=-1, drop_level=True)
        elif len(tickers) == 1:
            out = out.xs(out.columns.levels[-1][0], axis=1, level=-1, drop_level=True)
        else:
            first = out.columns.levels[-1][0]
            out = out.xs(first, axis=1, level=-1, drop_level=True)
            if str(first).upper() != sym_u:
                print(f"⚠️ yfinance 列 ticker 与请求不一致: 请求={sym_u} 实际={first}")
    return out


def analysis_text_contains_symbol(symbol: str, text: str) -> bool:
    """主分析/提炼输入须显式包含标的，避免模型套用其它股票上下文。"""
    if not symbol or not text:
        return False
    s = str(symbol).strip()
    if s in text:
        return True
    su, tu = s.upper(), text.upper()
    if su in tu:
        return True
    for suf in ('.SS', '.SZ', '.HK'):
        if su.endswith(suf):
            base = su[: -len(suf)]
            if base and base in tu:
                return True
            break
    return False


def calculate_data_hash(symbol: str, daily_data: pd.DataFrame, hourly_data: pd.DataFrame) -> str:
    """计算数据哈希值，用于检测数据是否变化"""
    # 带版本号，历史缓存格式有问题时可强制失效
    hash_version = "v2"

    # 使用最新的价格和关键序列计算哈希，避免仅靠最新一根数据命中脏缓存
    latest_daily = {
        'price': round(float(_last_row_scalar(_ensure_1d_series(daily_data['Close']))), 4)
        if not daily_data.empty
        else 0,
        'volume': int(_last_row_scalar(_ensure_1d_series(daily_data['Volume'])))
        if not daily_data.empty
        else 0,
        'recent_close': [
            round(float(x), 4)
            for x in _ensure_1d_series(daily_data['Close']).tail(5).tolist()
        ]
        if not daily_data.empty
        else [],
    }
    
    latest_hourly = {}
    if hourly_data is not None and not hourly_data.empty:
        latest_hourly = {
            'price': round(float(_last_row_scalar(_ensure_1d_series(hourly_data['Close']))), 4),
            'date': hourly_data.index[-1].strftime('%Y-%m-%d %H:%M'),
            'recent_close': [
                round(float(x), 4)
                for x in _ensure_1d_series(hourly_data['Close']).tail(5).tolist()
            ],
        }
    
    data_str = f"{hash_version}_{symbol}_{json.dumps(latest_daily, sort_keys=True)}_{json.dumps(latest_hourly, sort_keys=True)}"
    return hashlib.md5(data_str.encode()).hexdigest()

def load_analysis_cache(symbol: str, current_price: float = None) -> Optional[Dict]:
    """兼容旧逻辑：读盘并做过期与文案价格启发式校验；data_hash 由调用方自行比对。"""
    try:
        entry = read_analysis_cache_entry(symbol)
        if not entry:
            return None
        ts = entry.get('timestamp')
        if ts:
            try:
                if datetime.now() - datetime.fromisoformat(ts) > timedelta(hours=CACHE_EXPIRE_HOURS):
                    return None
            except Exception:
                pass
        text = entry.get('full_analysis') or ''
        if _legacy_analysis_text_dirty(text, current_price):
            return None
        return entry
    except Exception as e:
        print(f"⚠️ 加载 {symbol} 分析缓存失败: {e}")
        return None


def save_analysis_cache(symbol: str, data_hash: str, full_report: str):
    """写入 completed 缓存：full + AI 摘要；无 refine（refine_analysis 为空）。"""
    market = infer_market_from_symbol(symbol)
    daily_data, hourly_data = get_stock_data(symbol, 250)
    cp = 0.0
    if daily_data is not None and not daily_data.empty:
        cp = float(_last_row_scalar(_ensure_1d_series(daily_data['Close'])))
    summary = compress_summary_with_ai(full_report, symbol, market)
    entry = _base_ai_result(symbol, market, 'completed', data_hash, cp)
    entry['full_analysis'] = full_report
    entry['summary_analysis'] = summary
    entry['refined_info'] = empty_refined_info()
    with _get_symbol_lock(symbol):
        save_analysis_cache_entry(symbol, entry)

def clean_expired_cache():
    """清理过期的缓存文件"""
    try:
        ensure_cache_dir()
        current_time = datetime.now()
        cleaned_count = 0
        
        for filename in os.listdir(CACHE_DIR):
            if filename.endswith('_analysis.json'):
                file_path = os.path.join(CACHE_DIR, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                    
                    cache_time = datetime.fromisoformat(cache_data['timestamp'])
                    if current_time - cache_time > timedelta(hours=CACHE_EXPIRE_HOURS):
                        os.remove(file_path)
                        cleaned_count += 1
                        print(f"🗑️ 清理过期缓存: {filename}")
                
                except Exception as e:
                    print(f"⚠️ 清理缓存文件失败 {filename}: {e}")
        
        if cleaned_count > 0:
            print(f"✅ 已清理 {cleaned_count} 个过期缓存文件")
    
    except Exception as e:
        print(f"⚠️ 清理缓存目录失败: {e}")

def calculate_technical_indicators(data: pd.DataFrame) -> Dict:
    """
    计算技术指标
    
    Args:
        data: 包含OHLCV数据的DataFrame
        
    Returns:
        dict: 包含各种技术指标的字典
    """
    indicators = {}
    
    # RSI计算
    def calculate_rsi(prices, period=14):
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    # MACD计算
    def calculate_macd(prices, fast=12, slow=26, signal=9):
        exp1 = prices.ewm(span=fast, adjust=False).mean()
        exp2 = prices.ewm(span=slow, adjust=False).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=signal, adjust=False).mean()
        macd = (dif - dea) * 2
        return dif, dea, macd
    
    # EMA计算
    def calculate_ema(prices, period):
        return prices.ewm(span=period, adjust=False).mean()
    
    # ATR计算
    def calculate_atr(high, low, close, period=14):
        high_low = high - low
        high_close = np.abs(high - close.shift())
        low_close = np.abs(low - close.shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        return true_range.rolling(period).mean()
    
    # 计算各种指标
    indicators['rsi_7'] = calculate_rsi(data['Close'], 7)
    indicators['rsi_14'] = calculate_rsi(data['Close'], 14)
    
    dif, dea, macd = calculate_macd(data['Close'])
    indicators['macd_dif'] = dif
    indicators['macd_dea'] = dea
    indicators['macd'] = macd
    
    indicators['ema_20'] = calculate_ema(data['Close'], 20)
    indicators['ema_50'] = calculate_ema(data['Close'], 50)
    indicators['ema_12'] = calculate_ema(data['Close'], 12)
    indicators['ema_144'] = calculate_ema(data['Close'], 144)
    
    indicators['atr_3'] = calculate_atr(data['High'], data['Low'], data['Close'], 3)
    indicators['atr_14'] = calculate_atr(data['High'], data['Low'], data['Close'], 14)
    
    # 成交量指标
    indicators['volume_avg'] = data['Volume'].rolling(20).mean()
    indicators['volume_ratio'] = data['Volume'] / indicators['volume_avg']
    
    return indicators


def get_stock_data(symbol: str, period_days: int = 250) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    获取股票数据（日K线和小时级数据）
    
    Args:
        symbol: 股票代码
        period_days: 获取数据的天数
        
    Returns:
        tuple: (日K线数据, 小时级数据)
    """
    with _YF_DOWNLOAD_LOCK:
        daily_raw = yf.download(
            symbol, period=f"{period_days}d", interval="1d", auto_adjust=True, progress=False
        )
        hourly_raw = yf.download(
            symbol, period="30d", interval="1h", auto_adjust=True, progress=False
        )
    daily_data = _normalize_yf_dataframe(daily_raw, symbol)
    hourly_data = _normalize_yf_dataframe(hourly_raw, symbol)
    return daily_data, hourly_data


# 美股短线分析师角色定义
SYSTEM_PROMPT_US = """你是一位专业的股票技术分析师。
用户通过成交量、RSI、MACD情况筛选出了一些短线操作机会。
用户通常会在信号触发后的夜盘/盘前买入，并在下一个盘中时段卖出。特殊情况下，用户会额外持有2-3天。
用户对于此类投机仓位不会超过5%，风险在可控范围内。
你的任务是基于用户提供的数据，判断该短线操作机会的成功率，并给出买入/卖出、止盈/止损的价格区间。
并提醒用户：什么情况下可以继续看涨并继续持有？或是当日卖出止盈？"""

# 港A股短线分析师角色定义
SYSTEM_PROMPT_HKA = """你是一位专业的股票技术分析师。
用户通过成交量、RSI、MACD情况筛选出了一些短线操作机会。
用户通常会在信号触发后的第二天买入，并在下一天卖出。特殊情况下，用户会额外持有2-3天。
用户对于此类投机仓位不会超过5%，风险在可控范围内。
你的任务是基于用户提供的数据，判断该短线操作机会的成功率，并给出买入/卖出、止盈/止损的价格区间。
并提醒用户：什么情况下可以继续看涨并继续持有？或是当日卖出止盈？"""


def call_deepseek_api_US(prompt: str) -> str:
    """美股分析 - 使用 Agent 模式，注入预处理数据，仅使用搜索工具补充新闻"""
    deepseek = DeepSeekAPI(model_type="deepseek-chat")
    # 将角色定义和预处理数据作为 injection_prompt 注入
    # Agent 会使用搜索工具补充新闻、政策等信息
    injection = f"{SYSTEM_PROMPT_US}\n\n{prompt}"
    return deepseek.agent_call(
        user_prompt="请基于以上数据进行分析，并适当搜索最新新闻和政策来增强分析",
        injection_prompt=injection,
        tools_mode="search_only"
    )

def call_deepseek_api_HKA(prompt: str) -> str:
    """港A股分析 - 使用 Agent 模式，注入预处理数据，仅使用搜索工具补充新闻"""
    deepseek = DeepSeekAPI(model_type="deepseek-chat")
    # 将角色定义和预处理数据作为 injection_prompt 注入
    injection = f"{SYSTEM_PROMPT_HKA}\n\n{prompt}"
    return deepseek.agent_call(
        user_prompt="请基于以上数据进行分析，并适当搜索最新新闻和政策来增强分析",
        injection_prompt=injection,
        tools_mode="search_only"
    )

def call_deepseek_api(prompt: str, market: str = "US") -> str:
    """
    调用DeepSeek API分析股票
    
    Args:
        prompt: AI分析提示词
        market: 市场类型（"US"或"HKA"）
        
    Returns:
        str: AI分析结果
    """
    if market == "US":
        return call_deepseek_api_US(prompt)
    elif market == "HKA":
        return call_deepseek_api_HKA(prompt)
    else:
        raise ValueError(f"Invalid market: {market}. Must be 'US' or 'HKA'")


def refine_ai_analysis(
    ai_output: str,
    market: str = "US",
    current_price: float = None,
    symbol: str = "",
) -> Tuple[Dict[str, Any], str]:
    """
    将AI分析结果再喂给AI进行提炼，提取关键信息
    
    Args:
        ai_output: AI的原始分析结果
        market: 市场类型（"US"或"HKA"）
        current_price: 当前价格，用于对提炼结果做价格一致性校验
        
    Returns:
        (refined_info, refine_analysis): refined_info 仅含解析字段；refine_analysis 为模型输出的结构化正文。
    """
    if symbol and not analysis_text_contains_symbol(symbol, ai_output or ''):
        return empty_refined_info(), ''

    sym_line = f"标的代码: {symbol}\n" if symbol else ""
    # 构建提炼提示词 - 要求AI提取更多字段并使用固定格式
    refine_prompt = f"""
{sym_line}请只根据下面「报告正文」提炼，所有价格必须与该标的正文一致；不要使用其它股票、示例或模板中的数字。

请从以下股票分析报告中，提炼出最关键的交易信息。如果有多空双方博弈，请你只保留综合裁决的结果。

{ai_output}

请严格按照以下格式输出（每行一个，如果信息不存在则填写"无"）：
买入区间: [最低价]-[最高价]
买入时间: [具体时间建议]
目标价位: [价格]
止损位: [价格]
预估胜率: [百分比数字]%

注意：
- 价格只填数字，不要带货币符号
- 买入区间用"-"连接最低和最高价格，如 "10.5-11.2"
- 胜率用百分比数字，如 "65%"
- 如果原文没有明确给出某项信息，填写"无"

最后用一句话总结核心建议。
"""
    
    # 调用简易AI进行提炼（使用chat模型，更快更便宜）
    def _extract_structured_fields(refined_output: str) -> dict:
        import re

        result = {
            'min_buy_price': None,
            'max_buy_price': None,
            'buy_time': None,
            'target_price': None,
            'stop_loss': None,
            'win_rate': None,
            'refined_text': '',
        }
        
        # ===== 提取买入区间 =====
        # 支持格式：**理想买入区间**: $31.50 - $32.00、买入区间: 10.5-11.2 等
        buy_range_patterns = [
            # **理想买入区间**: $31.50 - $32.00（Markdown格式）
            r'\*{0,2}理想买入区间\*{0,2}[：:]\s*\$?([\d.]+)\s*[-~到至 ]+\s*\$?([\d.]+)',
            # **买入区间**: $31.50 - $32.00
            r'\*{0,2}买入区间\*{0,2}[：:]\s*\$?([\d.]+)\s*[-~到至 ]+\s*\$?([\d.]+)',
            # 买入价格区间: $10.5-$11.2
            r'\*{0,2}买入价格?区间\*{0,2}[：:]\s*\$?([\d.]+)\s*[-~到至 ]+\s*\$?([\d.]+)',
            # 建议买入: 10.5-11.2
            r'\*{0,2}建议买入\*{0,2}[：:]\s*\$?([\d.]+)\s*[-~到至 ]+\s*\$?([\d.]+)',
            # 买入点: 10.5-11.2
            r'\*{0,2}买入点\*{0,2}[：:]\s*\$?([\d.]+)\s*[-~到至 ]+\s*\$?([\d.]+)',
            # 最佳买入区间: $31.50-$31.80
            r'\*{0,2}最佳买入区间\*{0,2}[：:]\s*\$?([\d.]+)\s*[-~到至 ]+\s*\$?([\d.]+)',
        ]
        
        for pattern in buy_range_patterns:
            match = re.search(pattern, refined_output, re.IGNORECASE)
            if match:
                try:
                    result['min_buy_price'] = float(match.group(1))
                    result['max_buy_price'] = float(match.group(2))
                    break
                except:
                    pass
        
        # 如果没找到区间，尝试单独找最高/最低买入价
        if result['max_buy_price'] is None:
            max_price_patterns = [
                r'\*{0,2}最高买入价\*{0,2}[：:]\s*\$?([\d.]+)',
                r'\*{0,2}买入上限\*{0,2}[：:]\s*\$?([\d.]+)',
                r'\*{0,2}上限\*{0,2}[：:]\s*\$?([\d.]+)',
                # 激进买入: 当前价$32.40附近
                r'\*{0,2}激进买入\*{0,2}[：:].{0,10}\$?([\d.]+)',
            ]
            for pattern in max_price_patterns:
                match = re.search(pattern, refined_output, re.IGNORECASE)
                if match:
                    try:
                        result['max_buy_price'] = float(match.group(1))
                        break
                    except:
                        pass
        
        if result['min_buy_price'] is None:
            min_price_patterns = [
                r'\*{0,2}最低买入价\*{0,2}[：:]\s*\$?([\d.]+)',
                r'\*{0,2}买入下限\*{0,2}[：:]\s*\$?([\d.]+)',
                r'\*{0,2}下限\*{0,2}[：:]\s*\$?([\d.]+)',
            ]
            for pattern in min_price_patterns:
                match = re.search(pattern, refined_output, re.IGNORECASE)
                if match:
                    try:
                        result['min_buy_price'] = float(match.group(1))
                        break
                    except:
                        pass
        
        # ===== 提取买入时间 =====
        # 支持格式：**买入时间**: 建议明日开盘后30分钟内观察
        buy_time_patterns = [
            r'\*{0,2}买入时间\*{0,2}[：:]\s*([^\n*]+)',
            r'\*{0,2}建仓时机\*{0,2}[：:]\s*([^\n*]+)',
            r'\*{0,2}入场时间\*{0,2}[：:]\s*([^\n*]+)',
            r'\*{0,2}建仓时机建议\*{0,2}[：:]*\s*([^\n*]+)',
            # 建议明日/今日/开盘等
            r'建议\s*(明日|今日|周[一二三四五六日]).{0,30}(开盘|观察|买入)',
        ]
        
        for pattern in buy_time_patterns:
            match = re.search(pattern, refined_output, re.IGNORECASE)
            if match:
                buy_time = match.group(1).strip() if match.lastindex else match.group(0).strip()
                # 过滤掉"无"或空值，以及只包含标点的情况
                if buy_time and buy_time != '无' and len(buy_time) > 2 and any(c.isalnum() for c in buy_time):
                    # 中文括号转英文括号，减少字符长度
                    buy_time = buy_time.replace('（', '(').replace('）', ')')
                    result['buy_time'] = buy_time[:50]  # 限制长度
                    break
        
        # ===== 提取目标价/止盈位 =====
        # 支持格式：**短线目标1**: $33.50 - $34.00、**第一止盈**: $33.50
        target_patterns = [
            # 短线目标1: $33.50 - $34.00（取第一个价格）
            r'\*{0,2}短线目标1?\*{0,2}[：:]\s*\$?([\d.]+)',
            r'\*{0,2}第一止盈\*{0,2}[：:]\s*\$?([\d.]+)',
            r'\*{0,2}第一目标\*{0,2}[：:]\s*\$?([\d.]+)',
            r'\*{0,2}目标价位?\*{0,2}[：:]\s*\$?([\d.]+)',
            r'\*{0,2}止盈位?\*{0,2}[：:]\s*\$?([\d.]+)',
            r'\*{0,2}目标\*{0,2}[：:]\s*\$?([\d.]+)',
        ]
        
        for pattern in target_patterns:
            match = re.search(pattern, refined_output, re.IGNORECASE)
            if match:
                try:
                    price = float(match.group(1))
                    if price > 0:
                        result['target_price'] = price
                        break
                except:
                    pass
        
        # ===== 提取止损位 =====
        # 支持格式：**严格止损**: $31.00、**止损位**: $30.00
        stop_loss_patterns = [
            r'\*{0,2}严格止损\*{0,2}[：:]\s*\$?([\d.]+)',
            r'\*{0,2}止损位?\*{0,2}[：:]\s*\$?([\d.]+)',
            r'\*{0,2}止损\*{0,2}[：:]\s*\$?([\d.]+)',
            r'\*{0,2}止损价\*{0,2}[：:]\s*\$?([\d.]+)',
            r'\*{0,2}风险控制\*{0,2}[：:]\s*\$?([\d.]+)',
            r'\*{0,2}宽松止损\*{0,2}[：:]\s*\$?([\d.]+)',
        ]
        
        for pattern in stop_loss_patterns:
            match = re.search(pattern, refined_output, re.IGNORECASE)
            if match:
                try:
                    price = float(match.group(1))
                    if price > 0:
                        result['stop_loss'] = price
                        break
                except:
                    pass
        
        # ===== 提取胜率 =====
        # 支持格式：**约60-65%**、预估胜率: 65%、胜率约65%
        rate_patterns = [
            # **约60-65%**（区间形式，取中间值）
            r'\*{0,2}约?([\d.]+)\s*[-~到至]\s*([\d.]+)\s*%\*{0,2}',
            # 预估胜率: 65%
            r'\*{0,2}预估.{0,3}胜率\*{0,2}[：:]*\s*约?([\d.]+)\s*%',
            r'\*{0,2}胜率\*{0,2}[：:]\s*约?([\d.]+)\s*%',
            r'\*{0,2}成功率\*{0,2}[：:]\s*约?([\d.]+)\s*%',
            r'\*{0,2}概率\*{0,2}[：:]\s*约?([\d.]+)\s*%',
            r'约?([\d.]+)\s*%\s*的?胜率',
            r'胜率.{0,5}约?([\d.]+)\s*%',
            # 约60-65%（不带星号）
            r'约([\d.]+)\s*[-~到至]\s*([\d.]+)\s*%',
        ]
        
        for pattern in rate_patterns:
            match = re.search(pattern, refined_output, re.IGNORECASE)
            if match:
                try:
                    # 检查是否是区间形式（有两个捕获组）
                    if match.lastindex and match.lastindex >= 2:
                        # 区间形式，取中间值
                        rate1 = float(match.group(1))
                        rate2 = float(match.group(2))
                        rate = (rate1 + rate2) / 2
                    else:
                        rate = float(match.group(1))
                    
                    # 如果是百分比形式（>1），转换为小数
                    if rate > 1:
                        rate = rate / 100
                    # 确保在0-1之间
                    if 0 <= rate <= 1:
                        result['win_rate'] = rate
                        break
                except:
                    pass
        
        # 如果没有找到百分比形式，尝试找小数形式
        if result['win_rate'] is None:
            decimal_patterns = [
                r'\*{0,2}胜率\*{0,2}[：:]\s*([01]\.\d+)',
                r'\*{0,2}概率\*{0,2}[：:]\s*([01]\.\d+)',
            ]
            for pattern in decimal_patterns:
                match = re.search(pattern, refined_output, re.IGNORECASE)
                if match:
                    try:
                        result['win_rate'] = float(match.group(1))
                        break
                    except:
                        pass
        
        return result

    def _is_price_result_valid(result: dict, current_price: float) -> bool:
        prices_to_check = [
            result.get('min_buy_price'),
            result.get('max_buy_price'),
            result.get('target_price'),
            result.get('stop_loss'),
        ]
        prices_to_check = [p for p in prices_to_check if p is not None and p > 0]
        if not prices_to_check:
            return True
        if current_price is None or current_price <= 0:
            # 有价位却无现价锚点，视为无效（避免未校验数字直接落库）
            return False

        lower_bound = current_price * 0.8
        upper_bound = current_price * 1.2
        for p in prices_to_check:
            if p < lower_bound or p > upper_bound:
                return False
        return True

    try:
        deepseek = DeepSeekAPI(
            system_prompt="你是一个信息提炼助手，擅长从长文本中提取关键交易信息，并按固定格式输出。",
            model_type="deepseek-chat"
        )

        max_attempts = 2
        final_result = None
        last_refined_output = ''
        for attempt in range(max_attempts):
            refined_output = deepseek(refine_prompt, agent_mode=False, enable_debate=False)
            last_refined_output = refined_output or ''
            result = _extract_structured_fields(refined_output)

            extracted_count = sum(1 for v in [result['min_buy_price'], result['max_buy_price'], 
                                              result['buy_time'], result['target_price'], 
                                              result['stop_loss'], result['win_rate']] if v is not None)
            print(f"📊 AI提炼完成: 成功提取 {extracted_count}/6 个字段")

            if _is_price_result_valid(result, current_price):
                final_result = result
                break

            print(f"⚠️ AI提炼价格校验失败: current_price={current_price}, attempt={attempt + 1}/{max_attempts}")
            final_result = result

        if final_result is not None and not _is_price_result_valid(final_result, current_price):
            print(f"⚠️ AI提炼两次均价格异常，清空全部AI提炼字段，仅保留非AI原生指标: current_price={current_price}")
            final_result.update({
                'min_buy_price': None,
                'max_buy_price': None,
                'buy_time': None,
                'target_price': None,
                'stop_loss': None,
                'win_rate': None,
            })

        if final_result is None:
            return empty_refined_info(), ''
        final_result['refined_text'] = ''
        merged = {**empty_refined_info(), **final_result}
        return merged, (last_refined_output or '').strip()

    except Exception as e:
        print(f"⚠️  AI提炼失败: {e}")
        return empty_refined_info(), ''

def safe_get_value(series, default=None):
    """
    安全地从pandas Series获取最后一个值
    
    Args:
        series: pandas Series
        default: 默认值
        
    Returns:
        标量值或默认值
    """
    if series is None or len(series) == 0:
        return default

    series = _ensure_1d_series(series)
    value = series.iloc[-1]
    
    # 确保返回标量值
    if hasattr(value, 'item'):
        value = value.item()
    
    # 检查是否为NaN
    if pd.isna(value):
        return default
    
    return value


def format_analysis_data(symbol: str, daily_data: pd.DataFrame, hourly_data: pd.DataFrame, 
                        daily_indicators: Dict, hourly_indicators: Dict) -> str:
    """
    格式化分析数据为DeepSeek可理解的格式
    
    Args:
        symbol: 股票代码
        daily_data: 日K线数据
        hourly_data: 小时级数据
        daily_indicators: 日线技术指标
        hourly_indicators: 小时级技术指标
        
    Returns:
        str: 格式化的分析数据
    """
    # 获取当前价格和成交量（确保是标量）
    current_price = float(_last_row_scalar(_ensure_1d_series(daily_data['Close'])))
    current_volume = int(_last_row_scalar(_ensure_1d_series(daily_data['Volume'])))
    
    # 获取日线指标值（确保都是标量）
    latest_daily = {
        'price': current_price,
        'volume': current_volume,
        'rsi_7': safe_get_value(daily_indicators['rsi_7']),
        'rsi_14': safe_get_value(daily_indicators['rsi_14']),
        'macd_dif': safe_get_value(daily_indicators['macd_dif']),
        'macd_dea': safe_get_value(daily_indicators['macd_dea']),
        'macd': safe_get_value(daily_indicators['macd']),
        'ema_20': safe_get_value(daily_indicators['ema_20']),
        'ema_50': safe_get_value(daily_indicators['ema_50']),
        'atr_14': safe_get_value(daily_indicators['atr_14']),
        'volume_ratio': safe_get_value(daily_indicators['volume_ratio']),
    }
    
    # 获取小时级数据
    if hourly_data is not None and not hourly_data.empty and hourly_indicators:
        latest_hourly = {
            'price': float(_last_row_scalar(_ensure_1d_series(hourly_data['Close']))),
            'rsi_7': safe_get_value(hourly_indicators['rsi_7']),
            'macd': safe_get_value(hourly_indicators['macd']),
            'ema_20': safe_get_value(hourly_indicators['ema_20']),
        }
    else:
        latest_hourly = {
            'price': current_price,
            'rsi_7': None,
            'macd': None,
            'ema_20': None,
        }
    
    # 获取最近的价格序列（确保是列表）
    recent_prices = _ensure_1d_series(daily_data['Close']).tail(24).tolist()
    recent_volumes = _ensure_1d_series(daily_data['Volume']).tail(24).tolist()
    
    daily_tail_long = 24
    hourly_tail_long = 24
    
    # 获取日线技术指标的24个数据点
    daily_rsi_7_series = _ensure_1d_series(daily_indicators['rsi_7']).tail(daily_tail_long).tolist()
    daily_rsi_14_series = _ensure_1d_series(daily_indicators['rsi_14']).tail(daily_tail_long).tolist()
    daily_macd_dif_series = _ensure_1d_series(daily_indicators['macd_dif']).tail(daily_tail_long).tolist()
    daily_macd_dea_series = _ensure_1d_series(daily_indicators['macd_dea']).tail(daily_tail_long).tolist()
    daily_macd_series = _ensure_1d_series(daily_indicators['macd']).tail(daily_tail_long).tolist()
    daily_ema_20_series = _ensure_1d_series(daily_indicators['ema_20']).tail(daily_tail_long).tolist()
    daily_ema_50_series = _ensure_1d_series(daily_indicators['ema_50']).tail(daily_tail_long).tolist()
    
    # 获取小时级技术指标的24个数据点
    hourly_rsi_7_series = []
    hourly_macd_series = []
    hourly_ema_20_series = []
    
    if hourly_data is not None and not hourly_data.empty and hourly_indicators:
        hourly_rsi_7_series = _ensure_1d_series(hourly_indicators['rsi_7']).tail(hourly_tail_long).tolist()
        hourly_macd_series = _ensure_1d_series(hourly_indicators['macd']).tail(hourly_tail_long).tolist()
        hourly_ema_20_series = _ensure_1d_series(hourly_indicators['ema_20']).tail(hourly_tail_long).tolist()
    
    # 格式化数值显示
    def format_value(value, format_str=".2f"):
        if value is None:
            return 'N/A'
        return f"{value:{format_str}}"
    
    def format_series(series, format_str=".2f"):
        """格式化数据序列"""
        if not series:
            return 'N/A'
        return [f"{v:{format_str}}" if v is not None and not pd.isna(v) else 'N/A' for v in series]
    
    analysis_text = f"""
=== 数据绑定标的（模型须与此一致）===
标的: {symbol} | 日线末收={current_price:.4f} | 末量={current_volume}

股票代码: {symbol}
当前价格: ${current_price:.2f}
当前成交量: {current_volume:,}

=== 日线技术指标 ===
RSI(7) 最近{daily_tail_long}天: {format_series(daily_rsi_7_series)}
RSI(14) 最近{daily_tail_long}天: {format_series(daily_rsi_14_series)}
MACD DIF 最近{daily_tail_long}天: {format_series(daily_macd_dif_series)}
MACD DEA 最近{daily_tail_long}天: {format_series(daily_macd_dea_series)}
MACD 最近{daily_tail_long}天: {format_series(daily_macd_series)}
EMA(20) 最近{daily_tail_long}天: {format_series(daily_ema_20_series)}
EMA(50) 最近{daily_tail_long}天: {format_series(daily_ema_50_series)}
ATR(14): {format_value(latest_daily['atr_14'])}
成交量比率: {format_value(latest_daily['volume_ratio'])} （最后1日成交量 / 过去20日平均成交量）

=== 小时级技术指标 ===
当前价格: ${latest_hourly['price']:.2f}
RSI(7) 最近{hourly_tail_long}小时: {format_series(hourly_rsi_7_series)}
MACD 最近{hourly_tail_long}小时: {format_series(hourly_macd_series)}
EMA(20) 最近{hourly_tail_long}小时: {format_series(hourly_ema_20_series)}

=== 最近价格趋势 ===
最近{daily_tail_long}天收盘价: {[f"${p:.2f}" for p in recent_prices]}
最近{daily_tail_long}天成交量: {[f"{v:,}" for v in recent_volumes]}

=== 趋势分析 ===
"""
    
    # 添加趋势分析
    if len(recent_prices) >= 5:
        price_change = (recent_prices[-1] - recent_prices[-5]) / recent_prices[-5] * 100
        analysis_text += f"5日价格变化: {price_change:+.2f}%\n"
    
    if latest_daily['ema_20'] is not None and latest_daily['ema_50'] is not None:
        if latest_daily['ema_20'] > latest_daily['ema_50']:
            analysis_text += "EMA(20) > EMA(50): 短期趋势向上\n"
        else:
            analysis_text += "EMA(20) < EMA(50): 短期趋势向下\n"
    
    if latest_daily['rsi_7'] is not None:
        if latest_daily['rsi_7'] > 70:
            analysis_text += "RSI(7) > 70: 可能超买\n"
        elif latest_daily['rsi_7'] < 30:
            analysis_text += "RSI(7) < 30: 可能超卖\n"
        else:
            analysis_text += "RSI(7) 在正常区间\n"
    
    if latest_daily['macd'] is not None:
        if latest_daily['macd'] > 0:
            analysis_text += "MACD > 0: 多头信号\n"
        else:
            analysis_text += "MACD < 0: 空头信号\n"
    
    return analysis_text

def get_time_info(symbol: str) -> str:
    if symbol.endswith(".HK") or symbol.endswith(".SS") or symbol.endswith(".SZ"):
        now_hk = datetime.now(pytz.timezone('Asia/Hong_Kong'))
        time_info = f"""
        === 当前港A股交易时间 ===
        {now_hk.strftime('%Y-%m-%d %H:%M:%S')} {now_hk.tzname()} {now_hk.strftime('%A')}
        """
    else:
        now_et = datetime.now(pytz.timezone('US/Eastern'))
        time_info = f"""
        === 当前美股交易时间 ===
        {now_et.strftime('%Y-%m-%d %H:%M:%S')} {now_et.tzname()} {now_et.strftime('%A')}
        """
    return time_info

def get_stock_type(symbol: str) -> str:
    if symbol.endswith(".HK") or symbol.endswith(".SS") or symbol.endswith(".SZ"):
        return "港A股"
    else:
        return "美股"


def build_or_load_ai_result(symbol: str, period_days: int = 250, market: str = None) -> Dict[str, Any]:
    """
    统一入口：按 symbol 加锁生成/读取三层 AI 结果并写入磁盘缓存。
    缓存命中条件：validate_cache_for_use（含 data_hash、current_price、非脏、completed）。
    """
    if market is None:
        market = "HKA" if symbol.endswith(('.HK', '.SS', '.SZ')) else "US"

    ctx = get_analysis_context(symbol, period_days)
    if not ctx:
        err = _base_ai_result(symbol, market, 'failed', '', 0.0)
        err['error'] = f'无法获取 {symbol} 的股票数据'
        return err

    daily_data = ctx['daily_data']
    hourly_data = ctx['hourly_data']
    data_hash = ctx['data_hash']
    current_price = float(ctx['current_price'])

    snap = read_analysis_cache_entry(symbol)
    if snap and validate_cache_for_use(snap, symbol, data_hash, current_price):
        return snap

    with _get_symbol_lock(symbol):
        snap = read_analysis_cache_entry(symbol)
        if snap and validate_cache_for_use(snap, symbol, data_hash, current_price):
            return snap

        pending = _base_ai_result(symbol, market, 'pending', data_hash, current_price)
        save_analysis_cache_entry(symbol, pending)

        try:
            daily_indicators = calculate_technical_indicators(daily_data)
            hourly_indicators = (
                calculate_technical_indicators(hourly_data)
                if hourly_data is not None and not hourly_data.empty
                else {}
            )
            analysis_data = format_analysis_data(
                symbol, daily_data, hourly_data, daily_indicators, hourly_indicators
            )
            time_info = get_time_info(symbol)
            stock_type = get_stock_type(symbol)

            if market == "HKA":
                market_instruction = """
请用专业、简洁的语言进行分析，重点关注技术指标的信号强度和可靠性。
注意港A股市场特点：交易时间为上午9:30-12:00，下午13:00-16:00（港股），请充分考虑市场时间和流动性特点。
"""
            else:
                market_instruction = """
请用专业、简洁的语言进行分析，重点关注技术指标的信号强度和可靠性，并充分考虑当前时间因素对美股交易的影响。
接口允许的话，你也可以适当检索一些新闻、政策、事件并分析其对美股交易的影响。
"""

            prompt = f"""
【硬性要求】正文中标的代码 {symbol} 须至少出现两次；文中 RSI、MACD、成交量等数值必须与下方「格式化数据」一致，禁止套用其它股票或示例行情。

你是一位专业的股票技术分析师，请基于以下技术指标数据和当前市场时间，对{stock_type} {symbol} 进行深度分析：

{time_info}

{analysis_data}

请提供以下分析内容：

1. **短线技术分析**：
   - 当前技术面强弱评估
   - 主要技术指标解读
   - 短期趋势判断
   - 结合当前时间（周几、交易时段）的技术面分析

2. **建仓建议**：
   - 是否适合建仓（买入/卖出/观望）
   - 建仓时机建议（考虑当前是周几，是否接近周末等）
   - 风险等级评估

3. **买卖点建议**：
   - 具体买入价格区间和时间
   - 具体卖出价格区间和时间
   - 止损位建议
   - 止盈位建议
   - 给出预估的短线胜率

4. **风险提示**：
   - 主要风险因素
   - 注意事项

{market_instruction}
"""
            ai_full = call_deepseek_api(prompt, market=market)
            if not analysis_text_contains_symbol(symbol, ai_full or ''):
                skip_refine = _base_ai_result(symbol, market, 'partial', data_hash, current_price)
                skip_refine['full_analysis'] = ai_full or ''
                skip_refine['summary_analysis'] = compress_summary_with_ai(ai_full or '', symbol, market)
                skip_refine['refined_info'] = empty_refined_info()
                skip_refine['refine_analysis'] = ''
                skip_refine['error'] = '主分析正文未包含标的代码，已跳过提炼'
                save_analysis_cache_entry(symbol, skip_refine)
                return skip_refine

            summary = compress_summary_with_ai(ai_full, symbol, market)

            partial_e = _base_ai_result(symbol, market, 'partial', data_hash, current_price)
            partial_e['full_analysis'] = ai_full
            partial_e['summary_analysis'] = summary
            partial_e['refined_info'] = empty_refined_info()
            save_analysis_cache_entry(symbol, partial_e)

            try:
                refined, refine_raw = refine_ai_analysis(
                    ai_full, market=market, current_price=current_price, symbol=symbol
                )
                refined = {**empty_refined_info(), **refined}
            except Exception as ref_ex:
                partial_bad = _base_ai_result(symbol, market, 'partial', data_hash, current_price)
                partial_bad['full_analysis'] = ai_full
                partial_bad['summary_analysis'] = summary
                partial_bad['refined_info'] = empty_refined_info()
                partial_bad['refine_analysis'] = ''
                partial_bad['error'] = f'refine_failed: {ref_ex}'
                save_analysis_cache_entry(symbol, partial_bad)
                return partial_bad

            done = _base_ai_result(symbol, market, 'completed', data_hash, current_price)
            done['full_analysis'] = ai_full
            done['summary_analysis'] = summary
            done['refined_info'] = refined
            done['refine_analysis'] = refine_raw
            save_analysis_cache_entry(symbol, done)
            return done
        except Exception as ex:
            failed = _base_ai_result(symbol, market, 'failed', data_hash, current_price)
            failed['error'] = str(ex)
            save_analysis_cache_entry(symbol, failed)
            return failed


def analyze_stock_with_ai(symbol: str, period_days: int = 250, market: str = None) -> str:
    """
    使用AI分析股票；内部走 build_or_load_ai_result，返回全文便于兼容旧调用。
    """
    r = build_or_load_ai_result(symbol, period_days=period_days, market=market)
    text = (r.get('full_analysis') or '').strip()
    st = r.get('status')
    if st in ('completed', 'partial') and text:
        return r.get('full_analysis') or ''
    if st == 'failed':
        return f"❌ 无法完成 {symbol} 分析: {r.get('error', 'unknown')}"
    return text or f"❌ {r.get('error', '分析失败')}"


def main(symbol):
    """
    主函数 - 示例用法
    """
    result = analyze_stock_with_ai(symbol)  # 使用agent/deepseek.py中的DeepSeekAPI
    print(f"\n=== {symbol} AI分析结果 ===")
    print(result)


if __name__ == "__main__":
    
    import argparse
    
    # 获取命令行参数
    parser = argparse.ArgumentParser(description='股票分析')
    parser.add_argument('symbol', type=str, help='股票代码')
    args = parser.parse_args()
    symbol = args.symbol
    main(symbol)
