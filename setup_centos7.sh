#!/usr/bin/env bash
# =============================================================
# setup_centos7.sh — CentOS 7 环境一键准备脚本
# 用途: 在 CentOS 7 上安装 Python3 及注册脚本所需的依赖 (curl_cffi, Faker)
# 使用: chmod +x setup_centos7.sh && sudo ./setup_centos7.sh
# =============================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# 1. 权限检查
[[ $EUID -ne 0 ]] && error "请以 root 权限运行: sudo bash $0"

# 2. 安装 EPEL 及 基础工具
info "正在配置 EPEL 仓库并安装基础工具 (wget, curl, git)..."
yum install -y epel-release
yum install -y wget curl git zip unzip gcc openssl-devel libffi-devel

# 3. 安装 Python 3 (CentOS 7 默认仓库通常提供 3.6，EPEL 可能提供 3.9)
info "正在安装 Python 3.6..."
yum install -y python3 python3-pip python3-devel

if ! command -v python3 &>/dev/null; then
    error "Python3 安装失败，请检查网络或 YUM 源配置。"
fi

PYTHON_VER=$(python3 --version)
info "当前 Python 版本: ${PYTHON_VER}"

# 4. 升级 pip
info "正在升级 pip..."
python3 -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple

# 5. 安装核心依赖
info "正在安装 Python 依赖包 (curl_cffi, Faker)..."
# 使用清华源加速国内下载，如果是国外机器可去掉 -i 参数
python3 -m pip install requests faker -i https://pypi.tuna.tsinghua.edu.cn/simple

# 特别处理 curl_cffi: 
# curl_cffi 在 CentOS 7 这种老旧系统上可能存在 GLIBC 版本不兼容问题。
# 我们先尝试直接安装预编译包，如果不行则输出警告。
info "正在尝试安装 curl_cffi (可能耗时较长)..."
if python3 -m pip install curl_cffi -i https://pypi.tuna.tsinghua.edu.cn/simple; then
    info "✅ curl_cffi 安装成功！"
else
    warn "❌ curl_cffi 自动安装失败。这通常是由于 CentOS 7 的 GLIBC 版本过低导致的。"
    warn "   建议方案：使用 Docker 运行脚本（见 README 或 docker-compose.yml），"
    warn "   或者在更高版本的 Linux (如 CentOS 8, Ubuntu 20.04+) 上运行。"
fi

# 6. 验证
echo ""
info "===== 安装验证 ====="
echo -n "  Python3 : "; python3 --version
echo -n "  pip     : "; python3 -m pip --version
echo -n "  Faker   : "; python3 -c "import faker; print('OK')" 2>/dev/null || echo "FAIL"

info "✅ 基础环境配置完成！"
info "   如果 curl_cffi 导入报错，请优先考虑在本地或 Docker 环境运行。"
info "   运行命令: python3 openai_registerv10.py --proxy 'http://your-proxy:port'"
