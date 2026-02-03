# AI 智能股票监控与分析系统 (AI Stock Monitor & Analysis System)

这是一个集成了技术指标分析、AI 深度研判、自动警报和 Web 报告生成的综合性股票市场监控系统。支持美股、A股和港股三大市场，旨在辅助投资者进行高效的市场扫描和决策。

## 🚀 主要功能

*   **多市场支持**：全面覆盖美股 (US)、A股 (China A) 和港股 (HK) 市场。
*   **技术指标扫描**：内置 RSI、MACD、Carmen、Vegas 等多种技术指标组合，自动过滤低成交量标的。
*   **AI 智能分析**：
    *   集成大语言模型（DeepSeek）对筛选出的潜力股进行深度分析
    *   自动提取关键交易信息：**买入区间**、**买入时间**、**目标价位**、**止损位**、**预估胜率**
    *   **异步并发处理**：采用多线程架构，AI 分析与消息推送在后台异步执行，不阻塞主扫描流程，极大提升扫描效率
    *   支持多种 AI 输出格式的智能解析（Markdown、价格区间、中文表达等）
    *   QQ 推送与网页报告**数据同源**，避免重复 API 调用
*   **实时预警系统**：
    *   **QQ 消息推送**：通过 Qmsg 酱实时推送买入/卖出信号，包含完整的 AI 分析摘要（买入区间、目标价、止损位、胜率等）
    *   **GitHub Pages**：自动生成并部署静态 HTML 市场分析报告，展示原始 AI 深度分析结论，支持移动端查看
    *   **控制台摘要**：使用 ✅/⚠️/❌ 标识字段提取状态，便于调试
*   **自动化调度**：内置市场调度器，根据不同市场的交易时间（盘前、盘中、盘后）自动运行扫描任务。
*   **智能缓存**：AI 分析结果自动缓存复用，QQ 与网页推送共享同一数据源，节省 API 调用。
*   **辅助工具**：包含 YouTube 财经频道自动摘要工具和实验性的量化交易代理。

## 📂 项目结构与入口

### 1. 核心监控系统 (`indicator/`)
这是项目最核心的部分，负责市场扫描和信号生成。

*   **美股监控**: `indicator/main.py`
    *   运行模式：混合模式（定点扫描 + 盘中轮询）。
*   **A股监控**: `indicator/main_a.py`
    *   运行节点：11:35 (午休), 14:30, 15:10 (收盘)。
*   **港股监控**: `indicator/main_hk.py`
    *   运行节点：12:05 (午休), 15:30, 16:10 (收盘)。

### 2. 实验性量化交易 (`agent/`)
*   **入口**: `agent/main.py`
*   **说明**: 一个自动量化交易尝试，包含自动止盈止损和反指模式。
*   **⚠️ 风险提示**: 该模块尚不成熟，历史测试中曾导致账户归零，请谨慎参考或仅作学习用途。

### 3. 媒体监控工具 (`autotube/`)
*   **入口**: `autotube/monitor.py`
*   **功能**: 自动下载指定财经 YouTuber 的视频/直播，使用 Whisper 进行语音转写，并调用 DeepSeek 进行核心观点总结和整理。

## 🛠️ 安装与配置

### 环境要求
*   Python 3.8+
*   Git

### 安装依赖
```bash
pip install -r requirements.txt
```

### 配置说明
在使用前，你可能需要配置以下环境变量或文件：

1.  **QQ 推送配置**: 需要 Qmsg 酱的 Key 和目标 QQ 号。
2.  **LLM API 配置**: 用于 AI 分析（如 DeepSeek 或 OpenAI API Key）。
3.  **股票列表**:
    *   美股：默认扫描 Nasdaq 全量或 `my_stock_symbols.txt`。
    *   A股/港股：依赖 `stocks_list/cache/` 下的 CSV 文件。

## 🖥️ 使用方法

### 启动美股监控
```bash
cd indicator
python main.py
```

### 启动A股监控
```bash
cd indicator
python main_a.py
```

### 启动港股监控
```bash
cd indicator
python main_hk.py
```

## 📝 更新日志

### 2026-02-03

#### 异步架构升级 (`indicator/main*.py` & `indicator/async_ai.py`)
*   **多线程并发处理**：
    *   引入 `ThreadPoolExecutor` 线程池，实现 AI 分析任务的后台异步执行。
    *   扫描主循环不再被耗时的 AI API 调用阻塞，可立即处理下一只股票。
    *   HTML 报告生成前自动等待所有挂起的后台任务完成，确保数据完整性。
*   **代码重构**：
    *   新增 `indicator/async_ai.py` 模块，封装通用的异步任务处理逻辑。
    *   统一了 A股 (`main_a.py`) 和 港股 (`main_hk.py`) 的异步处理模式。

#### AI 分析提炼功能增强 (`indicator/analysis.py`)
*   **扩展 `refine_ai_analysis()` 字段提取**：
    *   新增字段：`min_buy_price`（买入区间下限）、`buy_time`（买入时间）、`target_price`（目标价/止盈位）、`stop_loss`（止损位）
    *   原有字段：`max_buy_price`（买入区间上限）、`win_rate`（预估胜率）
*   **增强正则表达式鲁棒性**：
    *   支持 Markdown 格式（如 `**理想买入区间**: $31.50 - $32.00`）
    *   支持价格区间格式（如 `约60-65%` 自动取中间值）
    *   支持多种中文表达方式
*   **修复 refine 误触发辩论模式**：添加 `agent_mode=False, enable_debate=False` 参数

#### QQ 推送功能增强 (`indicator/qq_notifier.py`)
*   **新增 `send_buy_signal()` 参数**：
    *   `min_buy_price`, `buy_time`, `target_price`, `stop_loss`, `refined_text`
*   **新增控制台摘要输出**：
    *   `_print_buy_signal_summary()` 方法打印完整 AI 分析摘要
    *   使用 ✅/⚠️/❌ 标识字段提取状态
    *   可通过注释关闭调试输出

#### 数据同源与缓存优化 (`indicator/main*.py`)
*   **修复 QQ 与网页推送不同源问题**：
    *   AI 分析结果保存到 `stock_data['_ai_analysis']` 和 `stock_data['_refined_info']`
    *   HTML 生成时复用缓存，避免重复 API 调用
*   **输出内容分离**：
    *   网页端：输出原始 AI 分析结论（完整报告）
    *   QQ 推送：输出解析字段 + refine 文本（简洁摘要）

## ⚠️ 免责声明

本项目仅供计算机编程学习和金融数据分析研究使用。
*   程序输出的所有分析、信号和建议仅供参考，不构成任何投资建议。
*   金融市场风险巨大，**agent 模块的自动交易功能具有极高风险**。
*   开发者不对任何因使用本软件而产生的投资损失负责。

