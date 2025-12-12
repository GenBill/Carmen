# 镜像网络模式直接使用 127.0.0.1，NAT模式从 resolv.conf 获取
hostip=$(cat /etc/resolv.conf | grep -oP '(?<=nameserver\ ).*')
if [[ "$hostip" == "127.0.0.42" ]]; then
    hostip="127.0.0.1"
fi
export hostip
export http_proxy="http://${hostip}:7897"
export https_proxy="http://${hostip}:7897"
export HTTP_PROXY="http://${hostip}:7897"
export HTTPS_PROXY="http://${hostip}:7897"

# Node.js 代理配置 (for Gemini CLI etc.)
export GLOBAL_AGENT_HTTP_PROXY="http://${hostip}:7897"
export NODE_OPTIONS="--require $(npm root -g)/global-agent/bootstrap.js"
