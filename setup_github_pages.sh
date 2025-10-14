#!/bin/bash

# GitHub Pages 快速配置脚本
# 用于初始化 gh-pages 分支和配置环境

set -e  # 遇到错误立即退出

echo "======================================================================"
echo "  Carmen Stock Scanner - GitHub Pages 快速配置"
echo "======================================================================"
echo ""

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 检查Git是否安装
if ! command -v git &> /dev/null; then
    echo -e "${RED}❌ Git未安装，请先安装Git${NC}"
    echo "   Ubuntu/Debian: sudo apt-get install git"
    exit 1
fi

echo -e "${GREEN}✅ Git已安装${NC}"

# 检查是否在Git仓库中
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo -e "${RED}❌ 当前目录不是Git仓库${NC}"
    echo "   请先初始化Git仓库: git init"
    exit 1
fi

echo -e "${GREEN}✅ Git仓库存在${NC}"

# 检查远程仓库
REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
if [ -z "$REMOTE_URL" ]; then
    echo -e "${YELLOW}⚠️  未配置远程仓库${NC}"
    echo ""
    echo "请添加远程仓库："
    echo "  git remote add origin https://github.com/您的用户名/Carmen.git"
    echo "  或"
    echo "  git remote add origin git@github.com:您的用户名/Carmen.git"
    echo ""
    read -p "是否继续（不推送到远程）？ [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
    SKIP_PUSH=true
else
    echo -e "${GREEN}✅ 远程仓库: ${REMOTE_URL}${NC}"
    SKIP_PUSH=false
fi

# 保存当前分支
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo -e "${GREEN}📍 当前分支: ${CURRENT_BRANCH}${NC}"

# 检查是否有未提交的更改
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    echo -e "${YELLOW}⚠️  检测到未提交的更改${NC}"
    echo ""
    git status --short
    echo ""
    read -p "是否暂存这些更改？ [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git stash push -m "Stashed before gh-pages setup"
        echo -e "${GREEN}✅ 已暂存更改${NC}"
        STASHED=true
    else
        echo -e "${YELLOW}⚠️  未暂存的更改可能影响分支切换${NC}"
        STASHED=false
    fi
else
    STASHED=false
fi

# 检查gh-pages分支是否存在
echo ""
echo "🔍 检查 gh-pages 分支..."

if git show-ref --verify --quiet refs/heads/gh-pages; then
    echo -e "${YELLOW}⚠️  本地 gh-pages 分支已存在${NC}"
    read -p "是否重新创建？ [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git branch -D gh-pages
        echo -e "${GREEN}✅ 已删除旧分支${NC}"
        CREATE_BRANCH=true
    else
        CREATE_BRANCH=false
    fi
else
    CREATE_BRANCH=true
fi

if [ "$CREATE_BRANCH" = true ]; then
    echo ""
    echo "🌱 创建 gh-pages 分支..."
    
    # 创建孤立分支
    git checkout --orphan gh-pages
    
    # 清空所有文件
    git rm -rf . 2>/dev/null || true
    
    # 创建 docs 目录
    mkdir -p docs
    
    # 创建占位HTML（防止空分支）
    cat > docs/index.html << 'EOF'
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Carmen Stock Scanner</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            text-align: center;
        }
        h1 {
            color: #2a5298;
            margin-bottom: 20px;
        }
        p {
            color: #6c757d;
            line-height: 1.6;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Carmen Stock Scanner</h1>
        <p>页面正在初始化...</p>
        <p>请运行程序生成第一份报告</p>
    </div>
</body>
</html>
EOF
    
    # 提交
    git add docs/index.html
    git commit -m "Initialize GitHub Pages"
    
    echo -e "${GREEN}✅ gh-pages 分支创建成功${NC}"
    
    # 推送到远程
    if [ "$SKIP_PUSH" = false ]; then
        echo ""
        echo "🚀 推送到远程仓库..."
        if git push -u origin gh-pages; then
            echo -e "${GREEN}✅ 推送成功${NC}"
        else
            echo -e "${RED}❌ 推送失败，请检查权限${NC}"
            echo "   您可以稍后手动推送: git push -u origin gh-pages"
        fi
    fi
fi

# 切回原分支
echo ""
echo "🔙 切回原分支 ${CURRENT_BRANCH}..."
git checkout "$CURRENT_BRANCH"

# 恢复暂存的更改
if [ "$STASHED" = true ]; then
    echo "📦 恢复暂存的更改..."
    git stash pop
fi

# 创建配置文件（如果不存在）
echo ""
echo "📝 检查配置文件..."

CONFIG_FILE="indicator/main.py"
if grep -q "ENABLE_GITHUB_PAGES" "$CONFIG_FILE"; then
    echo -e "${GREEN}✅ 配置文件已包含 GitHub Pages 设置${NC}"
else
    echo -e "${YELLOW}⚠️  配置文件可能需要更新${NC}"
    echo "   请确保 main.py 包含以下配置："
    echo "   ENABLE_GITHUB_PAGES = True"
    echo "   GITHUB_BRANCH = 'gh-pages'"
fi

# 显示下一步操作
echo ""
echo "======================================================================"
echo -e "${GREEN}✅ 配置完成！${NC}"
echo "======================================================================"
echo ""
echo "📋 下一步操作："
echo ""
echo "1️⃣  启用 GitHub Pages："
echo "   - 访问 https://github.com/您的用户名/Carmen/settings/pages"
echo "   - Source 选择: gh-pages 分支"
echo "   - Folder 选择: / (root)"
echo "   - 点击 Save"
echo ""
echo "2️⃣  运行程序："
echo "   cd indicator"
echo "   python main.py"
echo ""
echo "3️⃣  访问您的页面："

if [ "$SKIP_PUSH" = false ]; then
    # 尝试从远程URL提取用户名和仓库名
    if [[ $REMOTE_URL =~ github.com[:/]([^/]+)/([^/.]+) ]]; then
        USERNAME="${BASH_REMATCH[1]}"
        REPO="${BASH_REMATCH[2]}"
        echo "   https://${USERNAME}.github.io/${REPO}/"
    else
        echo "   https://<用户名>.github.io/Carmen/"
    fi
else
    echo "   https://<用户名>.github.io/Carmen/"
fi

echo ""
echo "📖 详细文档: 查看 GITHUB_PAGES_SETUP.md"
echo ""
echo "======================================================================"

