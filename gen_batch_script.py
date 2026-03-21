import re
import sys

with open('e:/AILearn/codex/registscript/run_experiment_centos7v6.sh', 'r', encoding='utf-8') as f:
    sh_content = f.read()

with open('e:/AILearn/codex/registscript/NasCacheExperiment.java', 'r', encoding='utf-8') as f:
    java_content = f.read()

start_marker = "cat > \"$WORK_DIR/NasCacheExperiment.java\" << 'JAVA_EOF'\n"
end_marker = "\nJAVA_EOF\n"

start_idx = sh_content.find(start_marker) + len(start_marker)
end_idx = sh_content.find(end_marker, start_idx)

if start_idx > -1 and end_idx > -1:
    sh_content = sh_content[:start_idx] + java_content + sh_content[end_idx:]

sh_content = re.sub(r"    # 编译辅助程序：独立进程.*?READER_EOF\n    javac[^\n]+\n    ok[^\n]+\n\n", "", sh_content, flags=re.DOTALL)
sh_content = re.sub(r"    # 编译辅助程序2：常驻读取进程.*?DAEMON_EOF\n    javac[^\n]+\n    ok[^\n]+\n", "", sh_content, flags=re.DOTALL)

old_run_exp = """run_experiments() {
    section "步骤5：运行所有实验"

    info "日志同步写入: $LOG_FILE"
    echo "" >> "$LOG_FILE"
    echo "===== 实验开始 $(date) =====" >> "$LOG_FILE"

    java -cp "$WORK_DIR" NasCacheExperiment \\
        "$NFS_MOUNT_LONG" \\
        "$NFS_MOUNT_NOCACHE" \\
        "$TMP_DIR" \\
        "$WORK_DIR" \\
        2>&1 | tee -a "$LOG_FILE"
}"""

new_run_exp = """run_experiments() {
    section "步骤5：分批次执行不同大小的实验"

    info "日志同步写入: $LOG_FILE"
    echo "" >> "$LOG_FILE"
    echo "===== 实验开始 $(date) =====" >> "$LOG_FILE"

    local sizes=(10 100 500 1000 5000)
    for size in "${sizes[@]}"; do
        section "开始实验，文件倍数因子: ${size}"
        java -cp "$WORK_DIR" NasCacheExperiment \\
            "$NFS_MOUNT_LONG" \\
            "$NFS_MOUNT_NOCACHE" \\
            "$TMP_DIR" \\
            "$WORK_DIR" \\
            "${size}" \\
            2>&1 | tee -a "$LOG_FILE"
    done
}"""

sh_content = sh_content.replace(old_run_exp, new_run_exp)
sh_content = sh_content.replace(
    "NAS 缓存乱码问题 —— 一键实验脚本", 
    "NAS 缓存乱码问题 —— 一键实验脚本 (批量大小版)"
)

with open('e:/AILearn/codex/registscript/run_experiment_batch_size.sh', 'w', encoding='utf-8', newline='\n') as f:
    f.write(sh_content)
