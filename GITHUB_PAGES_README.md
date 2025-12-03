# GitHub Pages 自动发布系统

## 📦 已完成的功能

本系统为您的 Carmen Stock Scanner 添加了完整的 GitHub Pages 自动发布功能。

### ✨ 核心特性

1. **智能内容检测** 🧠
   - 通过MD5哈希自动检测内容变化
   - 仅在数据真正更新时推送
   - 避免不必要的Git提交污染

2. **自动Git推送** 🚀
   - 数据更新后自动推送到GitHub
   - 使用独立的`gh-pages`分支
   - 不影响主代码仓库

3. **美观的展示页面** 🎨
   - 现代化响应式设计
   - 支持移动端访问
   - 实时显示市场状态和技术指标

4. **24/7运行支持** ⏰
   - 支持程序持续运行
   - 支持不定时启动
   - 每次检测内容变化自动推送

## 📁 新增文件清单

### 核心模块

| 文件 | 说明 |
|------|------|
| `indicator/html_generator.py` | HTML报告生成器，负责将股票数据转换为美观的HTML页面 |
| `indicator/git_publisher.py` | Git自动推送器，负责检测变化并推送到GitHub |
| `indicator/main.py` (已修改) | 主程序，已集成HTML生成和自动推送功能 |

### 配置和测试工具

| 文件 | 说明 |
|------|------|
| `setup_github_pages.sh` | 一键配置脚本，自动创建gh-pages分支 |
| `indicator/test_github_pages.py` | 功能测试脚本，验证系统是否正常工作 |

### 文档

| 文件 | 说明 |
|------|------|
| `GITHUB_PAGES_SETUP.md` | 完整配置指南（包含故障排除） |
| `QUICK_START_GITHUB_PAGES.md` | 5分钟快速开始指南 |
| `GITHUB_PAGES_README.md` | 本文件，项目总览 |

## 🚀 快速开始

### 方式1: 自动配置（推荐）

```bash
# 1. 运行配置脚本
cd /home/ibn5100/Carmen
./setup_github_pages.sh

# 2. 在GitHub启用Pages
#    Settings → Pages → Source: gh-pages

# 3. 运行程序
cd indicator
python main.py
```

### 方式2: 手动配置

详见 `QUICK_START_GITHUB_PAGES.md`

## 📊 工作流程

```
程序启动
    ↓
每次数据扫描循环 ────┐
    ↓               │
获取股票数据        │
    ↓               │
生成HTML报告        │
    ↓               │
计算内容哈希        │
    ↓               │
对比旧版本          │
    ↓               │
内容有变化？        │
    ↓ Yes           │
推送到GitHub        │
    ↓               │
等待下一次扫描 ─────┘
```

### 推送触发条件

✅ **会触发推送**：
- 股票列表变化
- 价格数据更新  
- 技术指标变化
- 交易信号出现/消失
- 市场状态变化

❌ **不会触发推送**：
- 仅时间戳更新
- 格式调整
- 注释修改

## ⚙️ 配置说明

### 主程序配置 (indicator/main.py)

```python
# GitHub Pages 配置
ENABLE_GITHUB_PAGES = True   # 启用/禁用自动推送
GITHUB_BRANCH = 'gh-pages'   # 目标分支名称
```

### 关键参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_GITHUB_PAGES` | `True` | 是否启用自动推送 |
| `GITHUB_BRANCH` | `'gh-pages'` | GitHub Pages分支名 |
| `html_file` | `'docs/index.html'` | HTML输出路径 |

## 🧪 测试系统

在部署前，建议先运行测试：

```bash
cd /home/ibn5100/Carmen
python indicator/test_github_pages.py
```

测试包括：
- ✅ HTML生成功能
- ✅ 内容变化检测
- ✅ Git环境检查
- ✅ 分支状态验证

## 📝 使用示例

### 基本使用

```bash
# 正常运行程序，自动推送已启用
cd /home/ibn5100/Carmen/indicator
python main.py
```

程序输出示例：
```
========================================================
⏰ 盘前时段 | 盘前/盘后模式 | 2025-10-14 09:29:24 EDT
查询 981 只股票 | RSI8 | MACD(8,17,9) | 缓存60分钟
...
[股票数据表格]
...
============================================================
📄 正在生成HTML报告...
✅ HTML报告已生成（内容有更新）
🚀 检测到内容变化，准备推送到GitHub Pages...
============================================================
📤 开始推送到 GitHub Pages...
============================================================
🔄 切换到 gh-pages 分支...
📝 添加文件到暂存区...
💾 提交变更: Update stock report - 2025-10-14 09:30:15
🚀 推送到远程仓库...
✅ 成功推送到 GitHub Pages!
🌐 您的页面将在几分钟后更新
🌐 访问您的页面: https://GenBill.github.io/Carmen/
```

### 禁用自动推送

```python
# 临时禁用
ENABLE_GITHUB_PAGES = False
```

### 查看生成的HTML

```bash
# 本地查看
cd /home/ibn5100/Carmen
firefox docs/index.html  # 或其他浏览器
```

## 🔧 常见操作

### 1. 初始化gh-pages分支

```bash
./setup_github_pages.sh
```

### 2. 手动推送更新

```bash
cd /home/ibn5100/Carmen

# 确保HTML已生成
ls -lh docs/index.html

# 手动推送
git checkout gh-pages
git add docs/index.html
git commit -m "Update report"
git push origin gh-pages
git checkout main
```

### 3. 强制重新生成

```bash
# 删除旧HTML
rm docs/index.html

# 重新运行程序
python indicator/main.py
```

### 4. 查看推送历史

```bash
git log gh-pages --oneline -10
```

### 5. 切换到gh-pages查看内容

```bash
git checkout gh-pages
ls -la docs/
cat docs/index.html | head -50
git checkout main  # 切回主分支
```

## 🌐 访问您的页面

推送成功后，页面地址为：

```
https://<GitHub用户名>.github.io/Carmen/
```

例如：
- 用户: `GenBill`
- 页面: `https://GenBill.github.io/Carmen/`

## 📱 特性展示

### 页面元素

- **市场状态栏**: 显示当前市场状态（盘前/盘中/盘后）
- **统计信息**: 扫描股票数、成功率、信号数量
- **股票表格**: 详细的价格、涨跌、RSI、MACD数据
- **自选股高亮**: ⭐标记自选股，黄色背景
- **交易信号**: 醒目的买入/卖出信号标记
- **响应式设计**: 完美支持PC和移动设备

### 示例截图结构

```
┌─────────────────────────────────────────┐
│  📊 Carmen Stock Scanner                │
│  NASDAQ 盘前/盘后技术指标扫描            │
├─────────────────────────────────────────┤
│  市场状态: ⏰ 盘前时段                   │
│  更新时间: 2025-10-14 09:30:00 EDT     │
│  扫描模式: 盘前/盘后模式                 │
├─────────────────────────────────────────┤
│  扫描股票    成功获取    交易信号        │
│     981        954         5            │
├─────────────────────────────────────────┤
│ 股票 | 价格涨跌 | 量比 | RSI | MACD     │
├─────────────────────────────────────────┤
│ ⭐AAPL | +2.5% | 120% | 45→52 | Buy 3.2│
│ TSLA  | -1.2% |  95% | 62→58 | Sell 3.5│
│  ...                                    │
└─────────────────────────────────────────┘
```

## 🔒 安全和隐私

### 私有仓库
- 私有仓库的GitHub Pages默认也是私有的
- 只有仓库访问权限的用户可以查看

### 公开仓库
- 页面对所有人可见
- 建议不要包含敏感信息

### API密钥保护
- 确保`.gitignore`包含密钥文件
- 使用环境变量存储敏感信息
- 不要将密钥硬编码到代码中

## 📚 文档指引

| 需求 | 推荐文档 |
|------|----------|
| 快速上手 | `QUICK_START_GITHUB_PAGES.md` |
| 详细配置 | `GITHUB_PAGES_SETUP.md` |
| 故障排除 | `GITHUB_PAGES_SETUP.md` (故障排除章节) |
| 开发测试 | `indicator/test_github_pages.py` |

## 💡 最佳实践

### 1. 程序运行模式

**持续运行（推荐）**：
```bash
# 使用screen或tmux保持后台运行
screen -S carmen
cd /home/ibn5100/Carmen/indicator
python main.py
# Ctrl+A, D 离开但保持运行
```

**定时任务**：
```bash
# crontab配置
# 每天早上7:00和下午4:30运行
0 7 * * 1-5 cd /home/ibn5100/Carmen/indicator && python main.py >> /var/log/carmen.log 2>&1
30 16 * * 1-5 cd /home/ibn5100/Carmen/indicator && python main.py >> /var/log/carmen.log 2>&1
```

### 2. 分支管理

- ✅ 主分支 (`main`/`master`): 代码开发
- ✅ `gh-pages` 分支: GitHub Pages内容
- ✅ 两个分支完全独立，互不影响

### 3. 性能优化

- 数据缓存: 避免频繁API调用
- 智能推送: 只在内容变化时推送
- 轻量HTML: 优化文件大小

## 🎯 下一步

### 立即开始

```bash
# 1. 测试功能
python indicator/test_github_pages.py

# 2. 初始化分支
./setup_github_pages.sh

# 3. 启用GitHub Pages
#    访问: https://github.com/<用户名>/Carmen/settings/pages

# 4. 运行程序
cd indicator
python main.py
```

### 进阶定制

- 修改HTML样式: 编辑 `indicator/html_generator.py`
- 自定义推送逻辑: 编辑 `indicator/git_publisher.py`
- 添加通知功能: 集成邮件/Webhook通知

## 📞 支持

### 运行诊断

```bash
# 环境检查
python indicator/test_github_pages.py

# Git状态
git status
git branch -a

# 查看日志
git log gh-pages --oneline -5
```

### 常见问题

详见 `GITHUB_PAGES_SETUP.md` 的"故障排除"章节

## 🎉 总结

您现在拥有一个完整的自动化股票数据发布系统：

✅ **自动扫描** - 定期或持续扫描股票数据  
✅ **智能检测** - 仅在数据变化时更新  
✅ **自动推送** - 无需手动操作  
✅ **美观展示** - 专业的可视化界面  
✅ **随时访问** - 通过网页随地查看  

**享受自动化带来的便利！** 🚀

