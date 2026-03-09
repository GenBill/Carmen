"""
碗口反弹策略 + B1完美图形匹配

严格复刻 https://github.com/Dzy-HW-XD/a-share-quant-selector

模块来源:
  - bowl_rebound_indicator()  ← strategy/bowl_rebound.py + utils/technical.py
  - PatternFeatureExtractor   ← strategy/pattern_feature_extractor.py
  - PatternMatcher            ← strategy/pattern_matcher.py (含 DTW)
  - B1PatternLibrary          ← strategy/pattern_library.py + strategy/pattern_config.py
"""

import pandas as pd
import numpy as np
import json
from pathlib import Path

try:
    from scipy.spatial.distance import euclidean as _scipy_euclidean
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

    def _scipy_euclidean(a, b):
        return float(np.sqrt(np.sum((np.asarray(a) - np.asarray(b)) ** 2)))

try:
    from fastdtw import fastdtw as _fastdtw
    _HAS_FASTDTW = True
except ImportError:
    _HAS_FASTDTW = False


# ============================================================
# B1 完美图形配置  (strategy/pattern_config.py)
# ============================================================

B1_PERFECT_CASES = [
    {"id": "case_001", "name": "华纳药厂", "code": "688799",
     "yf_symbol": "688799.SS", "breakout_date": "2025-05-12",
     "lookback_days": 25, "tags": ["科创板", "医药"],
     "description": "杯型整理+缩量+J值低位"},
    {"id": "case_002", "name": "宁波韵升", "code": "600366",
     "yf_symbol": "600366.SS", "breakout_date": "2025-08-06",
     "lookback_days": 25, "tags": ["主板", "稀土永磁"],
     "description": "回落短期趋势线+量能平稳+J值中位"},
    {"id": "case_003", "name": "微芯生物", "code": "688321",
     "yf_symbol": "688321.SS", "breakout_date": "2025-06-20",
     "lookback_days": 25, "tags": ["科创板", "医药"],
     "description": "平台整理+缩量后放量+J值低位"},
    {"id": "case_004", "name": "方正科技", "code": "600601",
     "yf_symbol": "600601.SS", "breakout_date": "2025-07-23",
     "lookback_days": 25, "tags": ["主板", "科技"],
     "description": "靠近多空线+量能平稳+J值中位"},
    {"id": "case_005", "name": "澄天伟业", "code": "300689",
     "yf_symbol": "300689.SZ", "breakout_date": "2025-07-15",
     "lookback_days": 25, "tags": ["创业板", "芯片"],
     "description": "持续缩量+价格震荡+J值低位"},
    {"id": "case_006", "name": "国轩高科", "code": "002074",
     "yf_symbol": "002074.SZ", "breakout_date": "2025-08-04",
     "lookback_days": 25, "tags": ["中小板", "新能源"],
     "description": "靠近短期趋势线+量能平稳+J值低位"},
    {"id": "case_007", "name": "野马电池", "code": "605378",
     "yf_symbol": "605378.SS", "breakout_date": "2025-08-01",
     "lookback_days": 25, "tags": ["主板", "电池"],
     "description": "持续缩量+J值深度低位+趋势下行"},
    {"id": "case_008", "name": "光电股份", "code": "600184",
     "yf_symbol": "600184.SS", "breakout_date": "2025-07-10",
     "lookback_days": 25, "tags": ["主板", "军工"],
     "description": "缩量后放量+J值低位+趋势上行"},
    {"id": "case_009", "name": "新瀚新材", "code": "301076",
     "yf_symbol": "301076.SZ", "breakout_date": "2025-08-01",
     "lookback_days": 25, "tags": ["创业板", "化工"],
     "description": "缩量后放量+价格接近短期趋势线+J值中位"},
    {"id": "case_010", "name": "昂利康", "code": "002940",
     "yf_symbol": "002940.SZ", "breakout_date": "2025-07-11",
     "lookback_days": 25, "tags": ["中小板", "医药"],
     "description": "价格接近短期趋势线+缩量+顶部未放量"},
]

SIMILARITY_WEIGHTS = {
    "trend_structure": 0.30,
    "kdj_state":       0.20,
    "volume_pattern":  0.25,
    "price_shape":     0.25,
}

MATCH_TOLERANCES = {
    "trend_ratio":  0.10,
    "price_bias":   10,
    "trend_spread": 10,
    "j_value":      30,
    "drawdown":     15,
}

MIN_SIMILARITY_SCORE = 60.0
DEFAULT_LOOKBACK_DAYS = 25

_BOWL_PARAMS = {
    'N': 4, 'M': 15, 'J_VAL': 30,
    'duokong_pct': 3, 'short_pct': 2,
    'M1': 14, 'M2': 28, 'M3': 57, 'M4': 114,
}


# ============================================================
# 技术指标  (utils/technical.py — 升序数据版本)
# ============================================================

def _ma(series, n):
    """简单移动平均 — 升序数据直接 rolling"""
    return series.rolling(window=n, min_periods=1).mean()


def _ema(series, n):
    """指数移动平均 — 升序数据直接 ewm"""
    return series.ewm(span=n, adjust=False, min_periods=1).mean()


def _kdj(df, n=9, m1=3, m2=3):
    """
    KDJ(9,3,3) — 通达信 SMA 递推实现
    严格复刻 utils/technical.py 中的 KDJ 函数

    公式:
      RSV = (CLOSE - LLV(LOW,N)) / (HHV(HIGH,N) - LLV(LOW,N)) * 100
      K   = SMA(RSV, M1, 1)   即 K = (RSV + K' * (M1-1)) / M1
      D   = SMA(K,   M2, 1)   即 D = (K   + D' * (M2-1)) / M2
      J   = 3K - 2D

    初始: K[0]=50, D[0]=50; 前 n-1 期 RSV=50
    """
    close = df['close'].values
    low = df['low'].values
    high = df['high'].values
    length = len(df)

    rsv = np.full(length, 50.0)
    for i in range(length):
        start = max(0, i - n + 1)
        lo = np.min(low[start:i + 1])
        hi = np.max(high[start:i + 1])
        rng = hi - lo
        if i >= n - 1 and rng > 0:
            rsv[i] = (close[i] - lo) / rng * 100

    K = np.empty(length)
    D = np.empty(length)
    K[0] = 50.0
    D[0] = 50.0
    for i in range(1, length):
        K[i] = (rsv[i] * 1 + K[i - 1] * (m1 - 1)) / m1
        D[i] = (K[i]   * 1 + D[i - 1] * (m2 - 1)) / m2

    J = 3 * K - 2 * D
    idx = df.index
    return pd.Series(K, index=idx), pd.Series(D, index=idx), pd.Series(J, index=idx)


def _zhixing_trend(df, m1=14, m2=28, m3=57, m4=114):
    """
    知行短期趋势线 = EMA(EMA(CLOSE,10),10)
    知行多空线     = (MA(C,m1) + MA(C,m2) + MA(C,m3) + MA(C,m4)) / 4
    """
    short_term = _ema(_ema(df['close'], 10), 10)
    bull_bear = (_ma(df['close'], m1) + _ma(df['close'], m2)
                 + _ma(df['close'], m3) + _ma(df['close'], m4)) / 4
    return short_term, bull_bear


# ============================================================
# 数据转换
# ============================================================

def _prepare_df(stock_data):
    """将 Carmen stock_data dict 转为内部升序、小写列名 DataFrame"""
    hist = stock_data.get('hist')
    if hist is None or len(hist) == 0:
        return None
    df = hist.copy()
    if len(df) > 1 and df.index[0] > df.index[-1]:
        df = df.iloc[::-1]
    df['date'] = df.index
    rename = {}
    for c in df.columns:
        lc = c.lower()
        if lc != c and c != 'date':
            rename[c] = lc
    if rename:
        df = df.rename(columns=rename)
    return df.reset_index(drop=True)


def _prepare_raw_hist(hist):
    """将原始 yfinance DataFrame 转为内部格式"""
    if hist is None or len(hist) == 0:
        return None
    df = hist.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    if len(df) > 1 and df.index[0] > df.index[-1]:
        df = df.iloc[::-1]
    df['date'] = df.index
    rename = {}
    for c in df.columns:
        lc = c.lower()
        if lc != c and c != 'date':
            rename[c] = lc
    if rename:
        df = df.rename(columns=rename)
    return df.reset_index(drop=True)


# ============================================================
# 碗口反弹过滤  (strategy/bowl_rebound.py)
# ============================================================

def bowl_rebound_indicator(stock_data):
    """
    碗口反弹选股过滤 — 严格复刻 strategy/bowl_rebound.py

    选股信号 = 异动 AND 趋势线在上 AND J值低位
               AND (回落碗中 OR 靠近多空线 OR 靠近短期趋势线)

    Returns:
        float — 0.0 (不满足) / 0.7 (靠近短期趋势线) /
                0.8 (靠近多空线) / 1.0 (回落碗中)
    """
    df = _prepare_df(stock_data)
    if df is None or len(df) < _BOWL_PARAMS['M4']:
        return 0.0

    short_trend, bull_bear = _zhixing_trend(
        df, _BOWL_PARAMS['M1'], _BOWL_PARAMS['M2'],
        _BOWL_PARAMS['M3'], _BOWL_PARAMS['M4'])
    _, _, J = _kdj(df)

    vol_ratio = df['volume'] / df['volume'].shift(1)
    key_candle = (vol_ratio >= _BOWL_PARAMS['N']) & (df['close'] > df['open'])

    i = len(df) - 1
    c  = df['close'].iloc[i]
    s  = short_trend.iloc[i]
    b  = bull_bear.iloc[i]
    jv = J.iloc[i]

    if pd.isna(s) or pd.isna(b) or pd.isna(jv):
        return 0.0

    # 条件1: 趋势线在上
    if s <= b:
        return 0.0

    # 条件2: J值低位
    if jv > _BOWL_PARAMS['J_VAL']:
        return 0.0

    # 条件3: M天内存在关键K线(放量阳线)
    if not key_candle.iloc[-_BOWL_PARAMS['M']:].any():
        return 0.0

    # 条件4: 位置分类 (优先级: 回落碗中 > 靠近多空线 > 靠近短期趋势线)
    dk = _BOWL_PARAMS['duokong_pct'] / 100
    st = _BOWL_PARAMS['short_pct'] / 100

    if c >= b and c <= s:
        return 1.0
    if c >= b * (1 - dk) and c <= b * (1 + dk):
        return 0.8
    if c >= s * (1 - st) and c <= s * (1 + st):
        return 0.7

    return 0.0


# ============================================================
# 特征提取  (strategy/pattern_feature_extractor.py)
# ============================================================

class PatternFeatureExtractor:
    """从股票数据提取 B1 完美图形特征"""

    def __init__(self, lookback_days=DEFAULT_LOOKBACK_DAYS):
        self.lookback_days = lookback_days

    def extract(self, df, lookback_days=None):
        """
        提取完整特征向量
        df: 升序 DataFrame (含 date/close/open/high/low/volume)
        """
        if df is None or df.empty or len(df) < 10:
            return self._empty()

        days = lookback_days or self.lookback_days
        window = df.tail(days).copy().reset_index(drop=True)

        short_trend, bull_bear = _zhixing_trend(window)
        window['short_term_trend'] = short_trend
        window['bull_bear_line'] = bull_bear

        K, D, J = _kdj(window)
        window['K'] = K
        window['D'] = D
        window['J'] = J

        return {
            "trend_structure": self._trend_features(window),
            "kdj_state":       self._kdj_features(window),
            "volume_pattern":  self._volume_features(window),
            "price_shape":     self._shape_features(window),
        }

    def extract_from_stock_data(self, stock_data, lookback_days=None):
        """便捷方法：从 Carmen stock_data dict 提取特征"""
        return self.extract(_prepare_df(stock_data), lookback_days)

    def _empty(self):
        return {"trend_structure": {}, "kdj_state": {},
                "volume_pattern": {}, "price_shape": {}}

    # ---- 1. 双线结构 (30%) ----

    def _trend_features(self, df):
        if len(df) < 5:
            return {}
        latest = df.iloc[-1]
        bb = latest['bull_bear_line']
        st = latest['short_term_trend']
        cl = latest['close']
        if bb == 0 or st == 0:
            return {}

        short_vs_bullbear = st / bb

        short_slope = ((df['short_term_trend'].iloc[-1]
                        / df['short_term_trend'].iloc[-5] - 1) * 100
                       if df['short_term_trend'].iloc[-5] != 0 else 0)
        bullbear_slope = ((df['bull_bear_line'].iloc[-1]
                           / df['bull_bear_line'].iloc[-5] - 1) * 100
                          if df['bull_bear_line'].iloc[-5] != 0 else 0)

        price_vs_short_pct = (cl - st) / st * 100
        price_vs_bullbear_pct = (cl - bb) / bb * 100
        is_in_bowl = bool(st > cl > bb)
        trend_spread_pct = (st - bb) / bb * 100

        avg_trend = (st + bb) / 2
        price_bias_pct = (cl - avg_trend) / avg_trend * 100 if avg_trend != 0 else 0

        return {
            "short_vs_bullbear":    round(float(short_vs_bullbear), 4),
            "short_slope":          round(float(short_slope), 4),
            "bullbear_slope":       round(float(bullbear_slope), 4),
            "price_vs_short_pct":   round(float(price_vs_short_pct), 4),
            "price_vs_bullbear_pct": round(float(price_vs_bullbear_pct), 4),
            "is_in_bowl":           is_in_bowl,
            "trend_spread_pct":     round(float(trend_spread_pct), 4),
            "price_bias_pct":       round(float(price_bias_pct), 4),
        }

    # ---- 2. KDJ 状态 (20%) ----

    def _kdj_features(self, df):
        if len(df) < 2 or 'J' not in df.columns:
            return {}
        latest = df.iloc[-1]
        j_values = df['J'].values

        j_val = float(latest['J']) if not pd.isna(latest['J']) else 50.0
        if j_val <= 20:
            j_position = "低位"
        elif j_val >= 80:
            j_position = "高位"
        else:
            j_position = "中位"

        if len(j_values) >= 5:
            x = np.arange(5)
            recent = j_values[-5:]
            j_trend = float(np.polyfit(x, recent, 1)[0]) if not np.isnan(recent).any() else 0
        else:
            j_trend = 0

        k_cross_d = False
        if len(df) >= 2 and not pd.isna(latest['K']) and not pd.isna(latest['D']):
            prev = df.iloc[-2]
            k_cross_d = bool((prev['K'] < prev['D']) and (latest['K'] > latest['D']))

        j_rebound = bool(j_values[-1] > j_values[-3]) if len(j_values) >= 3 else False

        return {
            "j_value":        round(j_val, 2),
            "j_position":     j_position,
            "j_trend":        round(j_trend, 4),
            "j_min_lookback": round(float(np.nanmin(j_values)), 2),
            "k_cross_d":      k_cross_d,
            "j_rebound":      j_rebound,
        }

    # ---- 3. 量能特征 (25%) ----

    def _volume_features(self, df):
        if 'volume' not in df.columns or len(df) < 5:
            return {}
        volumes = df['volume'].values.astype(float)

        if len(volumes) >= 20:
            recent_avg = np.mean(volumes[-10:])
            before_avg = np.mean(volumes[-20:-10])
            avg_volume_ratio = recent_avg / before_avg if before_avg > 0 else 1.0
        elif len(volumes) >= 10:
            recent_avg = np.mean(volumes[-10:])
            before_avg = np.mean(volumes[:-10]) if len(volumes) > 10 else recent_avg
            avg_volume_ratio = recent_avg / before_avg if before_avg > 0 else 1.0
        else:
            avg_volume_ratio = 1.0

        vol_ratios = []
        for i in range(1, min(len(volumes), 20)):
            if volumes[i - 1] > 0:
                vol_ratios.append(volumes[i] / volumes[i - 1])
        max_volume_ratio = max(vol_ratios) if vol_ratios else 1.0

        shrink_then_expand = self._detect_shrink_expand(volumes)

        key_candles = 0
        for i in range(1, len(df)):
            if (df['volume'].iloc[i] > df['volume'].iloc[i - 1] * 2
                    and df['close'].iloc[i] > df['open'].iloc[i]):
                key_candles += 1

        volume_trend = self._classify_volume_trend(volumes)

        return {
            "avg_volume_ratio":  round(float(avg_volume_ratio), 2),
            "max_volume_ratio":  round(float(max_volume_ratio), 2),
            "volume_trend":      volume_trend,
            "key_candles_count": int(key_candles),
            "shrink_then_expand": bool(shrink_then_expand),
        }

    def _detect_shrink_expand(self, volumes):
        if len(volumes) < 10:
            return False
        mid = len(volumes) // 2
        early_avg = np.mean(volumes[:mid])
        late_avg = np.mean(volumes[mid:])
        overall_avg = np.mean(volumes)
        return bool(late_avg > early_avg * 1.3 and early_avg < overall_avg * 0.9)

    def _classify_volume_trend(self, volumes):
        if len(volumes) < 5:
            return "unknown"
        x = np.arange(len(volumes))
        slope = np.polyfit(x, volumes, 1)[0]
        avg_vol = np.mean(volumes)
        slope_pct = slope / avg_vol * 100 if avg_vol > 0 else 0
        if slope_pct > 5:
            return "持续放量"
        elif slope_pct < -5:
            return "持续缩量"
        elif self._detect_shrink_expand(volumes):
            return "缩量后放量"
        else:
            return "量能平稳"

    # ---- 4. 价格形态 (25%) ----

    def _shape_features(self, df):
        if len(df) < 5:
            return {}
        closes = df['close'].values.astype(float)

        pmin, pmax = closes.min(), closes.max()
        normalized = ((closes - pmin) / (pmax - pmin)
                      if pmax > pmin else np.zeros_like(closes))

        peak = np.maximum.accumulate(closes)
        drawdown = (peak - closes) / peak
        max_drawdown = float(drawdown.max()) * 100

        breakout_strength = ((closes[-1] / closes[-2] - 1) * 100
                             if len(closes) >= 2 else 0)

        if len(closes) >= 2:
            returns = np.diff(closes) / closes[:-1]
            volatility = float(np.std(returns)) * 100
        else:
            volatility = 0

        consolidation_days = self._count_consolidation(closes)

        if closes[-1] > closes[0] * 1.05:
            overall_trend = "上升"
        elif closes[-1] < closes[0] * 0.95:
            overall_trend = "下降"
        else:
            overall_trend = "震荡"

        return {
            "normalized_curve":   normalized.tolist(),
            "max_drawdown":       round(max_drawdown, 2),
            "breakout_strength":  round(float(breakout_strength), 2),
            "volatility":         round(volatility, 4),
            "consolidation_days": int(consolidation_days),
            "overall_trend":      overall_trend,
        }

    def _count_consolidation(self, closes):
        if len(closes) < 5:
            return 0
        mx, mn = closes.max(), closes.min()
        if mx > 0 and (mx - mn) / mx < 0.10:
            return len(closes)
        max_days = current = 0
        for i in range(len(closes) - 5):
            w = closes[i:i + 5]
            wmax, wmin = w.max(), w.min()
            if wmax > 0 and (wmax - wmin) / wmax < 0.05:
                current += 1
                max_days = max(max_days, current)
            else:
                current = 0
        return max_days


# ============================================================
# 相似度匹配引擎  (strategy/pattern_matcher.py)
# ============================================================

class PatternMatcher:
    """B1 完美图形相似度匹配 — 支持 DTW"""

    def __init__(self, weights=None, tolerances=None):
        self.weights = weights or SIMILARITY_WEIGHTS
        self.tolerances = tolerances or MATCH_TOLERANCES

    def match(self, candidate, case):
        """计算候选 vs 案例的相似度 → {total_score (百分制), breakdown}"""
        if not candidate or not case:
            return {"total_score": 0.0, "breakdown": {}}

        scores = {}

        scores["trend_structure"] = (
            self._trend_sim(candidate["trend_structure"], case["trend_structure"])
            if candidate.get("trend_structure") and case.get("trend_structure")
            else 0.5)

        scores["kdj_state"] = (
            self._kdj_sim(candidate["kdj_state"], case["kdj_state"])
            if candidate.get("kdj_state") and case.get("kdj_state")
            else 0.5)

        scores["volume_pattern"] = (
            self._volume_sim(candidate["volume_pattern"], case["volume_pattern"])
            if candidate.get("volume_pattern") and case.get("volume_pattern")
            else 0.5)

        scores["price_shape"] = (
            self._shape_sim(candidate["price_shape"], case["price_shape"])
            if candidate.get("price_shape") and case.get("price_shape")
            else 0.5)

        total = sum(scores[k] * self.weights.get(k, 0.25) for k in scores)
        return {
            "total_score": round(total * 100, 2),
            "breakdown": {k: round(v * 100, 2) for k, v in scores.items()},
        }

    # ---- 1. 双线结构相似度 (权重30%) ----

    def _trend_sim(self, cand, case):
        sims = []
        tol_ratio  = self.tolerances.get("trend_ratio", 0.10)
        tol_bias   = self.tolerances.get("price_bias", 10)
        tol_spread = self.tolerances.get("trend_spread", 10)

        # 短期/多空比值
        if "short_vs_bullbear" in cand and "short_vs_bullbear" in case:
            d = abs(cand["short_vs_bullbear"] - case["short_vs_bullbear"])
            sims.append(max(0, 1 - d / tol_ratio))

        # 斜率方向一致性（最重要）
        if "short_slope" in cand and "short_slope" in case:
            same_dir = (cand["short_slope"] > 0) == (case["short_slope"] > 0)
            slope_diff = abs(cand["short_slope"] - case["short_slope"])
            if same_dir:
                sims.append(max(0.7, 1 - slope_diff / 10))
            else:
                sims.append(max(0, 0.3 - slope_diff / 20))

        # 是否在碗中
        if "is_in_bowl" in cand and "is_in_bowl" in case:
            sims.append(1.0 if cand["is_in_bowl"] == case["is_in_bowl"] else 0.2)

        # 价格偏离百分比
        cb = cand.get("price_vs_short_pct", 0)
        cc = case.get("price_vs_short_pct", 0)
        sims.append(max(0, 1 - abs(cb - cc) / tol_bias))

        # 趋势发散度
        cs = cand.get("trend_spread_pct", 0)
        css = case.get("trend_spread_pct", 0)
        sims.append(max(0, 1 - abs(cs - css) / tol_spread))

        # 双线乖离率
        if "price_bias_pct" in cand and "price_bias_pct" in case:
            d = abs(cand["price_bias_pct"] - case["price_bias_pct"])
            sims.append(max(0, 1 - d / tol_bias))

        return float(np.mean(sims)) if sims else 0.5

    # ---- 2. KDJ 状态相似度 (权重20%) ----

    def _kdj_sim(self, cand, case):
        sims = []
        tol_j = self.tolerances.get("j_value", 30)

        # J值位置一致性
        if "j_position" in cand and "j_position" in case:
            if cand["j_position"] == case["j_position"]:
                sims.append(1.0)
            elif {cand["j_position"], case["j_position"]} <= {"低位", "中位"}:
                sims.append(0.8)
            else:
                sims.append(0.4)

        # J值数值相似
        if "j_value" in cand and "j_value" in case:
            d = abs(cand["j_value"] - case["j_value"])
            sims.append(max(0, 1 - d / tol_j))

        # 金叉状态
        if "k_cross_d" in cand and "k_cross_d" in case:
            sims.append(1.0 if cand["k_cross_d"] == case["k_cross_d"] else 0.6)

        # J值回升趋势
        if "j_rebound" in cand and "j_rebound" in case:
            sims.append(1.0 if cand["j_rebound"] == case["j_rebound"] else 0.7)

        return float(np.mean(sims)) if sims else 0.5

    # ---- 3. 量能特征相似度 (权重25%) ----

    def _volume_sim(self, cand, case):
        sims = []

        # 均量比 (容差 ±1.5)
        if "avg_volume_ratio" in cand and "avg_volume_ratio" in case:
            d = abs(cand["avg_volume_ratio"] - case["avg_volume_ratio"])
            sims.append(max(0, 1 - d / 1.5))

        # 缩量后放量
        if "shrink_then_expand" in cand and "shrink_then_expand" in case:
            sims.append(1.0 if cand["shrink_then_expand"] == case["shrink_then_expand"] else 0.5)

        # 关键K线数
        if "key_candles_count" in cand and "key_candles_count" in case:
            d = abs(cand["key_candles_count"] - case["key_candles_count"])
            sims.append(max(0, 1 - d / 3))

        # 量能趋势分类
        if "volume_trend" in cand and "volume_trend" in case:
            sims.append(1.0 if cand["volume_trend"] == case["volume_trend"] else 0.6)

        # 最大量比 (容差 ±3)
        if "max_volume_ratio" in cand and "max_volume_ratio" in case:
            d = abs(cand["max_volume_ratio"] - case["max_volume_ratio"])
            sims.append(max(0, 1 - d / 3))

        return float(np.mean(sims)) if sims else 0.5

    # ---- 4. 价格形态相似度 (权重25%) ----

    def _shape_sim(self, cand, case):
        sims = []
        tol_dd = self.tolerances.get("drawdown", 15)

        # DTW 曲线相似度
        if "normalized_curve" in cand and "normalized_curve" in case:
            c1 = np.asarray(cand["normalized_curve"], dtype=float)
            c2 = np.asarray(case["normalized_curve"], dtype=float)
            if len(c1) > 0 and len(c2) > 0:
                if _HAS_FASTDTW:
                    try:
                        dist, _ = _fastdtw(c1, c2, dist=_scipy_euclidean)
                        max_d = max(len(c1), len(c2))
                        sims.append(max(0, 1 - dist / max_d) if max_d > 0 else 0)
                    except Exception:
                        sims.append(self._simple_dtw(c1, c2))
                else:
                    sims.append(self._simple_dtw(c1, c2))

        # 回撤幅度 (容差 ±15%)
        if "max_drawdown" in cand and "max_drawdown" in case:
            d = abs(cand["max_drawdown"] - case["max_drawdown"])
            sims.append(max(0, 1 - d / tol_dd))

        # 突破力度 (容差 ±5%)
        if "breakout_strength" in cand and "breakout_strength" in case:
            d = abs(cand["breakout_strength"] - case["breakout_strength"])
            sims.append(max(0, 1 - d / 5))

        # 整体趋势方向
        if "overall_trend" in cand and "overall_trend" in case:
            sims.append(1.0 if cand["overall_trend"] == case["overall_trend"] else 0.5)

        # 盘整天数
        if "consolidation_days" in cand and "consolidation_days" in case:
            d = abs(cand["consolidation_days"] - case["consolidation_days"])
            sims.append(max(0, 1 - d / 10))

        return float(np.mean(sims)) if sims else 0.5

    def _simple_dtw(self, s1, s2):
        """fastdtw 不可用时的简化替代"""
        n, m = len(s1), len(s2)
        if n == 0 or m == 0:
            return 0.0
        tgt = max(n, m)
        if n != tgt:
            s1 = np.interp(np.linspace(0, n - 1, tgt), np.arange(n), s1)
        if m != tgt:
            s2 = np.interp(np.linspace(0, m - 1, tgt), np.arange(m), s2)
        dist = np.sqrt(np.sum((s1 - s2) ** 2))
        max_d = np.sqrt(len(s1))
        return float(max(0, 1 - dist / max_d)) if max_d > 0 else 0


# ============================================================
# B1 案例库  (strategy/pattern_library.py)
# ============================================================

_CACHE_DIR = Path(__file__).parent / '.cache'


class B1PatternLibrary:
    """
    B1 完美图形案例库
    - 预计算 10 个历史成功案例的特征向量
    - 支持 JSON 缓存（避免重复下载）
    - 支持动态添加/移除案例
    """

    CACHE_FILE = _CACHE_DIR / 'b1_pattern_library.json'

    def __init__(self):
        self.extractor = PatternFeatureExtractor()
        self.matcher = PatternMatcher()
        self.cases = {}
        self._load_cache()

    def build(self, download_func=None):
        """
        构建案例库（需下载 A 股历史数据）。

        download_func(yf_symbol, period) -> DataFrame
        若不传则尝试使用 yfinance。
        """
        if download_func is None:
            try:
                import yfinance as yf

                def download_func(symbol, period="2y"):
                    h = yf.download(symbol, period=period,
                                    progress=False, auto_adjust=False)
                    return h
            except ImportError:
                print("⚠️ yfinance 未安装，无法构建 B1 案例库")
                return

        print("🏗️ 构建 B1 完美图形库...")
        for case in B1_PERFECT_CASES:
            try:
                raw = download_func(case["yf_symbol"])
                df = _prepare_raw_hist(raw)
                if df is None or df.empty:
                    print(f"  ⚠️ 跳过 {case['name']}({case['code']}): 无数据")
                    continue

                window = self._extract_window(
                    df, case["breakout_date"], case["lookback_days"])
                if window is None or len(window) < 10:
                    print(f"  ⚠️ 跳过 {case['name']}: 窗口数据不足")
                    continue

                features = self.extractor.extract(window, lookback_days=len(window))
                self.cases[case["id"]] = {"meta": case, "features": features}
                print(f"  ✅ {case['name']} - 特征提取完成")

            except Exception as e:
                print(f"  ❌ {case['name']} 失败: {e}")

        if self.cases:
            self._save_cache()
            print(f"🏁 案例库构建完成: {len(self.cases)} 个案例")
        else:
            print("⚠️ 没有成功加载任何案例")

    def _extract_window(self, df, breakout_date, lookback_days):
        """提取突破日之前 lookback_days 天数据（不含突破当天）"""
        if 'date' not in df.columns:
            return None
        dates = pd.to_datetime(df['date'])
        bd = pd.to_datetime(breakout_date)
        filtered = df[dates < bd]
        if filtered.empty:
            return None
        return filtered.tail(lookback_days).reset_index(drop=True)

    def find_best_match(self, stock_data_or_df, lookback_days=DEFAULT_LOOKBACK_DAYS):
        """
        为单只股票找到最匹配的 B1 案例。

        Args:
            stock_data_or_df: Carmen stock_data dict 或已转换的 DataFrame
            lookback_days:    回看天数（默认25）

        Returns:
            dict — {best_match, all_matches, candidate_features}
        """
        if not self.cases:
            return {"best_match": None, "all_matches": [], "candidate_features": {}}

        if isinstance(stock_data_or_df, dict):
            df = _prepare_df(stock_data_or_df)
        else:
            df = stock_data_or_df

        cand_features = self.extractor.extract(df, lookback_days)

        matches = []
        for cid, cdata in self.cases.items():
            try:
                sim = self.matcher.match(cand_features, cdata["features"])
                matches.append({
                    "case_id":          cid,
                    "case_name":        cdata["meta"]["name"],
                    "case_code":        cdata["meta"]["code"],
                    "case_date":        cdata["meta"]["breakout_date"],
                    "similarity_score": sim["total_score"],
                    "breakdown":        sim["breakdown"],
                    "tags":             cdata["meta"].get("tags", []),
                })
            except Exception:
                continue

        matches.sort(key=lambda x: x["similarity_score"], reverse=True)
        return {
            "best_match":         matches[0] if matches else None,
            "all_matches":        matches,
            "candidate_features": cand_features,
        }

    def match_batch(self, stocks_data):
        """
        批量匹配: stocks_data = [{stock_data_or_df, code, name}, ...]
        """
        results = []
        for stock in stocks_data:
            try:
                r = self.find_best_match(stock.get("stock_data") or stock.get("df"))
                if r["best_match"]:
                    results.append({
                        "stock_code": stock.get("code", ""),
                        "stock_name": stock.get("name", ""),
                        **r,
                    })
            except Exception:
                continue
        results.sort(
            key=lambda x: x["best_match"]["similarity_score"]
            if x.get("best_match") else 0, reverse=True)
        return results

    def add_case(self, case_config, download_func=None):
        """动态添加案例"""
        if download_func is None:
            try:
                import yfinance as yf

                def download_func(symbol, period="2y"):
                    return yf.download(symbol, period=period,
                                       progress=False, auto_adjust=False)
            except ImportError:
                print("⚠️ yfinance 未安装")
                return

        try:
            raw = download_func(case_config["yf_symbol"])
            df = _prepare_raw_hist(raw)
            window = self._extract_window(
                df, case_config["breakout_date"],
                case_config.get("lookback_days", 25))
            features = self.extractor.extract(window, lookback_days=len(window))
            self.cases[case_config["id"]] = {"meta": case_config, "features": features}
            self._save_cache()
            print(f"✅ 新增案例: {case_config['name']}")
        except Exception as e:
            print(f"❌ 添加案例失败: {e}")

    def remove_case(self, case_id):
        if case_id in self.cases:
            del self.cases[case_id]
            self._save_cache()

    def list_cases(self):
        return [
            {"id": cid, "name": d["meta"]["name"],
             "code": d["meta"]["code"], "date": d["meta"]["breakout_date"]}
            for cid, d in self.cases.items()
        ]

    # ---- 缓存 ----

    def _save_cache(self):
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            data = {}
            for cid, cd in self.cases.items():
                data[cid] = {
                    "meta": cd["meta"],
                    "features": _serialize(cd["features"]),
                }
            with open(self.CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 缓存保存失败: {e}")

    def _load_cache(self):
        if not self.CACHE_FILE.exists():
            return
        try:
            with open(self.CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for cid, cd in data.items():
                self.cases[cid] = {
                    "meta": cd["meta"],
                    "features": _deserialize(cd["features"]),
                }
        except Exception:
            pass


# ---- 序列化工具 ----

def _serialize(obj):
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.integer, np.floating)):
        return float(obj)
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    return obj


def _deserialize(obj):
    if isinstance(obj, dict):
        return {k: _deserialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return obj
    return obj
