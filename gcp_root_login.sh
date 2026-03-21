#!/usr/bin/env bash
# =============================================================
# gcp_root_login.sh — 谷歌云 (GCP) 开启 Root 远程登录脚本
# 用途: 自动配置 PermitRootLogin 和 PasswordAuthentication
# 使用: sudo bash gcp_root_login.sh
# =============================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# 1. 权限检查
[[ $EUID -ne 0 ]] && error "请以 root 权限运行: sudo bash $0"

# 2. 修改 SSH 配置文件
SSH_CONFIG="/etc/ssh/sshd_config"

info "正在备份并修改 ${SSH_CONFIG}..."
cp "${SSH_CONFIG}" "${SSH_CONFIG}.bak_$(date +%Y%m%d_%H%M%S)"

# 修改 PermitRootLogin
if grep -q "^#\?PermitRootLogin" "${SSH_CONFIG}"; then
    sed -i "s|^#\?PermitRootLogin.*|PermitRootLogin yes|" "${SSH_CONFIG}"
else
    echo "PermitRootLogin yes" >> "${SSH_CONFIG}"
fi

# 修改 PasswordAuthentication
if grep -q "^#\?PasswordAuthentication" "${SSH_CONFIG}"; then
    sed -i "s|^#\?PasswordAuthentication.*|PasswordAuthentication yes|" "${SSH_CONFIG}"
else
    echo "PasswordAuthentication yes" >> "${SSH_CONFIG}"
fi

# 3. 重启 SSH 服务
info "正在重启 SSH 服务..."
if command -v systemctl &>/dev/null; then
    systemctl restart sshd
else
    service sshd restart
fi

echo ""
info "✅ SSH 配置已更新！"
info "------------------------------------------------"
warn "请立即运行以下命令设置 root 密码："
echo -e "      ${YELLOW}passwd root${NC}"
info "------------------------------------------------"
info "设置完成后，即可使用 Xshell 通过 root 账号登录了。"
