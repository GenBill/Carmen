"""
Git自动推送模块
将生成的HTML自动推送到GitHub Pages分支（独立目录模式）
"""

import subprocess
import os
from datetime import datetime
from typing import Optional


class GitPublisher:
    """Git自动推送器（独立目录模式）"""
    
    def __init__(self, repo_path: str = None, gh_pages_dir: str = None, force_push: bool = False):
        """
        初始化Git推送器
        
        Args:
            repo_path: 主仓库路径，默认为当前目录的父目录
            gh_pages_dir: gh-pages独立目录路径，默认为 repo_path/gh-pages
            force_push: 是否强制推送，覆盖远端内容
        """
        self.repo_path = repo_path or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.gh_pages_dir = gh_pages_dir or os.path.join(self.repo_path, 'gh-pages')
        self.force_push = force_push
        
        # 源文件路径
        self.html_file = os.path.join(self.repo_path, 'docs/index.html')
        self.html_hka_file = os.path.join(self.repo_path, 'docs/index_hka.html')
        self.meta_file = os.path.join(self.repo_path, 'docs/meta.json')
        self.meta_hka_file = os.path.join(self.repo_path, 'docs/meta_hka.json')
        
        # 目标文件路径
        self.target_docs_dir = os.path.join(self.gh_pages_dir, 'docs')
        
    def _run_command(self, cmd: list, cwd: str = None) -> tuple:
        """
        运行shell命令
        
        Returns:
            tuple: (success: bool, output: str)
        """
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd or self.repo_path,
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, str(e)
    
    def check_git_available(self) -> bool:
        """检查Git是否可用"""
        success, _ = self._run_command(['git', '--version'])
        return success
    
    def check_gh_pages_dir_exists(self) -> bool:
        """检查gh-pages目录是否存在"""
        return os.path.exists(self.gh_pages_dir) and os.path.isdir(self.gh_pages_dir)
    
    def publish(self, commit_message: Optional[str] = None, force_push: Optional[bool] = None) -> bool:
        """
        发布HTML到GitHub Pages
        
        Args:
            commit_message: 提交信息，默认为自动生成
            force_push: 是否强制推送，覆盖远端内容。如果为None，使用初始化时的设置
            
        Returns:
            bool: 是否成功推送
        """
        
        # 检查Git环境
        if not self.check_git_available():
            print("❌ Git未安装或不可用")
            return False
        
        # 检查gh-pages目录
        if not self.check_gh_pages_dir_exists():
            print(f"❌ gh-pages目录不存在: {self.gh_pages_dir}")
            print(f"💡 请先创建gh-pages目录:")
            print(f"   cd {self.repo_path}")
            print(f"   git worktree add gh-pages gh-pages")
            return False
        
        # 检查HTML文件是否存在
        if not os.path.exists(self.html_file):
            print(f"❌ HTML文件不存在: {self.html_file}")
            return False
        if not os.path.exists(self.html_hka_file):
            print(f"❌ HTML文件不存在: {self.html_hka_file}")
            return False
        
        # print(f"\n{'='*60}")
        # print(f"📤 开始推送到 GitHub Pages...")
        # print(f"{'='*60}")
        
        try:
            # print(f"📁 gh-pages目录: {self.gh_pages_dir}")
            
            # 确定是否使用强制推送
            use_force_push = force_push if force_push is not None else self.force_push
            
            # 确保目标目录存在
            os.makedirs(self.target_docs_dir, exist_ok=True)
            
            # 复制HTML文件
            import shutil
            
            # 复制美股HTML
            if os.path.exists(self.html_file):
                target_html = os.path.join(self.target_docs_dir, 'index.html')
                shutil.copy2(self.html_file, target_html)
            
            # 复制港A股HTML
            if os.path.exists(self.html_hka_file):
                target_html_hka = os.path.join(self.target_docs_dir, 'index_hka.html')
                shutil.copy2(self.html_hka_file, target_html_hka)
            
            # 复制meta文件（如果存在）
            if os.path.exists(self.meta_file):
                target_meta = os.path.join(self.target_docs_dir, 'meta.json')
                shutil.copy2(self.meta_file, target_meta)
            
            if os.path.exists(self.meta_hka_file):
                target_meta_hka = os.path.join(self.target_docs_dir, 'meta_hka.json')
                shutil.copy2(self.meta_hka_file, target_meta_hka)
            
            # 添加文件到Git
            # print(f"\n📝 添加文件到暂存区...")
            success, output = self._run_command(['git', 'add', 'docs/'], cwd=self.gh_pages_dir)
            if not success:
                print(f"❌ 添加文件失败: {output}")
                return False
            
            # 检查是否有变更
            success, _ = self._run_command(['git', 'diff', '--cached', '--quiet'], cwd=self.gh_pages_dir)
            if success:
                print("ℹ️  没有变更需要提交")
                return True
            
            # 提交
            if commit_message is None:
                commit_message = f"Update stock report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            # print(f"💾 提交变更: {commit_message}")
            success, output = self._run_command(['git', 'commit', '-m', commit_message], cwd=self.gh_pages_dir)
            if not success:
                print(f"❌ 提交失败: {output}")
                return False
            
            # 推送到远程
            # print(f"🚀 推送到远程仓库...")
            if use_force_push:
                # 使用强制推送，覆盖远端内容
                success, output = self._run_command(['git', 'push', '--force-with-lease'], cwd=self.gh_pages_dir)
                if not success:
                    # 如果--force-with-lease失败，尝试--force
                    print(f"⚠️  --force-with-lease失败，尝试--force: {output}")
                    success, output = self._run_command(['git', 'push', '--force'], cwd=self.gh_pages_dir)
            else:
                # 正常推送
                success, output = self._run_command(['git', 'push'], cwd=self.gh_pages_dir)
            
            if not success:
                print(f"❌ 推送失败: {output}")
                print(f"💡 提示: 请确保已配置远程仓库和推送权限")
                return False
            
            print(f"✅ 成功推送到 GitHub Pages!")
            # print(f"🌐 您的页面将在几分钟后更新")
            
            return True
            
        except Exception as e:
            print(f"❌ 推送过程出错: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # finally:
        #     print(f"{'='*60}\n")
    
    def get_pages_url(self) -> Optional[str]:
        """
        获取GitHub Pages URL
        
        Returns:
            str: GitHub Pages URL，失败返回None
        """
        # 从gh-pages目录获取远程仓库URL
        success, output = self._run_command(['git', 'remote', 'get-url', 'origin'], cwd=self.gh_pages_dir)
        if not success:
            return None
        
        remote_url = output.strip()
        
        # 解析仓库信息
        # 支持格式: https://github.com/user/repo.git 或 git@github.com:user/repo.git
        if 'github.com' in remote_url:
            if remote_url.startswith('https://'):
                # https://github.com/user/repo.git -> user/repo
                parts = remote_url.replace('https://github.com/', '').replace('.git', '').split('/')
            elif remote_url.startswith('git@'):
                # git@github.com:user/repo.git -> user/repo
                parts = remote_url.replace('git@github.com:', '').replace('.git', '').split('/')
            else:
                return None
            
            if len(parts) >= 2:
                user, repo = parts[0], parts[1]
                return f"https://{user}.github.io/{repo}/"
        
        return None


def test_publisher():
    """测试推送功能"""
    publisher = GitPublisher()
    
    print("🧪 测试Git推送模块")
    print(f"主仓库路径: {publisher.repo_path}")
    print(f"gh-pages目录: {publisher.gh_pages_dir}")
    print(f"HTML文件: {publisher.html_file}")
    
    # 检查Git环境
    if publisher.check_git_available():
        print("✅ Git可用")
    else:
        print("❌ Git不可用")
        return
    
    if publisher.check_gh_pages_dir_exists():
        print("✅ gh-pages目录存在")
    else:
        print("❌ gh-pages目录不存在")
        print(f"💡 创建方法: git worktree add gh-pages gh-pages")
        return
    
    # 获取Pages URL
    url = publisher.get_pages_url()
    if url:
        print(f"🌐 GitHub Pages URL: {url}")
    else:
        print("ℹ️  无法确定GitHub Pages URL")


if __name__ == '__main__':
    test_publisher()
