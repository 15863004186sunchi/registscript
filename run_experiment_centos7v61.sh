#!/bin/bash
# =============================================================================
#  NAS 缓存乱码问题 —— 一键实验脚本
#  适用环境：CentOS 7.x（虚拟机即可）
#  用法：chmod +x run_experiment_centos7.sh && sudo ./run_experiment_centos7.sh
# =============================================================================

set -e  # 任何命令失败立即退出

# ── 颜色定义 ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ── 路径配置（可按需修改）─────────────────────────────────────────────────────
NFS_EXPORT_DIR="/srv/nas_share"       # NFS 服务端共享目录（模拟 NAS 磁盘）
NFS_MOUNT_LONG="/mnt/nas_long_cache"  # 挂载点A：长缓存（复现乱码）
NFS_MOUNT_NOCACHE="/mnt/nas_nocache"  # 挂载点B：禁用缓存（验证修复）
TMP_DIR="/tmp/nas_convert_tmp"        # 编码转换临时目录
WORK_DIR="/tmp/nas_experiment"        # Java 编译工作目录
LOG_FILE="/tmp/nas_experiment.log"    # 完整日志文件

# ── 工具函数 ──────────────────────────────────────────────────────────────────
log()      { echo -e "${CYAN}[$(date '+%H:%M:%S')]${NC} $*" | tee -a "$LOG_FILE"; }
info()     { echo -e "${BLUE}${BOLD}[INFO]${NC} $*" | tee -a "$LOG_FILE"; }
ok()       { echo -e "${GREEN}${BOLD}[✓ OK]${NC} $*" | tee -a "$LOG_FILE"; }
warn()     { echo -e "${YELLOW}${BOLD}[WARN]${NC} $*" | tee -a "$LOG_FILE"; }
err()      { echo -e "${RED}${BOLD}[ERR]${NC} $*" | tee -a "$LOG_FILE"; }
section()  { echo -e "\n${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; \
             echo -e "${BOLD}${BLUE}  $*${NC}"; \
             echo -e "${BOLD}${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"; }

# root 检查
check_root() {
    if [[ $EUID -ne 0 ]]; then
        err "此脚本需要 root 权限（需要配置 NFS 和 drop_caches）"
        echo "请使用: sudo $0"
        exit 1
    fi
}

# ── 步骤1：安装依赖 ────────────────────────────────────────────────────────────
install_deps() {
    section "步骤1：检查并安装依赖"

    # CentOS 7 用 yum，包名与 Ubuntu 不同
    local pkgs=()
    command -v java  &>/dev/null || pkgs+=(java-1.8.0-openjdk-devel)
    command -v javac &>/dev/null || pkgs+=(java-1.8.0-openjdk-devel)
    # nfs-utils 同时包含服务端(nfsd)和客户端(mount.nfs)
    rpm -q nfs-utils &>/dev/null || pkgs+=(nfs-utils)
    # rpcbind 是 NFS 依赖的端口映射服务，CentOS 7 需要单独启动
    rpm -q rpcbind   &>/dev/null || pkgs+=(rpcbind)

    if [[ ${#pkgs[@]} -gt 0 ]]; then
        info "安装: ${pkgs[*]}"
        yum install -y -q "${pkgs[@]}"
        ok "依赖安装完成"
    else
        ok "所有依赖已就绪"
    fi

    local java_ver
    java_ver=$(java -version 2>&1 | head -1)
    log "Java 版本: $java_ver"
}

# ── 步骤2：配置 NFS 服务端 ─────────────────────────────────────────────────────
setup_nfs_server() {
    section "步骤2：配置 NFS 服务端（模拟 NAS 硬件）"

    # CentOS 7 默认开启 firewalld，会阻断本机 NFS loopback 连接
    # 实验环境直接关闭，生产环境应开放 nfs/mountd/rpc-bind 端口
    if systemctl is-active firewalld &>/dev/null; then
        warn "检测到 firewalld 正在运行，临时关闭以允许本机 NFS 挂载..."
        systemctl stop firewalld
        log "firewalld 已临时停止（脚本结束后可手动 systemctl start firewalld 恢复）"
    fi

    mkdir -p "$NFS_EXPORT_DIR"
    chmod 777 "$NFS_EXPORT_DIR"

    # CentOS 7 exports 格式：去掉 no_subtree_check（该选项在 CentOS nfs-utils 中不被识别）
    local export_line="$NFS_EXPORT_DIR *(rw,sync,no_root_squash)"
    if ! grep -qF "$NFS_EXPORT_DIR" /etc/exports 2>/dev/null; then
        echo "$export_line" >> /etc/exports
        log "已添加 NFS export: $export_line"
    else
        # 更新已有条目
        sed -i "\|$NFS_EXPORT_DIR|c\\$export_line" /etc/exports
        log "已更新 NFS export"
    fi

    # CentOS 7 的 NFS 服务名是 nfs（不是 nfs-kernel-server）
    # 同时需要先启动 rpcbind，否则 nfs 启动失败
    systemctl enable rpcbind &>/dev/null
    systemctl start  rpcbind
    systemctl enable nfs &>/dev/null
    systemctl restart nfs
    exportfs -ra

    ok "NFS 服务端启动完成，共享目录: $NFS_EXPORT_DIR"
    exportfs -v | grep "$NFS_EXPORT_DIR" | while IFS= read -r line; do log "Export: $line"; done
}

# ── 步骤3：挂载两个 NFS 客户端（不同缓存参数）────────────────────────────────
setup_nfs_mounts() {
    section "步骤3：挂载 NFS 客户端（两种缓存配置）"

    mkdir -p "$NFS_MOUNT_LONG" "$NFS_MOUNT_NOCACHE" "$TMP_DIR"

    # 先卸载（忽略未挂载的错误）
    umount -f "$NFS_MOUNT_LONG"    2>/dev/null || true
    umount -f "$NFS_MOUNT_NOCACHE" 2>/dev/null || true

    # 挂载A：长缓存，actimeo=60，用于稳定复现乱码
    mount -t nfs localhost:"$NFS_EXPORT_DIR" "$NFS_MOUNT_LONG" \
        -o "rw,actimeo=60,lookupcache=all"
    ok "挂载A（长缓存 actimeo=60s）: $NFS_MOUNT_LONG"

    # 挂载B：禁用缓存，用于验证修复
    mount -t nfs localhost:"$NFS_EXPORT_DIR" "$NFS_MOUNT_NOCACHE" \
        -o "rw,noac,lookupcache=none"
    ok "挂载B（禁用缓存 noac）:       $NFS_MOUNT_NOCACHE"

    log "当前挂载状态:"
    mount | grep "$NFS_EXPORT_DIR" | while read line; do log "  $line"; done
}

# ── 步骤4：写出 Java 源码并编译 ───────────────────────────────────────────────
compile_java() {
    section "步骤4：生成并编译 Java 实验程序"

    mkdir -p "$WORK_DIR"

    # 把 Java 源码内嵌在这里，运行时写出
    cat > "$WORK_DIR/NasCacheExperiment.java" << 'JAVA_EOF'
import java.io.*;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.TimeUnit;

public class NasCacheExperiment {

    // 注意：这里是 Java Unicode String，不是 GBK 字节
    // 变量名 TEST_CONTENT 更准确，GBK/UTF-8 只体现在 writeGbk()/writeUtf8() 的磁盘写入上
    static final String TEST_CONTENT =
        "这是一段测试内容，用于验证编码转换和缓存问题。" +
        "第二行数据。第三行数据。结尾标记END。";
    static final String SEP = new String(new char[55]).replace("\0", "=");
    static final SimpleDateFormat SDF = new SimpleDateFormat("HH:mm:ss.SSS");

    // 实验结果收集
    static final Map<String, Boolean> RESULTS = new LinkedHashMap<>();

    public static void main(String[] args) throws Exception {
        if (args.length < 4) {
            System.out.println("用法: java NasCacheExperiment <nas_long> <nas_nocache> <tmp> <classdir>");
            System.exit(1);
        }
        Path nasLong    = Paths.get(args[0]);
        Path nasNocache = Paths.get(args[1]);
        Path tmpDir     = Paths.get(args[2]);
        Path classDir   = Paths.get(args[3]);  // FileReader.class 所在目录

        log("NAS长缓存路径 : " + nasLong.toAbsolutePath());
        log("NAS禁缓存路径 : " + nasNocache.toAbsolutePath());
        log("临时转换路径  : " + tmpDir.toAbsolutePath());

        // 前置校验：确认 TEST_CONTENT 能被 GBK 完整编码再解码，否则实验结果不可信
        validateGbkRoundtrip();

        exp1_LocalBaseline(tmpDir);
        exp2_NasReproduce(nasLong, tmpDir, classDir);
        exp3a_SameNameNoFsync(nasLong, tmpDir);
        exp3b_SameNameFsync(nasLong, tmpDir);
        exp3c_SameNameSleep(nasLong, tmpDir);
        exp3d_Rename(nasLong, tmpDir);
        exp3e_Nocache(nasNocache, tmpDir);
        exp3f_DropCaches(nasLong, tmpDir);

        printSummary();
    }

    // ── 实验1：本地基线 ────────────────────────────────────────────────────
    static void exp1_LocalBaseline(Path tmpDir) throws Exception {
        header("实验1：本地基线 —— 排除编码转换代码本身的 bug");
        Path f = tmpDir.resolve("exp1_baseline.txt");
        writeGbk(f, TEST_CONTENT);
        String content = readGbk(f);
        writeUtf8(f, content, false);
        boolean ok = TEST_CONTENT.equals(readUtf8(f));
        RESULTS.put("实验1 本地基线", ok);
        result("实验1", ok,
            "本地同名覆盖后读取正常，编码转换逻辑无 bug",
            "本地也乱码！编码转换代码有 bug，先修代码再做后续实验");
    }

    // ── 实验2：NAS 复现（常驻进程持有 fd，稳定复现）─────────────────────
    //
    // 复现关键三要素：
    //   1. 读取进程在转换前已经 open 文件（预热 Page Cache）
    //   2. 读取进程不退出，持续 hold fd（模拟常驻服务）
    //   3. 用同一个 fd seek(0) 重读，OS 可能返回 Page Cache 旧数据
    //
    static void exp2_NasReproduce(Path nasDir, Path tmpDir, Path classDir) throws Exception {
        header("实验2：NAS 上完整复现生产流程（常驻读取进程 + fd hold）");

        Path nasFile    = nasDir.resolve("exp2_reproduce.txt");
        Path tmpFile    = tmpDir.resolve("exp2_reproduce.txt");
        Path readyFile  = tmpDir.resolve("exp2_ready.sig");
        Path goFile     = tmpDir.resolve("exp2_go.sig");
        Path resultFile = tmpDir.resolve("exp2_result.txt");
        Path javaExe    = findJava();

        // 清理上次信号文件
        Files.deleteIfExists(readyFile);
        Files.deleteIfExists(goFile);
        Files.deleteIfExists(resultFile);

        // Step1: 写入 GBK 原始文件（足够大，增大缓存命中概率）
        StringBuilder bigContent = new StringBuilder();
        for (int i = 0; i < 500; i++) bigContent.append(TEST_CONTENT);
        String largeGbkContent = bigContent.toString();
        writeGbk(nasFile, largeGbkContent);
        logFileInfo(nasFile, "写入GBK后");
        log("文件大小: " + Files.size(nasFile) + " bytes（足够大，确保 Page Cache 缓存）");

        // Step2: 启动常驻读取进程（后台），它会 open 文件预热缓存，然后等待 GO 信号
        log("[读取进程] 后台启动，预热文件到 Page Cache...");
        ProcessBuilder pb = new ProcessBuilder(
            javaExe.toString(), "-cp", classDir.toString(),
            "FileReaderDaemon",
            nasFile.toString(),
            "UTF-8",
            readyFile.toString(),
            goFile.toString(),
            resultFile.toString()
        );
        pb.redirectErrorStream(true);
        pb.redirectOutput(tmpDir.resolve("exp2_daemon.log").toFile());
        Process daemon = pb.start();

        // Step3: 等待读取进程完成预热（最多 15 秒）
        log("[主进程] 等待读取进程预热完成...");
        boolean ready = false;
        for (int i = 0; i < 150; i++) {
            if (Files.exists(readyFile)) { ready = true; break; }
            Thread.sleep(100);
        }
        if (!ready) {
            daemon.destroyForcibly();
            log("[实验2跳过] 读取进程预热超时，检查 " + tmpDir.resolve("exp2_daemon.log"));
            RESULTS.put("实验2 NAS复现", null);
            return;
        }
        log("[读取进程] 预热完成，GBK 数据已进入 Page Cache");

        // Step4: 执行转换（move → GBK转UTF-8 → 同名写回）
        log("[转换进程] 执行 move → GBK转UTF-8 → 同名写回...");
        Files.move(nasFile, tmpFile, StandardCopyOption.REPLACE_EXISTING);
        convertBack(tmpFile, nasFile, false);
        logFileInfo(nasFile, "转换写回后");

        // Step5: 发送 GO 信号，让读取进程用同一个 fd 重新读取
        log("[主进程] 发送 GO 信号，读取进程开始重读...");
        writeSignalFile(goFile, "GO");

        // Step6: 等待读取进程返回结果（最多 15 秒）
        boolean resultReady = false;
        for (int i = 0; i < 150; i++) {
            if (Files.exists(resultFile)) { resultReady = true; break; }
            Thread.sleep(100);
        }
        daemon.waitFor(5, TimeUnit.SECONDS);

        if (!resultReady) {
            log("[实验2跳过] 等待读取结果超时");
            RESULTS.put("实验2 NAS复现", null);
            return;
        }

        // Step7: 读取结果，与原始内容对比
        String result = readUtf8(resultFile);
        // result 里的 \n 被转义过，还原后和 largeGbkContent 比较
        String resultDecoded = result.replace("\\n", "\n");
        boolean ok = largeGbkContent.equals(resultDecoded);
        RESULTS.put("实验2 NAS复现", ok);

        // 打印可视化对比，直观展示乱码
        String preview = resultDecoded.substring(0, Math.min(100, resultDecoded.length()));
        String expected = largeGbkContent.substring(0, Math.min(100, largeGbkContent.length()));
        System.out.println();
        System.out.println("  ┌─────────────────────────────────────────────────────┐");
        System.out.println("  │              读取内容对比（前100字符）               │");
        System.out.println("  ├─────────────────────────────────────────────────────┤");
        System.out.println("  │ 期望内容: " + expected);
        System.out.println("  │ 实际读到: " + preview);
        System.out.println("  │ 前20字节hex: " + toHex(resultDecoded.substring(0, Math.min(20, resultDecoded.length()))));
        System.out.println("  │ 内容相同: " + (ok ? "✅ 是（缓存已更新）" : "❌ 否（读到旧GBK数据，乱码）"));
        System.out.println("  └─────────────────────────────────────────────────────┘");
        System.out.println();
        result("实验2", ok,
            "读取进程读到了正确的 UTF-8 数据（缓存已更新）",
            "读取进程读到了旧 GBK 数据 ✓ 成功复现！OS Page Cache 缓存了旧数据");
    }

    static Path findJava() {
        String javaHome = System.getProperty("java.home");
        if (javaHome != null) {
            Path candidate = Paths.get(javaHome, "bin", "java");
            if (Files.exists(candidate)) return candidate;
            candidate = Paths.get(javaHome, "..", "bin", "java").normalize();
            if (Files.exists(candidate)) return candidate;
        }
        return Paths.get("java");
    }

    static void writeSignalFile(Path p, String content) throws Exception {
        try (OutputStreamWriter w = new OutputStreamWriter(
                new FileOutputStream(p.toFile()), StandardCharsets.UTF_8)) {
            w.write(content); w.flush();
        }
    }

    static String toHex(String s) {
        byte[] bytes = s.getBytes(StandardCharsets.UTF_8);
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < Math.min(bytes.length, 20); i++)
            sb.append(String.format("%02X ", bytes[i]));
        return sb.toString();
    }

    // ── 实验3A：同名无fsync（基准，预期乱码）─────────────────────────────
    static void exp3a_SameNameNoFsync(Path nasDir, Path tmpDir) throws Exception {
        header("实验3A：同名写回 + 无fsync（基准，预期乱码）");
        Path nasFile = nasDir.resolve("exp3a.txt");
        Path tmpFile = tmpDir.resolve("exp3a.txt");
        writeGbk(nasFile, TEST_CONTENT);
        Files.move(nasFile, tmpFile, StandardCopyOption.REPLACE_EXISTING);
        convertBack(tmpFile, nasFile, false);
        boolean ok = TEST_CONTENT.equals(readUtf8(nasFile));
        RESULTS.put("实验3A 同名无fsync", ok);
        result("实验3A", ok,
            "正常（缓存未命中，建议多跑几次）",
            "乱码 ✓ 基准复现成功");
    }

    // ── 实验3B：同名 + fsync ───────────────────────────────────────────────
    static void exp3b_SameNameFsync(Path nasDir, Path tmpDir) throws Exception {
        header("实验3B：同名写回 + fsync（验证写端是否是根因）");
        Path nasFile = nasDir.resolve("exp3b.txt");
        Path tmpFile = tmpDir.resolve("exp3b.txt");
        writeGbk(nasFile, TEST_CONTENT);
        Files.move(nasFile, tmpFile, StandardCopyOption.REPLACE_EXISTING);
        convertBack(tmpFile, nasFile, true);  // 开启 fsync
        boolean ok = TEST_CONTENT.equals(readUtf8(nasFile));
        RESULTS.put("实验3B 同名+fsync", ok);
        result("实验3B", ok,
            "fsync后正常 ✓ 写端问题：flush()未等NAS落盘，加fsync可修复",
            "fsync后仍乱码 → 问题在读端Page Cache，fsync无效，继续看3C/3E");
    }

    // ── 实验3C：同名 + sleep 等待缓存超时 ────────────────────────────────
    static void exp3c_SameNameSleep(Path nasDir, Path tmpDir) throws Exception {
        int sec = 65;  // 超过 actimeo=60
        header("实验3C：同名写回 + sleep " + sec + "s（验证是否NFS缓存超时）");
        Path nasFile = nasDir.resolve("exp3c.txt");
        Path tmpFile = tmpDir.resolve("exp3c.txt");
        writeGbk(nasFile, TEST_CONTENT);
        Files.move(nasFile, tmpFile, StandardCopyOption.REPLACE_EXISTING);
        convertBack(tmpFile, nasFile, false);
        log("等待 " + sec + "s（NFS actimeo=60s 超时）...");
        for (int i = sec; i > 0; i -= 5) {
            System.out.printf("  倒计时 %3ds...\r", i);
            TimeUnit.SECONDS.sleep(Math.min(5, i));
        }
        System.out.println();
        boolean ok = TEST_CONTENT.equals(readUtf8(nasFile));
        RESULTS.put("实验3C 同名+sleep65s", ok);
        result("实验3C", ok,
            "等待后正常 ✓ 铁证：NFS attribute cache 超时失效，调 noac/actimeo 可修复",
            "等待后仍乱码 → 缓存时间更长或其他原因，继续看3E");
    }

    // ── 实验3D：改名写回（对照组）────────────────────────────────────────
    static void exp3d_Rename(Path nasDir, Path tmpDir) throws Exception {
        header("实验3D：改名写回（对照组，应与生产现象一致：正常）");
        Path nasFile        = nasDir.resolve("exp3d_original.txt");
        Path nasFileRenamed = nasDir.resolve("exp3d_utf8.txt");
        Path tmpFile        = tmpDir.resolve("exp3d_original.txt");
        writeGbk(nasFile, TEST_CONTENT);
        Files.move(nasFile, tmpFile, StandardCopyOption.REPLACE_EXISTING);
        writeUtf8(nasFileRenamed, readGbk(tmpFile), false);
        boolean ok = TEST_CONTENT.equals(readUtf8(nasFileRenamed));
        RESULTS.put("实验3D 改名写回", ok);
        result("实验3D", ok,
            "改名后正常 ✓ 与生产现象吻合，改名绕过了缓存key",
            "改名后也乱码 → 问题不在缓存key，需检查编码转换逻辑");
    }

    // ── 实验3E：noac 挂载点（禁用缓存）──────────────────────────────────
    static void exp3e_Nocache(Path nasDir, Path tmpDir) throws Exception {
        header("实验3E：noac挂载点同名写回（禁用缓存，应正常）");
        Path nasFile = nasDir.resolve("exp3e.txt");
        Path tmpFile = tmpDir.resolve("exp3e.txt");
        writeGbk(nasFile, TEST_CONTENT);
        Files.move(nasFile, tmpFile, StandardCopyOption.REPLACE_EXISTING);
        convertBack(tmpFile, nasFile, false);
        boolean ok = TEST_CONTENT.equals(readUtf8(nasFile));
        RESULTS.put("实验3E noac挂载", ok);
        result("实验3E", ok,
            "noac后正常 ✓ 铁证：禁用NFS缓存后问题消失，根因确认是NFS attribute cache",
            "noac后仍乱码 → 问题不在NFS缓存，可能是Java层stream复用或其他原因");
    }

    // ── 实验3F：drop_caches 手动清缓存 ────────────────────────────────────
    static void exp3f_DropCaches(Path nasDir, Path tmpDir) throws Exception {
        header("实验3F：同名写回 + drop_caches（直接清OS Page Cache）");
        Path nasFile = nasDir.resolve("exp3f.txt");
        Path tmpFile = tmpDir.resolve("exp3f.txt");
        writeGbk(nasFile, TEST_CONTENT);
        Files.move(nasFile, tmpFile, StandardCopyOption.REPLACE_EXISTING);
        convertBack(tmpFile, nasFile, false);

        boolean dropped = dropCaches();
        if (!dropped) {
            log("[跳过] drop_caches 执行失败（权限不足），跳过本实验");
            RESULTS.put("实验3F drop_caches", null == null ? false : true);
            return;
        }
        boolean ok = TEST_CONTENT.equals(readUtf8(nasFile));
        RESULTS.put("实验3F drop_caches", ok);
        result("实验3F", ok,
            "drop_caches后正常 ✓ 铁证：OS Page Cache持有旧GBK数据",
            "drop_caches后仍乱码 → 问题在NAS服务端缓存，非客户端OS缓存");
    }

    // ── 前置校验：TEST_CONTENT 能否被 GBK 完整编码 ────────────────────────
    static void validateGbkRoundtrip() throws Exception {
        Charset gbk = Charset.forName("GBK");

        // 1. 检查 GBK 编码器能否无损编码（不可编码的字符会被替换为 '?')
        byte[] gbkBytes = TEST_CONTENT.getBytes(gbk);
        String roundtrip = new String(gbkBytes, gbk);
        if (!TEST_CONTENT.equals(roundtrip)) {
            System.out.println("[前置校验失败] TEST_CONTENT 含有 GBK 无法表示的字符！");
            System.out.println("  原始内容  : " + TEST_CONTENT);
            System.out.println("  GBK往返后 : " + roundtrip);
            System.out.println("  请修改 TEST_CONTENT，只使用 GBK 字符集内的字符。");
            System.exit(2);
        }

        // 2. 检查 GBK 字节用 UTF-8 解码确实会乱码（若不乱码则实验无意义）
        String misread = new String(gbkBytes, StandardCharsets.UTF_8);
        if (TEST_CONTENT.equals(misread)) {
            System.out.println("[前置校验警告] GBK字节用UTF-8解码后内容相同，实验可能无法体现乱码！");
            System.out.println("  建议在 TEST_CONTENT 中加入更多中文字符。");
            // 不退出，仅警告
        }

        log("[前置校验通过] TEST_CONTENT 可被 GBK 完整编码，且 GBK 字节用 UTF-8 读取会乱码");
        log("  Unicode 原文   : " + TEST_CONTENT);
        log("  GBK 字节长度   : " + gbkBytes.length + " bytes");
        log("  UTF-8 字节长度 : " + TEST_CONTENT.getBytes(StandardCharsets.UTF_8).length + " bytes");
        log("  UTF-8误读结果  : " + misread.substring(0, Math.min(10, misread.length())) + "...(乱码)");
    }

    // ── 工具方法 ──────────────────────────────────────────────────────────
    static void writeGbk(Path p, String content) throws Exception {
        try (OutputStreamWriter w = new OutputStreamWriter(
                new FileOutputStream(p.toFile()), Charset.forName("GBK"))) {
            w.write(content); w.flush();
        }
    }

    static void writeUtf8(Path p, String content, boolean fsync) throws Exception {
        FileOutputStream fos = new FileOutputStream(p.toFile());
        try (OutputStreamWriter w = new OutputStreamWriter(fos, StandardCharsets.UTF_8)) {
            w.write(content); w.flush();
            if (fsync) { fos.getFD().sync(); log("[fsync] getFD().sync() 完成"); }
        }
    }

    static String readGbk(Path p) throws Exception {
        try (InputStreamReader r = new InputStreamReader(
                new FileInputStream(p.toFile()), Charset.forName("GBK"))) {
            return readAll(r);
        }
    }

    static String readUtf8(Path p) throws Exception {
        // 每次重新 open，排除 Java stream 复用问题
        try (InputStreamReader r = new InputStreamReader(
                new FileInputStream(p.toFile()), StandardCharsets.UTF_8)) {
            return readAll(r);
        }
    }

    static String readAll(Reader r) throws Exception {
        StringBuilder sb = new StringBuilder();
        char[] buf = new char[4096]; int n;
        while ((n = r.read(buf)) != -1) sb.append(buf, 0, n);
        return sb.toString();
    }

    static void convertBack(Path src, Path dst, boolean fsync) throws Exception {
        String content = readGbk(src);
        writeUtf8(dst, content, fsync);
        log("转换写回完成 → " + dst.getFileName());
    }

    static void logFileInfo(Path p, String label) throws Exception {
        if (!Files.exists(p)) { log("[" + label + "] 文件不存在"); return; }
        BasicFileAttributes a = Files.readAttributes(p, BasicFileAttributes.class);
        String inode = "N/A";
        try { inode = Files.getAttribute(p, "unix:ino").toString(); } catch (Exception ignored) {}
        log(String.format("[%s] size=%d bytes | inode=%s | mtime=%s",
            label, a.size(), inode,
            SDF.format(new Date(a.lastModifiedTime().toMillis()))));
    }

    static boolean dropCaches() {
        try {
            // Files.writeString() 是 Java 11+，这里用 Java 8 兼容写法
            try (FileWriter fw = new FileWriter("/proc/sys/vm/drop_caches")) {
                fw.write("3");
                fw.flush();
            }
            log("drop_caches 执行成功");
            return true;
        } catch (Exception e) {
            try {
                Process p = new ProcessBuilder("sudo","sh","-c","echo 3 > /proc/sys/vm/drop_caches")
                    .redirectErrorStream(true).start();
                boolean done = p.waitFor(3, TimeUnit.SECONDS);
                if (done && p.exitValue() == 0) { log("sudo drop_caches 执行成功"); return true; }
            } catch (Exception ignored) {}
            log("drop_caches 失败: " + e.getMessage());
            return false;
        }
    }

    static void header(String title) {
        System.out.println("\n" + SEP);
        System.out.println("  " + title);
        System.out.println(SEP);
    }

    static void result(String exp, boolean ok, String msgOk, String msgFail) {
        System.out.println();
        if (ok) System.out.println("  ✅ [" + exp + "] " + msgOk);
        else    System.out.println("  ❌ [" + exp + "] " + msgFail);
        System.out.println();
    }

    static void log(String msg) {
        System.out.println("  [" + SDF.format(new Date()) + "] " + msg);
    }

    static void printSummary() {
        String line = new String(new char[55]).replace("\0", "━");
        System.out.println("\n" + line);
        System.out.println("  实验汇总");
        System.out.println(line);
        RESULTS.forEach((name, ok) ->
            System.out.printf("  %s  %-28s%n", ok ? "✅" : "❌", name));
        System.out.println();

        // 自动给出结论
        Boolean r3a = RESULTS.get("实验3A 同名无fsync");
        Boolean r3b = RESULTS.get("实验3B 同名+fsync");
        Boolean r3c = RESULTS.get("实验3C 同名+sleep65s");
        Boolean r3d = RESULTS.get("实验3D 改名写回");
        Boolean r3e = RESULTS.get("实验3E noac挂载");
        Boolean r3f = RESULTS.get("实验3F drop_caches");

        System.out.println("  ── 自动诊断结论 ──");
        if (Boolean.FALSE.equals(r3a) && Boolean.TRUE.equals(r3e)) {
            System.out.println("  🎯 根因确认：NFS attribute cache 导致读端命中旧数据");
            System.out.println("     修复：挂载加 noac 参数，或写端加 fsync");
        }
        if (Boolean.FALSE.equals(r3a) && Boolean.TRUE.equals(r3b)) {
            System.out.println("  🎯 根因确认：写端 flush() 不足，NAS 未及时落盘");
            System.out.println("     修复：flush() 改为 getFD().sync()");
        }
        if (Boolean.FALSE.equals(r3a) && Boolean.TRUE.equals(r3c)) {
            System.out.println("  🎯 根因确认：NFS attribute cache 超时（actimeo=60s 后自动失效）");
            System.out.println("     修复：挂载加 actimeo=1 或 noac");
        }
        if (Boolean.FALSE.equals(r3a) && Boolean.TRUE.equals(r3f)) {
            System.out.println("  🎯 根因确认：OS Page Cache 缓存了旧 GBK 数据");
        }
        if (Boolean.TRUE.equals(r3d) && Boolean.FALSE.equals(r3a)) {
            System.out.println("  🎯 与生产现象完全吻合：改名绕过缓存key → 正常");
        }
        System.out.println(line);
    }
}
JAVA_EOF

    info "编译 Java 源码..."
    javac -encoding UTF-8 "$WORK_DIR/NasCacheExperiment.java" -d "$WORK_DIR"
    ok "编译成功: $WORK_DIR/NasCacheExperiment.class"

    # 编译辅助程序：独立进程读取文件，用于实验2双进程复现
    cat > "$WORK_DIR/FileReader.java" << 'READER_EOF'
import java.io.*;
import java.nio.charset.Charset;
import java.nio.file.*;

// 独立进程：读取指定文件并把内容输出到 stdout
// 用法: java FileReader <filepath> <charset>
// 作为独立进程运行，每次都从磁盘（或OS Cache）重新读取，不受调用方进程缓存影响
public class FileReader {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) { System.exit(1); }
        Path path    = Paths.get(args[0]);
        Charset cs   = Charset.forName(args[1]);
        try (InputStreamReader r = new InputStreamReader(
                new FileInputStream(path.toFile()), cs)) {
            char[] buf = new char[4096]; int n;
            StringBuilder sb = new StringBuilder();
            while ((n = r.read(buf)) != -1) sb.append(buf, 0, n);
            // 单行输出，方便调用方 readLine() 接收
            System.out.print(sb.toString().replace("\n", "\\n").replace("\r", ""));
        }
    }
}
READER_EOF
    javac -encoding UTF-8 "$WORK_DIR/FileReader.java" -d "$WORK_DIR"
    ok "编译成功: $WORK_DIR/FileReader.class"

    # 编译辅助程序2：常驻读取进程，持续 hold 住文件句柄，模拟生产中的常驻服务
    # 协议：
    #   启动后读取文件内容写入 READY_FILE，表示已预热完毕
    #   主进程写入 GO_FILE 后，再次读取同一文件写入 RESULT_FILE
    cat > "$WORK_DIR/FileReaderDaemon.java" << 'DAEMON_EOF'
import java.io.*;
import java.nio.charset.*;
import java.nio.file.*;

// 常驻读取进程，模拟生产中的长驻服务持有文件句柄
// 用法: java FileReaderDaemon <targetFile> <charset> <readyFile> <goFile> <resultFile>
public class FileReaderDaemon {
    public static void main(String[] args) throws Exception {
        Path targetFile = Paths.get(args[0]);
        Charset cs      = Charset.forName(args[1]);
        Path readyFile  = Paths.get(args[2]);  // 写入此文件表示预热完成
        Path goFile     = Paths.get(args[3]);  // 等待此文件出现后再次读取
        Path resultFile = Paths.get(args[4]);  // 把第二次读取结果写入此文件

        // Step1: 打开文件，读取内容（预热 Page Cache），保持 fd 打开
        FileInputStream fis = new FileInputStream(targetFile.toFile());
        InputStreamReader reader = new InputStreamReader(fis, cs);
        String firstRead = readAll(reader);

        // Step2: 把预热完成信号写出去（不关闭 fis，fd 仍然持有）
        writeSignal(readyFile, "READY:" + firstRead.length());

        // Step3: 等待主进程发出 GO 信号（转换完成后才会写 goFile）
        for (int i = 0; i < 300; i++) {  // 最多等 30 秒
            if (Files.exists(goFile)) break;
            Thread.sleep(100);
        }

        // Step4: 重新 seek 到文件头，用同一个 fd 再读一次
        // 这是关键：同一个 fd，不关闭重开，OS 可能仍然返回 Page Cache 里的旧数据
        fis.getChannel().position(0);
        reader = new InputStreamReader(fis, cs);
        String secondRead = readAll(reader);

        // Step5: 把结果写出去，主进程来读
        writeSignal(resultFile, secondRead);
        fis.close();
    }

    static String readAll(InputStreamReader r) throws Exception {
        StringBuilder sb = new StringBuilder();
        char[] buf = new char[4096]; int n;
        while ((n = r.read(buf)) != -1) sb.append(buf, 0, n);
        return sb.toString();
    }

    static void writeSignal(Path p, String content) throws Exception {
        try (OutputStreamWriter w = new OutputStreamWriter(
                new FileOutputStream(p.toFile()), StandardCharsets.UTF_8)) {
            w.write(content); w.flush();
        }
    }
}
DAEMON_EOF
    javac -encoding UTF-8 "$WORK_DIR/FileReaderDaemon.java" -d "$WORK_DIR"
    ok "编译成功: $WORK_DIR/FileReaderDaemon.class"
}

# ── 步骤5：运行实验 ────────────────────────────────────────────────────────────
run_experiments() {
    section "步骤5：运行所有实验"

    info "日志同步写入: $LOG_FILE"
    echo "" >> "$LOG_FILE"
    echo "===== 实验开始 $(date) =====" >> "$LOG_FILE"

    java -cp "$WORK_DIR" NasCacheExperiment \
        "$NFS_MOUNT_LONG" \
        "$NFS_MOUNT_NOCACHE" \
        "$TMP_DIR" \
        "$WORK_DIR" \
        2>&1 | tee -a "$LOG_FILE"
}

# ── 步骤6：清理环境（可选）────────────────────────────────────────────────────
cleanup() {
    section "清理实验环境"
    read -rp "  是否清理所有实验文件和 NFS 挂载？[y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        umount -f "$NFS_MOUNT_LONG"    2>/dev/null || true
        umount -f "$NFS_MOUNT_NOCACHE" 2>/dev/null || true
        rm -rf "$NFS_EXPORT_DIR"/* "$TMP_DIR" "$WORK_DIR"
        sed -i "\|$NFS_EXPORT_DIR|d" /etc/exports
        exportfs -ra
        ok "清理完成"
    else
        info "跳过清理，挂载点和文件保留"
    fi
}

# ── 前置清理：幂等，无论是否首次运行都安全 ────────────────────────────────────
pre_clean() {
    section "前置清理：重置为干净初始状态"

    # 1. 卸载挂载点（-f 强制，-l lazy，两者组合应对 stale NFS）
    for mnt in "$NFS_MOUNT_LONG" "$NFS_MOUNT_NOCACHE"; do
        if mountpoint -q "$mnt" 2>/dev/null; then
            umount -f -l "$mnt" 2>/dev/null && log "已卸载: $mnt" || warn "卸载失败（忽略）: $mnt"
        else
            log "未挂载，跳过: $mnt"
        fi
    done

    # 2. 清理上次实验残留文件（保留目录结构）
    if [[ -d "$NFS_EXPORT_DIR" ]]; then
        rm -f "$NFS_EXPORT_DIR"/exp*.txt
        log "已清理 NFS 共享目录残留文件: $NFS_EXPORT_DIR"
    fi
    if [[ -d "$TMP_DIR" ]]; then
        rm -f "$TMP_DIR"/exp*.txt
        log "已清理临时目录残留文件: $TMP_DIR"
    fi
    if [[ -d "$WORK_DIR" ]]; then
        rm -f "$WORK_DIR"/*.class
        log "已清理上次编译产物: $WORK_DIR/*.class"
    fi

    # 3. 去重 /etc/exports（防止多次运行重复追加）
    if [[ -f /etc/exports ]]; then
        # 删除所有含 NFS_EXPORT_DIR 的行，后续 setup_nfs_server 会重新写入
        sed -i "\|$NFS_EXPORT_DIR|d" /etc/exports
        log "已清理 /etc/exports 中的旧条目"
    fi

    ok "前置清理完成，环境已归零"
}

# ── 主流程 ─────────────────────────────────────────────────────────────────────
main() {
    clear
    echo -e "${BOLD}${CYAN}"
    echo "  ╔══════════════════════════════════════════════════════╗"
    echo "  ║    NAS 缓存乱码问题 —— 一键实验脚本                 ║"
    echo "  ║    适用环境：CentOS 7.x                             ║"
    echo "  ╚══════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    > "$LOG_FILE"  # 清空日志

    check_root
    pre_clean       # ← 每次运行都先清理，保证幂等
    install_deps
    setup_nfs_server
    setup_nfs_mounts
    compile_java
    run_experiments
    cleanup

    echo ""
    ok "全部完成！完整日志: $LOG_FILE"
}

main "$@"
