export hostip=$(cat /etc/resolv.conf |grep -oP '(?<=nameserver\ ).*')
export https_proxy="http://${hostip}:7897"
export http_proxy="http://${hostip}:7897"