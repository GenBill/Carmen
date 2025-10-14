"""
Git自动推送模块
将生成的HTML自动推送到GitHub Pages分支
"""

import subprocess
import os
from datetime import datetime
from typing import Optional


class GitPublisher:
    """Git自动推送器"""
    
    def __init__(self, repo_path: str = None, branch: str = 'gh-pages', 
                 html_file: str = 'docs/index.html'):
        """
        初始化Git推送器
        
        Args:
            repo_path: Git仓库路径，默认为当前目录的父目录
            branch: 目标分支名，默认为gh-pages
            html_file: HTML文件路径（相对于repo_path）
        """
        self.repo_path = repo_path or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.branch = branch
        self.html_file = html_file
        self.html_full_path = os.path.join(self.repo_path, html_file)
        
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
    
    def check_repo_exists(self) -> bool:
        """检查是否在Git仓库中"""
        success, _ = self._run_command(['git', 'rev-parse', '--git-dir'])
        return success
    
    def init_gh_pages_branch(self) -> bool:
        """
        初始化gh-pages分支（如果不存在）
        
        Returns:
            bool: 是否成功
        """
        print(f"🔍 检查 {self.branch} 分支是否存在...")
        
        # 检查远程分支是否存在
        success, output = self._run_command(['git', 'ls-remote', '--heads', 'origin', self.branch])
        
        if self.branch in output:
            print(f"✅ 远程 {self.branch} 分支已存在")
            
            # 检查本地分支
            success, output = self._run_command(['git', 'rev-parse', '--verify', self.branch])
            if not success:
                # 本地分支不存在，从远程拉取
                print(f"📥 从远程拉取 {self.branch} 分支...")
                success, output = self._run_command(['git', 'fetch', 'origin', f'{self.branch}:{self.branch}'])
                if not success:
                    print(f"❌ 拉取失败: {output}")
                    return False
            return True
        else:
            # 创建新的孤立分支
            print(f"🌱 创建新的 {self.branch} 分支...")
            
            # 保存当前分支
            success, current_branch = self._run_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
            if not success:
                print(f"❌ 无法获取当前分支: {current_branch}")
                return False
            current_branch = current_branch.strip()
            
            # 创建孤立分支
            commands = [
                ['git', 'checkout', '--orphan', self.branch],
                ['git', 'rm', '-rf', '.'],
                ['git', 'commit', '--allow-empty', '-m', 'Initialize GitHub Pages'],
                ['git', 'push', '-u', 'origin', self.branch],
                ['git', 'checkout', current_branch]
            ]
            
            for cmd in commands:
                success, output = self._run_command(cmd)
                if not success and 'git rm' not in ' '.join(cmd):
                    # git rm 可能失败（空仓库），忽略该错误
                    print(f"❌ 命令失败: {' '.join(cmd)}")
                    print(f"   错误: {output}")
                    # 尝试恢复到原分支
                    self._run_command(['git', 'checkout', current_branch])
                    return False
            
            print(f"✅ {self.branch} 分支创建成功")
            return True
    
    def publish(self, commit_message: Optional[str] = None) -> bool:
        """
        发布HTML到GitHub Pages
        
        Args:
            commit_message: 提交信息，默认为自动生成
            
        Returns:
            bool: 是否成功推送
        """
        
        # 检查Git环境
        if not self.check_git_available():
            print("❌ Git未安装或不可用")
            return False
        
        if not self.check_repo_exists():
            print("❌ 当前目录不是Git仓库")
            return False
        
        # 检查HTML文件是否存在
        if not os.path.exists(self.html_full_path):
            print(f"❌ HTML文件不存在: {self.html_full_path}")
            return False
        
        print(f"\n{'='*60}")
        print(f"📤 开始推送到 GitHub Pages...")
        print(f"{'='*60}")
        
        # 保存当前分支
        success, current_branch = self._run_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
        if not success:
            print(f"❌ 无法获取当前分支")
            return False
        current_branch = current_branch.strip()
        
        # 保存当前工作目录状态
        success, status = self._run_command(['git', 'status', '--porcelain'])
        has_uncommitted = bool(status.strip())
        
        try:
            # 切换到gh-pages分支
            print(f"🔄 切换到 {self.branch} 分支...")
            success, output = self._run_command(['git', 'checkout', self.branch])
            if not success:
                print(f"❌ 切换分支失败: {output}")
                print(f"💡 尝试初始化 {self.branch} 分支...")
                if not self.init_gh_pages_branch():
                    return False
                success, output = self._run_command(['git', 'checkout', self.branch])
                if not success:
                    print(f"❌ 切换分支仍然失败: {output}")
                    return False
            
            # 从主分支复制HTML文件到gh-pages分支
            import shutil
            
            # 确保目标目录存在
            target_dir = os.path.dirname(self.html_file) if os.path.dirname(self.html_file) else '.'
            target_path = os.path.join(self.repo_path, target_dir)
            os.makedirs(target_path, exist_ok=True)
            
            # 复制文件（从临时位置）
            # 由于我们切换了分支，需要使用git show来获取文件内容
            temp_html = f'/tmp/carmen_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html'
            
            # 先切回原分支获取文件
            self._run_command(['git', 'checkout', current_branch])
            if os.path.exists(self.html_full_path):
                shutil.copy2(self.html_full_path, temp_html)
            else:
                print(f"❌ HTML文件在原分支中不存在")
                return False
            
            # 再切到gh-pages
            self._run_command(['git', 'checkout', self.branch])
            
            # 复制到目标位置
            target_file = os.path.join(self.repo_path, self.html_file)
            shutil.copy2(temp_html, target_file)
            os.remove(temp_html)
            
            # 同时复制meta.json文件（如果存在）
            html_dir = os.path.dirname(self.html_file)
            meta_file = os.path.join(html_dir, 'meta.json') if html_dir else 'meta.json'
            source_meta = os.path.join(self.repo_path, meta_file)
            
            # 切回原分支获取meta.json
            self._run_command(['git', 'checkout', current_branch])
            if os.path.exists(source_meta):
                temp_meta = f'/tmp/carmen_meta_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
                shutil.copy2(source_meta, temp_meta)
                
                # 切回gh-pages
                self._run_command(['git', 'checkout', self.branch])
                target_meta = os.path.join(self.repo_path, meta_file)
                shutil.copy2(temp_meta, target_meta)
                os.remove(temp_meta)
                print(f"📝 已复制meta信息文件")
            else:
                # 切回gh-pages
                self._run_command(['git', 'checkout', self.branch])
            
            # 添加文件
            print(f"📝 添加文件到暂存区...")
            success, output = self._run_command(['git', 'add', self.html_file])
            if not success:
                print(f"❌ 添加文件失败: {output}")
                return False
            
            # 如果meta.json存在，也添加它
            if os.path.exists(os.path.join(self.repo_path, meta_file)):
                self._run_command(['git', 'add', meta_file])
            
            # 检查是否有变更
            success, diff = self._run_command(['git', 'diff', '--cached', '--quiet'])
            if success:
                print("ℹ️  没有变更需要提交")
                self._run_command(['git', 'checkout', current_branch])
                return True
            
            # 提交
            if commit_message is None:
                commit_message = f"Update stock report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            print(f"💾 提交变更: {commit_message}")
            success, output = self._run_command(['git', 'commit', '-m', commit_message])
            if not success:
                print(f"❌ 提交失败: {output}")
                return False
            
            # 推送到远程
            print(f"🚀 推送到远程仓库...")
            success, output = self._run_command(['git', 'push', 'origin', self.branch])
            if not success:
                print(f"❌ 推送失败: {output}")
                print(f"💡 提示: 请确保已配置远程仓库和推送权限")
                return False
            
            print(f"✅ 成功推送到 GitHub Pages!")
            print(f"🌐 您的页面将在几分钟后更新")
            
            return True
            
        except Exception as e:
            print(f"❌ 推送过程出错: {e}")
            return False
            
        finally:
            # 恢复到原分支
            print(f"🔙 恢复到原分支 {current_branch}...")
            self._run_command(['git', 'checkout', current_branch])
            print(f"{'='*60}\n")
    
    def get_pages_url(self) -> Optional[str]:
        """
        获取GitHub Pages URL
        
        Returns:
            str: GitHub Pages URL，失败返回None
        """
        # 获取远程仓库URL
        success, output = self._run_command(['git', 'remote', 'get-url', 'origin'])
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
    print(f"仓库路径: {publisher.repo_path}")
    print(f"目标分支: {publisher.branch}")
    print(f"HTML文件: {publisher.html_file}")
    
    # 检查Git环境
    if publisher.check_git_available():
        print("✅ Git可用")
    else:
        print("❌ Git不可用")
        return
    
    if publisher.check_repo_exists():
        print("✅ Git仓库存在")
    else:
        print("❌ 不在Git仓库中")
        return
    
    # 获取Pages URL
    url = publisher.get_pages_url()
    if url:
        print(f"🌐 GitHub Pages URL: {url}")
    else:
        print("ℹ️  无法确定GitHub Pages URL")


if __name__ == '__main__':
    test_publisher()

