# TG-AI 使用说明

TG-AI 是 Carmen 的 Telegram AI 分析监听器，用于接收机器人按钮回调与 `/ai_analysis` 命令，并调用本地 AI 分析链路返回结果。

## 功能

- 接收买入提醒里的 **`🤖 AI分析`** 按钮点击
- 接收 Telegram 命令：`/ai_analysis <symbol>`
- 优先复用 `indicator/analysis_cache/` 中的缓存结果
- 缓存失效时自动调用 `analyze_stock_with_ai()` 重新分析
- 仅响应配置文件中指定的 Telegram `chat_id`

## 支持的股票代码输入

统一调用方法如下：

- **A股：6位数字**
  - `5/6/9` 开头 → 自动识别为 `.SS`
  - 其它常见 6 位数字 → 自动识别为 `.SZ`
  - 示例：
    - `/ai_analysis 600519`
    - `/ai_analysis 002594`
    - `/ai_analysis 300750`

- **港股：4位数字**
  - 自动识别为 `.HK`
  - 示例：
    - `/ai_analysis 0700`
    - `/ai_analysis 3969`

- **美股：全字母**
  - 直接按 ticker 处理
  - 示例：
    - `/ai_analysis TSLA`
    - `/ai_analysis NVDA`

- **也兼容显式后缀写法**
  - `600519SH`
  - `600519SS`
  - `002594SZ`
  - `0700HK`

## 依赖

- Telegram Bot Token / Chat ID
- Carmen 本地分析环境
- `indicator/telegram.token`
- `agent/deepseek.token`
- `Quant` conda 环境

## 启动方式

### 方式 1：直接前台启动

```bash
cd /home/serv/Carmen
source ~/.zshrc
conda activate Quant
python scripts/telegram_ai_listener.py
```

### 方式 2：在 tmux 中启动（推荐）

```bash
cd /home/serv/Carmen
source ~/.zshrc

# 新建独立窗口
if tmux has-session -t Carmen 2>/dev/null; then
  tmux new-window -t Carmen -c /home/serv/Carmen -n TG-AI 'source ~/.zshrc && conda activate Quant && cd /home/serv/Carmen && python scripts/telegram_ai_listener.py'
else
  tmux new-session -d -s Carmen -c /home/serv/Carmen -n TG-AI 'source ~/.zshrc && conda activate Quant && cd /home/serv/Carmen && python scripts/telegram_ai_listener.py'
fi
```

### 方式 3：完整重启 Carmen 四窗口

```bash
cd /home/serv/Carmen
source ~/.zshrc

if tmux has-session -t Carmen 2>/dev/null; then
  tmux kill-session -t Carmen
fi

tmux new-session -d -s Carmen -c /home/serv/Carmen -n US 'source ~/.zshrc && conda activate Quant && cd /home/serv/Carmen && python indicator/run.py'
tmux new-window -t Carmen:1 -c /home/serv/Carmen -n A 'source ~/.zshrc && conda activate Quant && cd /home/serv/Carmen && python indicator/main_a.py'
tmux new-window -t Carmen:2 -c /home/serv/Carmen -n HK 'source ~/.zshrc && conda activate Quant && cd /home/serv/Carmen && python indicator/main_hk.py'
tmux new-window -t Carmen:3 -c /home/serv/Carmen -n TG-AI 'source ~/.zshrc && conda activate Quant && cd /home/serv/Carmen && python scripts/telegram_ai_listener.py'
```

## 常用 tmux 命令

查看窗口：

```bash
tmux list-windows -t Carmen
```

查看 TG-AI 输出：

```bash
tmux capture-pane -t Carmen:TG-AI -p | tail -50
```

重启 TG-AI：

```bash
tmux send-keys -t Carmen:TG-AI C-c
tmux send-keys -t Carmen:TG-AI 'source ~/.zshrc && conda activate Quant && cd /home/serv/Carmen && python scripts/telegram_ai_listener.py' Enter
```

## 运行状态

正常启动后，监听器会：

- 注册 bot 命令 `/ai_analysis`
- 轮询 Telegram `getUpdates`
- 处理按钮回调与命令消息
- 将分析结果回复到当前 Telegram 对话

## 文件位置

- 监听器：`/home/serv/Carmen/scripts/telegram_ai_listener.py`
- Telegram 推送器：`/home/serv/Carmen/indicator/telegram_notifier.py`
- AI 分析缓存：`/home/serv/Carmen/indicator/analysis_cache/`
- 偏移量状态：`/home/serv/Carmen/runtime/telegram_listener.offset`
