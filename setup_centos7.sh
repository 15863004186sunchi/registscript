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

# 2. 安装 EPEL 及 SCL 仓库 (SCL 项目能为 CentOS 7 提供更高版本的 Python)
info "正在配置仓库并安装基础编译工具..."
yum install -y epel-release centos-release-scl
yum install -y wget curl git zip unzip gcc openssl-devel libffi-devel make

# 3. 安装 Python 3.8 (通过 SCL)
info "正在通过 SCL 安装 Python 3.8..."
yum install -y rh-python38 rh-python38-python-devel rh-python38-python-pip

if [ ! -d "/opt/rh/rh-python38" ]; then
    error "rh-python38 安装失败，请检查网络或 YUM 源配置。"
fi

# 启用 Python 3.8 环境
# 注意：在脚本后续部分需要使用完整的 python 路径或 source enable
export PATH="/opt/rh/rh-python38/root/usr/bin:$PATH"
export LD_LIBRARY_PATH="/opt/rh/rh-python38/root/usr/lib64:$LD_LIBRARY_PATH"

PYTHON_EXE="/opt/rh/rh-python38/root/usr/bin/python3"
PIP_EXE="/opt/rh/rh-python38/root/usr/bin/pip3"

PYTHON_VER=$($PYTHON_EXE --version)
info "当前 Python 版本: ${PYTHON_VER} (from SCL)"

# 4. 升级 pip 并安装 cffi 预填依赖
info "正在升级 pip 并预装 cffi..."
$PYTHON_EXE -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
$PYTHON_EXE -m pip install cffi -i https://pypi.tuna.tsinghua.edu.cn/simple

# 5. 安装核心依赖
info "正在安装 Python 依赖包 (curl_cffi, Faker)..."
$PYTHON_EXE -m pip install requests faker -i https://pypi.tuna.tsinghua.edu.cn/simple

# 特别处理 curl_cffi
info "正在尝试安装最新版 curl_cffi..."
if $PYTHON_EXE -m pip install curl_cffi -i https://pypi.tuna.tsinghua.edu.cn/simple; then
    info "✅ curl_cffi 安装成功！"
else
    warn "❌ curl_cffi 自动安装失败。"
    warn "   由于 CentOS 7 的 GLIBC 版本过低，可能无法直接运行 curl_cffi 的二进制包。"
    warn "   建议方案：使用 Docker 运行脚本（见项目中的 docker-compose.yml）"
fi

# 6. 验证
echo ""
info "===== 安装验证 ====="
echo -n "  Python3 : "; $PYTHON_EXE --version
echo -n "  pip     : "; $PIP_EXE --version
echo -n "  curl_cffi: "; $PYTHON_EXE -c "import curl_cffi; print(curl_cffi.__version__)" 2>/dev/null || echo "FAIL"

info "✅ 环境配置完成！"
info "   ！！！注意：以后运行脚本请使用以下命令（或先执行 source /opt/rh/rh-python38/enable）："
info "   $PYTHON_EXE openai_registerv10.py --proxy 'http://your-proxy:port'"

info "✅ 基础环境配置完成！"
info "   如果 curl_cffi 导入报错，请优先考虑在本地或 Docker 环境运行。"
info "   运行命令: python3 openai_registerv10.py --proxy 'http://your-proxy:port'"
