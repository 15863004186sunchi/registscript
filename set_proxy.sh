#!/usr/bin/env bash
# =============================================================
# set_proxy.sh — 一键配置虚拟机走宿主机代理
# 用途: 自动配置系统环境变量、YUM 代理以及 GIT 代理
# 使用: chmod +x set_proxy.sh && sudo ./set_proxy.sh <宿主机IP> <端口>
# 示例: sudo ./set_proxy.sh 192.168.137.1 7890
# =============================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# 1. 参数检查
if [ "$#" -ne 2 ]; then
    echo "使用方法: $0 <宿主机IP> <端口>"
    echo "示例: $0 192.168.137.1 7890"
    exit 1
fi

HOST_IP=$1
PORT=$2
PROXY_URL="http://${HOST_IP}:${PORT}"

# 2. 权限检查
[[ $EUID -ne 0 ]] && error "请以 root 权限运行: sudo bash $0"

# 3. 设置 YUM 代理 (持久化)
info "正在配置 /etc/yum.conf 代理..."
if grep -q "proxy=" /etc/yum.conf; then
    sed -i "s|proxy=.*|proxy=${PROXY_URL}|" /etc/yum.conf
else
    echo "proxy=${PROXY_URL}" >> /etc/yum.conf
fi

# 4. 设置系统环境变量 (持久化到 /etc/profile.d/proxy.sh)
info "正在配置系统全局环境变量..."
cat > /etc/profile.d/openai_proxy.sh <<EOF
export http_proxy="${PROXY_URL}"
export https_proxy="${PROXY_URL}"
export no_proxy="localhost,127.0.0.1,localaddress,.localdomain.com"
EOF

# 5. 设置 Git 全局代理
if command -v git &>/dev/null; then
    info "正在配置 Git 全局代理..."
    git config --global http.proxy "${PROXY_URL}"
    git config --global https.proxy "${PROXY_URL}"
fi

# 6. 生效当前会话
export http_proxy="${PROXY_URL}"
export https_proxy="${PROXY_URL}"

echo ""
info "✅ 代理配置完成！"
echo "------------------------------------------------"
echo "  当前代理: ${PROXY_URL}"
echo "  YUM 代理: 已写入 /etc/yum.conf"
echo "  系统变量: 已写入 /etc/profile.d/openai_proxy.sh"
echo "------------------------------------------------"
info "提示: 请执行 'source /etc/profile' 或重新登录使环境变量全局生效。"
info "测试连接: curl -I https://www.google.com"
