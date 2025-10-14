# Carmen Stock Scanner - GitHub Pages

本目录包含自动生成的HTML报告和调试信息。

## 📁 文件说明

### `index.html`
主要的股票扫描报告页面，包含：
- 市场状态（盘前/盘中/盘后）
- 扫描的股票列表
- 技术指标（RSI、MACD）
- 交易信号（买入/卖出）

访问地址: `https://<用户名>.github.io/Carmen/`

### `meta.json`
调试和追溯信息文件，包含：
- **最后更新时间**: 上次生成报告的时间戳
- **内容哈希**: 用于检测内容是否变化的MD5哈希值
- **市场状态**: 当前市场状态（盘前/盘中/盘后）
- **统计数据**: 扫描数量、成功率、信号数量等
- **更新历史**: 最近10次更新的记录

#### meta.json 示例

```json
{
  "last_update": "2025-10-14T09:30:15.123456",
  "last_update_readable": "2025-10-14 09:30:15",
  "content_hash": "a1b2c3d4e5f6g7h8i9j0",
  "html_file": "docs/index.html",
  "html_file_size": 12345,
  "market_status": "⏰ 盘前时段",
  "update_time": "2025-10-14 09:30:00 EDT",
  "mode": "盘前/盘后模式",
  "stats": {
    "total_scanned": 981,
    "success_count": 954,
    "signal_count": 5,
    "blacklist_count": 2119,
    "stocks_displayed": 22
  },
  "config": {
    "rsi_period": 8,
    "macd_params": "8,17,9"
  },
  "update_history": [
    {
      "timestamp": "2025-10-14T09:30:15.123456",
      "timestamp_readable": "2025-10-14 09:30:15",
      "content_hash": "a1b2c3d4e5f6g7h8i9j0",
      "market_status": "⏰ 盘前时段",
      "stocks_count": 22,
      "signals": 5
    }
  ],
  "total_updates": 1
}
```

## 🔍 调试用途

### 检查上次更新时间
```bash
cat docs/meta.json | grep last_update_readable
```

### 查看内容哈希
```bash
cat docs/meta.json | grep content_hash
```

### 查看更新历史
```bash
cat docs/meta.json | jq '.update_history'
```

### 验证数据完整性
通过比较连续两次更新的content_hash，可以验证数据是否真正发生变化。

## 🚀 自动更新机制

程序在每次扫描完成后：
1. 生成HTML报告
2. 计算内容哈希
3. 与上次对比
4. 如果内容变化（或HTML不存在）→ 生成新HTML + 更新meta.json
5. 自动推送到GitHub Pages

## 📊 查看更新频率

通过meta.json的update_history可以了解：
- 更新频率
- 每次更新的市场状态
- 数据变化趋势
- 交易信号出现频率

## 💡 故障排除

### 问题：页面未更新

1. 检查meta.json的last_update时间
2. 比较content_hash是否变化
3. 查看update_history了解更新模式

### 问题：数据看起来不对

1. 检查meta.json中的market_status
2. 确认update_time是否正确
3. 查看stats中的数据是否合理

## 🔒 隐私说明

- `index.html`: 公开可访问（如果仓库是公开的）
- `meta.json`: 仅包含统计信息，不含敏感数据

## 📝 更新日志

meta.json会自动记录最近10次更新，包括：
- 时间戳
- 内容哈希
- 市场状态
- 股票数量
- 信号数量

这些信息可用于：
- 追溯历史变化
- 调试更新问题
- 分析数据模式
- 验证系统运行

---

**自动生成** | 由 Carmen Stock Scanner 维护

