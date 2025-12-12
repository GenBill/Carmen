import os
import re
import socket
import subprocess
import urllib.request
import urllib.error

def get_hostip():
    """从 /etc/resolv.conf 获取 hostip"""
    try:
        result = subprocess.run(
            ['cat', '/etc/resolv.conf'],
            capture_output=True,
            text=True,
            check=True
        )
        match = re.search(r'nameserver\s+(.+)', result.stdout)
        if match:
            hostip = match.group(1).strip()
            if hostip == '127.0.0.42':
                hostip = '127.0.0.1'
            return hostip
    except Exception:
        pass
    return None

def check_google_connectivity():
    """检查是否能连接到Google"""
    try:
        req = urllib.request.Request('https://www.google.com.tw', method='HEAD')
        urllib.request.urlopen(req, timeout=3)
        return True
    except (urllib.error.URLError, socket.timeout, Exception):
        return False
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex(('www.google.com.tw', 443))
        sock.close()
        return result == 0
    except Exception:
        return False

def setup_proxy_if_needed(clash_port=7897):
    """自动检测网络连接，如无法连接Google则设置proxy"""
    if check_google_connectivity():
        return
    
    hostip = get_hostip()
    if hostip:
        proxy_url = f'http://{hostip}:{clash_port}'
        # 使用小写的环境变量名，与shell脚本保持一致
        os.environ['http_proxy'] = proxy_url
        os.environ['https_proxy'] = proxy_url
        # 同时设置大写版本，确保兼容性
        os.environ['HTTP_PROXY'] = proxy_url
        os.environ['HTTPS_PROXY'] = proxy_url
    else:
        print("警告: 无法获取hostip，proxy设置可能失败")

if __name__ == "__main__":

    clash_port = 7897
    setup_proxy_if_needed(clash_port)
