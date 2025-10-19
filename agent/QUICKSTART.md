# 快速开始指南

## 🚀 5分钟快速启动

### 1. 环境准备
```bash
# 确保Python 3.7+
python3 --version

# 安装依赖
pip3 install -r requirements.txt
```

### 2. API配置
```bash
# 运行快速设置脚本
python3 setup.py

# 或手动配置：
echo "sk-your-deepseek-api-key" > agent/deepseek.token
echo "your-okx-api-key" > agent/okx.token
```

### 3. 环境变量设置
```bash
export OKX_API_KEY="your-api-key"
export OKX_SECRET_KEY="your-secret-key"
export OKX_PASSPHRASE="your-passphrase"
export OKX_SANDBOX="true"  # 测试模式
```

### 4. 测试系统
```bash
python3 test_system.py
```

### 5. 启动交易
```bash
# 使用启动脚本
./start_trading.sh

# 或直接启动
python3 main.py --test-mode  # 测试模式
python3 main.py --dry-run    # 干跑模式
python3 main.py              # 正常交易
```

## 📁 文件说明

| 文件 | 说明 |
|------|------|
| `main.py` | 主程序入口 |
| `agent_trader.py` | 核心交易agent |
| `okx_api.py` | OKX交易所接口 |
| `deepseek.py` | DeepSeek API接口 |
| `risk_manager.py` | 风险管理模块 |
| `config.py` | 配置管理 |
| `test_system.py` | 系统测试脚本 |
| `setup.py` | 快速设置脚本 |
| `start_trading.sh` | 启动脚本 |
| `requirements.txt` | 依赖包列表 |
| `README.md` | 详细文档 |

## ⚙️ 配置选项

### 基本配置
- `trading_interval_minutes`: 交易决策间隔（默认3分钟）
- `max_leverage`: 最大杠杆倍数（默认15倍）
- `max_risk_per_trade`: 单笔交易风险比例（默认5%）
- `max_positions`: 最大持仓数（默认6个）

### 运行模式
- `--test-mode`: 测试模式（使用沙盒环境）
- `--dry-run`: 干跑模式（只分析不交易）
- `--interval N`: 设置交易间隔为N分钟
- `--log-level LEVEL`: 设置日志级别
- `--enable-prompt-log`: 启用详细的prompt日志记录
- `--disable-prompt-log`: 禁用prompt日志记录

## 🛡️ 安全建议

1. **测试先行**: 始终先在测试环境中验证
2. **小资金开始**: 使用少量资金测试策略
3. **定期监控**: 关注交易日志和风险指标
4. **备份配置**: 定期备份重要的配置文件

## 📊 监控指标

- **账户价值**: 实时监控总资产变化
- **未实现盈亏**: 当前持仓的盈亏情况
- **风险指标**: 夏普比率、最大回撤等
- **交易统计**: 交易次数、成功率等

## 🆘 常见问题

### Q: API连接失败怎么办？
A: 检查网络连接和API密钥配置，确认API权限设置正确。

### Q: 如何修改交易策略？
A: 编辑 `agent_trader.py` 中的系统提示词，调整AI决策逻辑。

### Q: 如何调整风险参数？
A: 修改 `config.py` 中的风险管理参数，或使用命令行参数。

### Q: 系统运行异常怎么办？
A: 查看 `trading_log.txt` 日志文件，使用DEBUG模式获取详细信息。

## 📞 技术支持

如遇到问题，请：
1. 查看 `README.md` 详细文档
2. 检查 `trading_log.txt` 日志文件
3. 运行 `test_system.py` 诊断问题
4. 确保所有依赖包已正确安装

---

**免责声明**: 本系统仅供学习和研究使用，不构成投资建议。加密货币交易存在高风险，请谨慎使用。
