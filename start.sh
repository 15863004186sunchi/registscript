#!/bin/bash

# ================= 配置区 =================
# 程序文件名
APP_NAME="openai_registerv10.py"
# 日志文件名
LOG_FILE="openai_registerv10.log"
# Python解释器
PYTHON_CMD="python3"
# ==========================================

# 获取进程PID
get_pid() {
    echo $(ps -ef | grep "$APP_NAME" | grep -v grep | awk '{print $2}')
}

# 归档 JSON 文件为 ZIP (新功能)
archive_json() {
    # 检查是否安装了 zip
    if ! command -v zip &> /dev/null; then
        echo "❌ 错误: 未检测到 zip 命令。"
        echo "   请先运行: sudo yum install -y zip"
        return
    fi

    # 检查当前目录下是否有 json 文件
    count=$(ls *.json 2>/dev/null | wc -l)
    
    if [ "$count" -eq "0" ]; then
        echo "📭 当前目录无 JSON 文件，跳过归档。"
        return
    fi

    # 生成时间戳
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    DIR_NAME="result_${TIMESTAMP}"
    # 这里后缀改成了 .zip
    ARCHIVE_NAME="${DIR_NAME}.zip"

    echo "📦 发现 $count 个 JSON 文件，准备归档..."

    # 1. 创建文件夹
    mkdir -p "$DIR_NAME"

    # 2. 移动文件
    mv *.json "$DIR_NAME/"

    # 3. 压缩文件夹 (使用 zip -r 递归压缩)
    echo "🗜️ 正在生成压缩包: $ARCHIVE_NAME"
    # -r 表示递归目录，-q 表示静默模式(不刷屏)
    zip -r -q "$ARCHIVE_NAME" "$DIR_NAME"

    # 4. 删除临时文件夹，只保留压缩包
    rm -rf "$DIR_NAME"

    echo "✅ 归档完成，文件已保存为: $ARCHIVE_NAME"
}

# 启动
start() {
    pid=$(get_pid)
    if [ -n "$pid" ]; then
        echo "⚠️  程序 $APP_NAME 已经在运行中，PID: $pid"
    else
        echo "🚀 正在启动 $APP_NAME ..."
        nohup $PYTHON_CMD -u $APP_NAME > $LOG_FILE 2>&1 &
        
        sleep 1
        new_pid=$(get_pid)
        echo "✅ 启动成功! PID: $new_pid"
        echo "📝 日志写入: $LOG_FILE"
    fi
}

# 停止
stop() {
    pid=$(get_pid)
    if [ -z "$pid" ]; then
        echo "⚠️  程序 $APP_NAME 未运行"
        # 即使没运行，也尝试归档残留文件
        archive_json
    else
        echo "🛑 正在停止 $APP_NAME (PID: $pid) ..."
        kill $pid
        
        sleep 1
        if [ -z "$(get_pid)" ]; then
            echo "✅ 进程已停止"
        else
            echo "❌ 软停止失败，尝试强制停止..."
            kill -9 $pid
            echo "✅ 已强制停止"
        fi
        
        # 🛑 停止后执行归档 🛑
        archive_json
    fi
}

# 重启
restart() {
    stop
    sleep 1
    start
}

# 查看状态
status() {
    pid=$(get_pid)
    if [ -n "$pid" ]; then
        echo "✅ 程序正在运行，PID: $pid"
    else
        echo "⚪ 程序未运行"
    fi
}

# 查看日志
view_log() {
    echo "📜 正在查看日志 (按 Ctrl+C 退出)..."
    tail -f $LOG_FILE
}

# 命令判断
case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    log)
        view_log
        ;;
    *)
        echo "使用方法: $0 {start|stop|restart|status|log}"
        exit 1
        ;;
esac
