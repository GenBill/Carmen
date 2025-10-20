# AI自动交易系统

基于DeepSeek API和OKX交易所的加密货币永续合约自动交易agent，专门交易BTC、ETH、SOL、BNB、DOGE、XRP。

## 功能特点

- 🤖 **AI驱动决策**: 使用DeepSeek Chat模型进行智能交易决策
- 📊 **技术分析**: 集成EMA、MACD、RSI、ATR等技术指标
- 🛡️ **风险管理**: 内置止损、止盈、仓位控制等风险管理功能
- ⚡ **永续合约交易**: 支持OKX交易所的永续合约实时交易执行
- 📈 **杠杆交易**: 支持最大15倍杠杆的永续合约交易
- 📝 **详细日志**: 完整的交易记录和日志系统

## 系统架构

```
agent/
├── main.py              # 主程序入口
├── agent_trader.py      # 核心交易agent
├── okx_api.py          # OKX交易所API接口
├── deepseek.py         # DeepSeek API接口
├── risk_manager.py     # 风险管理模块
├── config.py           # 配置管理
├── requirements.txt    # 依赖包列表
├── agent/deepseek.token     # DeepSeek API密钥
├── agent/okx.token          # OKX API密钥
└── README.md          # 说明文档
```

## 安装和配置

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置API密钥

#### DeepSeek API
在 `agent/deepseek.token` 文件中放入您的DeepSeek API密钥：
```
sk-your-deepseek-api-key-here
```

#### OKX API
在 `agent/okx.token` 文件中放入您的OKX API密钥，并设置环境变量：

```bash
export OKX_API_KEY="your-okx-api-key"
export OKX_SECRET_KEY="your-okx-secret-key"
export OKX_PASSPHRASE="your-okx-passphrase"
```

### 3. 配置OKX API权限

确保您的OKX API密钥具有以下权限：
- 读取账户信息
- 获取市场数据
- 执行交易订单
- 管理持仓

## 使用方法

### 基本使用

```bash
python main.py
```

### 高级选项

```bash
# 设置交易间隔为5分钟
python main.py --interval 5

# 设置日志级别为DEBUG
python main.py --log-level DEBUG

# 测试模式（使用沙盒环境）
python main.py --test-mode

# 干跑模式（只分析不交易）
python main.py --dry-run

# 启用详细的prompt日志记录
python main.py --enable-prompt-log

# 禁用prompt日志记录
python main.py --disable-prompt-log

# 设置起始账户价值
python main.py --initial-value 50000

# 重置系统状态
python main.py --reset-state --initial-value 10000

# 显示性能摘要
python main.py --show-performance
```

### 参数说明

- `--interval`: 交易决策间隔（分钟），默认3分钟
- `--log-level`: 日志级别，可选DEBUG/INFO/WARNING/ERROR
- `--test-mode`: 测试模式，使用OKX沙盒环境
- `--dry-run`: 干跑模式，只分析市场不执行交易
- `--enable-prompt-log`: 启用详细的prompt日志记录（默认启用）
- `--disable-prompt-log`: 禁用prompt日志记录
- `--initial-value`: 设置起始账户价值（USDT）
- `--reset-state`: 重置系统状态
- `--show-performance`: 显示性能摘要后退出

## 交易策略

### AI决策流程

1. **数据收集**: 获取所有支持币种的实时价格和技术指标
2. **AI分析**: DeepSeek模型分析市场数据并做出交易决策
3. **风险验证**: 风险管理模块验证交易决策的合规性
4. **执行交易**: 通过OKX API执行交易订单
5. **记录日志**: 记录所有交易决策和执行结果

### 技术指标

- **EMA20**: 20期指数移动平均线，判断趋势方向
- **MACD**: 移动平均收敛散度，判断动量变化
- **RSI**: 相对强弱指数，判断超买超卖状态
- **ATR**: 平均真实波幅，判断波动率
- **资金费率**: 永续合约资金费率，判断市场情绪

### 风险管理

- **止损**: 每笔交易设置止损价格
- **止盈**: 每笔交易设置止盈目标
- **仓位控制**: 限制单笔交易风险不超过总资金的5%
- **持仓限制**: 最多同时持有6个币种的仓位
- **杠杆控制**: 最大杠杆倍数15倍

## 日志和监控

### 日志文件

- `trading_log.txt`: 主要交易日志，包含所有交易决策、执行结果和错误信息
- `prompt_log.txt`: 详细的prompt日志，记录每次AI交互的完整输入和输出（需要启用prompt日志功能）
- `trading_state.json`: 系统状态文件，保存起始时间、账户信息、交易历史等数据

### 监控指标

- 账户总价值
- 未实现盈亏
- 持仓详情
- 风险指标（夏普比率、最大回撤等）

### 状态管理

系统具有完整的状态持久化功能，支持：

- **状态恢复**: 系统关闭后重新启动会自动恢复之前的交易状态
- **起始时间跟踪**: 记录系统首次启动时间，计算总运行时间
- **交易历史**: 保存所有交易记录，包括成功/失败统计
- **性能指标**: 自动计算胜率、最大回撤、最佳/最差交易等指标
- **会话管理**: 跟踪不同的运行会话，支持多次启动

#### 状态文件说明

`trading_state.json` 包含以下信息：
- 起始时间和账户价值
- 总调用次数和交易次数
- 成功/失败交易统计
- 总PnL和性能指标
- 完整的交易历史记录

## 安全注意事项

1. **API密钥安全**: 确保API密钥文件权限设置正确，不要提交到版本控制
2. **测试先行**: 建议先在测试环境中验证策略效果
3. **资金管理**: 建议使用小资金进行测试，逐步增加投资金额
4. **风险控制**: 定期检查持仓和风险指标，必要时手动干预
5. **网络稳定**: 确保网络连接稳定，避免因网络问题导致交易失败

## 故障排除

### 常见问题

1. **API连接失败**
   - 检查网络连接
   - 验证API密钥是否正确
   - 确认API权限设置

2. **交易执行失败**
   - 检查账户余额是否充足
   - 验证交易对是否支持
   - 查看OKX交易所状态

3. **AI决策异常**
   - 检查DeepSeek API密钥
   - 查看API调用次数限制
   - 验证市场数据格式

### 调试模式

使用DEBUG日志级别获取详细信息：

```bash
python main.py --log-level DEBUG
```

## 免责声明

本系统仅供学习和研究使用，不构成投资建议。加密货币交易存在高风险，可能导致资金损失。使用本系统进行实际交易的风险由用户自行承担。

## 许可证

本项目采用MIT许可证，详见LICENSE文件。
