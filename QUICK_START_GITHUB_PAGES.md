# GitHub Pages 快速开始指南

## 🚀 5分钟快速配置

### 前提条件
- ✅ Git已安装
- ✅ GitHub账号已创建
- ✅ 代码已推送到GitHub仓库

### 快速配置步骤

#### 1️⃣ 运行自动配置脚本

```bash
cd /home/ibn5100/Carmen
./setup_github_pages.sh
```

这个脚本会自动：
- 创建 `gh-pages` 分支
- 初始化占位HTML
- 推送到GitHub

#### 2️⃣ 在GitHub启用Pages

1. 访问您的仓库: `https://github.com/<用户名>/Carmen`
2. 点击 **Settings** → **Pages**
3. 在 **Source** 下选择:
   - Branch: `gh-pages`
   - Folder: `/ (root)`
4. 点击 **Save**

#### 3️⃣ 配置程序（可选）

编辑 `indicator/main.py`，确认以下配置：

```python
# 启用GitHub Pages自动推送
ENABLE_GITHUB_PAGES = True

# 分支名称（默认即可）
GITHUB_BRANCH = 'gh-pages'
```

#### 4️⃣ 运行程序

```bash
cd indicator
python main.py
```

程序会：
- ✅ 扫描股票数据
- ✅ 生成HTML报告
- ✅ 自动推送到GitHub
- ✅ 显示页面URL

#### 5️⃣ 访问您的页面

几分钟后访问：
```
https://<用户名>.github.io/Carmen/
```

## 🧪 测试功能

在运行主程序前，可以先测试功能是否正常：

```bash
cd /home/ibn5100/Carmen
python indicator/test_github_pages.py
```

测试脚本会检查：
- HTML生成功能
- Git推送器配置
- 内容变化检测

## 📊 工作原理

### 自动检测机制

程序通过以下方式检测内容是否需要更新：

1. **MD5哈希对比**：比较新旧数据的哈希值
2. **只推送变化**：内容相同时跳过推送
3. **智能识别**：只对关键数据（股票、价格、指标）计算哈希

### 推送触发条件

满足以下条件时自动推送：

- ✅ 股票列表有变化
- ✅ 价格数据更新
- ✅ 技术指标变化
- ✅ 交易信号出现/消失

**不会触发推送的情况**：
- ❌ 仅时间戳变化
- ❌ 格式调整
- ❌ 注释修改

### 推送流程

```
数据扫描完成
    ↓
生成HTML到 docs/index.html
    ↓
计算内容哈希
    ↓
与旧版本对比
    ↓
内容有变化？
    ↓ Yes
切换到 gh-pages 分支
    ↓
复制HTML文件
    ↓
Git commit + push
    ↓
GitHub Pages 自动部署
    ↓
页面更新完成
```

## ⚙️ 配置选项

### 禁用自动推送

如果暂时不需要自动推送：

```python
# indicator/main.py
ENABLE_GITHUB_PAGES = False  # 禁用
```

### 使用不同分支

```python
# indicator/main.py
GITHUB_BRANCH = 'my-pages'  # 自定义分支名
```

记得在GitHub Pages设置中也选择相应分支。

### 修改HTML输出路径

```python
# 在 git_publisher 初始化时指定
git_publisher = GitPublisher(
    branch='gh-pages',
    html_file='custom/report.html'  # 自定义路径
)
```

## 🔧 常见问题

### Q1: 推送失败，提示权限错误

**原因**：没有配置Git凭据

**解决方案**：

```bash
# 方法1: 配置SSH密钥（推荐）
ssh-keygen -t ed25519 -C "your_email@example.com"
# 复制 ~/.ssh/id_ed25519.pub 到 GitHub Settings → SSH Keys

# 方法2: 使用Personal Access Token
# 1. GitHub → Settings → Developer settings → Personal access tokens
# 2. 生成token，勾选 repo 权限
# 3. 配置远程URL：
git remote set-url origin https://<TOKEN>@github.com/<用户名>/Carmen.git
```

### Q2: 页面显示404

**检查清单**：

1. GitHub Pages是否已启用？
2. 分支选择是否正确？
3. 是否等待了1-2分钟让GitHub处理？
4. HTML文件是否在正确位置？

### Q3: 页面内容未更新

**解决方案**：

```bash
# 1. 强制刷新浏览器（清除缓存）
Ctrl + Shift + R

# 2. 检查推送状态
cd /home/ibn5100/Carmen
git checkout gh-pages
git log --oneline -5
git checkout main  # 或 master

# 3. 手动触发推送
rm docs/index.html  # 删除旧HTML
python indicator/main.py  # 重新生成并推送
```

### Q4: 程序说"内容无变化"但我确实更新了数据

**原因**：程序只检查关键数据变化，不包括时间戳

**强制更新**：

```bash
# 删除旧HTML文件
rm docs/index.html

# 重新运行
python indicator/main.py
```

### Q5: 想在私密仓库使用GitHub Pages

**说明**：
- 免费账户：私有仓库的Pages也是私有的（仅自己可见）
- Pro/Team账户：可选公开或私有

**配置步骤相同**，访问权限由仓库设置决定。

## 📱 移动端访问

生成的页面完全支持移动设备：
- 📱 响应式布局
- 👆 触摸友好
- 🔄 自适应表格

直接在手机浏览器输入页面URL即可访问。

## 🎨 自定义页面样式

编辑 `indicator/html_generator.py` 中的CSS：

```python
# 找到 <style> 标签部分
# 修改颜色
background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);

# 修改字体
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", ...

# 修改布局
max-width: 1400px;  # 页面最大宽度
```

## 📞 获取帮助

### 1. 运行诊断

```bash
cd /home/ibn5100/Carmen
python indicator/test_github_pages.py
```

### 2. 查看日志

```bash
# 查看Git提交历史
git log gh-pages --oneline -10

# 查看GitHub部署状态
# 访问: https://github.com/<用户名>/Carmen/deployments
```

### 3. 检查分支

```bash
# 查看所有分支
git branch -a

# 切换到gh-pages查看内容
git checkout gh-pages
ls -la docs/
cat docs/index.html | head -20
git checkout main  # 切回主分支
```

## 📚 更多信息

- 📖 完整文档: `GITHUB_PAGES_SETUP.md`
- 🧪 测试脚本: `indicator/test_github_pages.py`
- ⚙️ 配置脚本: `setup_github_pages.sh`

## ✅ 验证清单

部署完成后，逐项检查：

- [ ] `gh-pages` 分支已创建
- [ ] 远程仓库已推送gh-pages分支
- [ ] GitHub Pages已启用
- [ ] Pages指向gh-pages分支
- [ ] 程序配置 `ENABLE_GITHUB_PAGES = True`
- [ ] 运行程序无错误
- [ ] 可以访问页面URL
- [ ] 页面显示最新数据
- [ ] 数据更新时自动推送
- [ ] 移动端显示正常

## 🎉 完成！

恭喜！您的股票扫描结果现在会自动发布到GitHub Pages。

**每次运行程序时**：
1. 扫描最新股票数据
2. 生成美观的HTML报告
3. 自动推送到GitHub
4. 页面自动更新

**无需手动操作**，一切都是自动的！

