# GitHub Pages 自动发布配置指南

本文档将指导您如何配置GitHub Pages，实现股票扫描结果的自动发布。

## 📋 功能说明

- ✅ **自动检测内容变化**：通过MD5哈希对比，只在数据有变化时才推送
- ✅ **独立分支管理**：使用`gh-pages`分支存放HTML，不污染主代码仓库
- ✅ **实时自动推送**：每次数据更新后自动推送到GitHub
- ✅ **美观的展示页面**：响应式设计，支持移动端访问

## 🚀 快速开始

### 步骤 1: 配置 Git 环境

确保您的Git仓库已正确配置：

```bash
# 检查Git配置
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"

# 确认远程仓库
cd /home/ibn5100/Carmen
git remote -v
```

### 步骤 2: 创建 gh-pages 分支

程序会自动创建`gh-pages`分支，但您也可以手动创建：

```bash
# 创建并切换到孤立分支
git checkout --orphan gh-pages

# 删除所有文件
git rm -rf .

# 创建初始提交
git commit --allow-empty -m "Initialize GitHub Pages"

# 推送到远程
git push -u origin gh-pages

# 切回主分支
git checkout main  # 或 master
```

### 步骤 3: 启用 GitHub Pages

1. 访问您的GitHub仓库页面
2. 点击 **Settings** (设置)
3. 在左侧菜单找到 **Pages**
4. 在 **Source** 下拉菜单中选择：
   - Branch: `gh-pages`
   - Folder: `/ (root)` 
5. 点击 **Save** (保存)

![GitHub Pages设置示例](https://docs.github.com/assets/images/help/pages/publishing-source-dropdown.png)

### 步骤 4: 配置程序参数

编辑 `indicator/main.py`，确认以下配置：

```python
# GitHub Pages 配置
ENABLE_GITHUB_PAGES = True   # 启用自动推送
GITHUB_BRANCH = 'gh-pages'   # 分支名称
```

### 步骤 5: 运行程序

```bash
cd /home/ibn5100/Carmen/indicator
python main.py
```

程序会自动：
1. 扫描股票数据
2. 生成HTML报告到 `docs/index.html`
3. 检测内容是否有变化
4. 如有变化，自动推送到 `gh-pages` 分支
5. GitHub Pages 自动更新（通常需要1-2分钟）

## 🌐 访问您的页面

推送成功后，您的页面地址为：

```
https://<你的GitHub用户名>.github.io/Carmen/
```

例如：
- 用户名: `john`
- 仓库名: `Carmen`
- 页面地址: `https://john.github.io/Carmen/`

程序会自动显示您的页面URL。

## ⚙️ 高级配置

### 自定义分支名称

如果您想使用不同的分支名：

```python
# 在 main.py 中修改
GITHUB_BRANCH = 'my-custom-branch'
```

然后在GitHub Pages设置中选择该分支。

### 禁用自动推送

如果暂时不需要自动推送：

```python
# 在 main.py 中修改
ENABLE_GITHUB_PAGES = False
```

### 自定义HTML输出路径

编辑 `indicator/main.py`，在初始化GitPublisher时修改：

```python
git_publisher = GitPublisher(
    branch=github_branch,
    html_file='custom/path/report.html'  # 自定义路径
)
```

## 🔧 故障排除

### 问题 1: 推送失败，提示 "Permission denied"

**解决方案**：配置SSH密钥或使用Personal Access Token

```bash
# 方法1: 使用SSH (推荐)
ssh-keygen -t ed25519 -C "your.email@example.com"
cat ~/.ssh/id_ed25519.pub  # 复制公钥到GitHub

# 方法2: 使用HTTPS + Token
git remote set-url origin https://<TOKEN>@github.com/username/Carmen.git
```

### 问题 2: 页面显示404

**检查清单**：
1. ✅ GitHub Pages是否已启用
2. ✅ 分支选择是否正确 (`gh-pages`)
3. ✅ HTML文件是否在分支根目录或docs文件夹
4. ✅ 等待1-2分钟让GitHub处理

### 问题 3: 推送成功但页面内容未更新

**解决方案**：
1. 清除浏览器缓存 (Ctrl+Shift+R 强制刷新)
2. 等待GitHub Pages构建完成（可能需要5分钟）
3. 检查 `https://github.com/username/Carmen/deployments` 查看部署状态

### 问题 4: Git未安装或不可用

**解决方案**：

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install git

# 验证安装
git --version
```

### 问题 5: 内容明明变化了，但显示"无变化"

程序使用MD5哈希检测内容变化，只关注关键数据（股票列表、价格、指标）。如果只是时间戳变化，不会触发推送。

如需强制推送，可手动删除旧HTML：

```bash
rm docs/index.html
```

## 📊 工作流程说明

```
┌─────────────────┐
│  运行 main.py   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  扫描股票数据   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  生成HTML报告   │
│ (docs/index.html)│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  计算内容哈希   │
│   与旧版本对比   │
└────────┬────────┘
         │
    内容有变化？
         │
    Yes  │  No
         ▼
┌─────────────────┐     ┌──────────────┐
│ 切换到gh-pages  │     │   跳过推送   │
│  复制HTML文件   │     └──────────────┘
│   Git commit    │
│   Git push      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ GitHub Pages    │
│  自动部署页面   │
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  访问公开URL    │
└─────────────────┘
```

## 🔒 安全建议

### 1. 使用Private Repository（可选）

如果股票数据敏感，建议使用私有仓库：
- Private Repo + GitHub Pages = 仅您可访问
- Public Repo + GitHub Pages = 所有人可访问

### 2. 不要提交API密钥

确保 `.gitignore` 包含敏感文件：

```gitignore
# .gitignore
*.env
*_api_key.txt
secrets.json
```

### 3. 使用环境变量

将API密钥存储在环境变量中：

```bash
export ALPHA_VANTAGE_KEY="your_api_key"
```

## 📱 移动端访问

生成的HTML页面完全响应式，支持手机访问：
- 自动适配屏幕宽度
- 优化表格显示
- 触摸友好的界面

## 🎨 自定义样式

如需修改页面样式，编辑 `indicator/html_generator.py` 中的CSS部分：

```python
# 找到 <style> 标签，修改颜色、字体等
body {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    ...
}
```

## 📞 获取帮助

如果遇到问题：

1. 检查程序输出的错误信息
2. 运行测试命令：
   ```bash
   cd /home/ibn5100/Carmen/indicator
   python -c "from git_publisher import test_publisher; test_publisher()"
   ```
3. 查看GitHub仓库的Actions/Deployments状态
4. 检查Git日志：
   ```bash
   git log gh-pages --oneline -10
   ```

## ✅ 验证清单

部署完成后，检查以下项目：

- [ ] Git环境配置正确
- [ ] `gh-pages` 分支已创建
- [ ] GitHub Pages已启用并指向正确分支
- [ ] 程序可以成功生成HTML
- [ ] 推送到GitHub无错误
- [ ] 可以通过浏览器访问页面
- [ ] 页面显示最新数据
- [ ] 移动端显示正常

## 🎉 完成！

恭喜！您已成功配置GitHub Pages自动发布。程序现在会：
- 持续监控股票数据
- 检测到变化时自动更新页面
- 将结果发布到公开/私有的GitHub Pages

每天盘前/盘后的扫描结果都会自动更新到您的专属页面！

