#!/usr/bin/env bash
# =============================================================
# setup_env.sh — CentOS 10 环境准备脚本
# 用途: 在运行 openai_register.py 之前一键配置所有依赖
# 使用: chmod +x setup_env.sh && sudo bash setup_env.sh
# =============================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# 必须以 root 或 sudo 运行
[[ $EUID -ne 0 ]] && error "请以 root 权限运行: sudo bash $0"

# ------------------------------------------------------------------
# 1. 更新软件包索引
# ------------------------------------------------------------------
info "更新 dnf 软件包索引..."
dnf makecache -q

# ------------------------------------------------------------------
# 2. 安装基础工具: zip / unzip / curl / wget / git
# ------------------------------------------------------------------
info "安装基础工具 (zip, curl, wget, git)..."
dnf install -y zip unzip curl wget git

# ------------------------------------------------------------------
# 3. 确保 Python 3 可用，并安装 pip
# ------------------------------------------------------------------
info "检查 Python 3 环境..."
if ! command -v python3 &>/dev/null; then
    info "Python3 未找到，正在安装 python3..."
    dnf install -y python3
fi

PYTHON_VER=$(python3 --version)
info "当前 Python 版本: ${PYTHON_VER}"

info "安装 python3-pip..."
dnf install -y python3-pip

# 升级 pip 到最新版本
info "升级 pip 到最新版本..."
python3 -m pip install --upgrade pip -q

# ------------------------------------------------------------------
# 4. 安装编译依赖 (curl_cffi 需要 libcurl 开发头文件)
# ------------------------------------------------------------------
info "安装 curl_cffi 所需的编译依赖..."
dnf install -y libcurl-devel openssl-devel gcc python3-devel

# ------------------------------------------------------------------
# 5. 安装 Python 依赖包: curl_cffi 和 Faker
# ------------------------------------------------------------------
info "安装 curl_cffi..."
python3 -m pip install curl_cffi -q

info "安装 Faker..."
python3 -m pip install faker -q

# 可选：一次性从 requirements.txt 安装（如果存在）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/requirements.txt" ]]; then
    info "发现 requirements.txt，正在安装..."
    python3 -m pip install -r "${SCRIPT_DIR}/requirements.txt" -q
fi

# ------------------------------------------------------------------
# 6. 安装 Docker
# ------------------------------------------------------------------
info "安装 Docker..."

# 移除旧版本（忽略报错）
dnf remove -y docker \
    docker-client \
    docker-client-latest \
    docker-common \
    docker-latest \
    docker-latest-logrotate \
    docker-logrotate \
    docker-engine 2>/dev/null || true

# 添加 Docker 官方 repo
dnf install -y dnf-plugins-core
dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

# 安装 Docker Engine（与官方文档对齐）
dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 启动并设置开机自启
systemctl enable --now docker
info "Docker 已启动并设置为开机自启"

# 将当前登录用户加入 docker 组（免 sudo 使用 docker）
REAL_USER="${SUDO_USER:-}"
if [[ -n "$REAL_USER" ]]; then
    usermod -aG docker "$REAL_USER"
    warn "已将用户 '${REAL_USER}' 加入 docker 组。重新登录后生效，或执行: newgrp docker"
fi

# ------------------------------------------------------------------
# 7. 验证安装结果
# ------------------------------------------------------------------
echo ""
info "===== 安装验证 ====="
echo -n "  Python3 : "; python3 --version
echo -n "  pip     : "; python3 -m pip --version
echo -n "  zip     : "; zip --version | head -1
echo -n "  Docker  : "; docker --version
echo -n "  curl_cffi: "; python3 -c "import curl_cffi; print(curl_cffi.__version__)"
echo -n "  Faker    : "; python3 -c "import faker; print(faker.VERSION)"
echo ""
info "✅ 所有依赖安装完成，可以运行 openai_register.py 了！"
info "   运行命令: python3 openai_register.py --proxy 'http://your-proxy:port'"
