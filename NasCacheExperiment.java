import java.io.*;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.concurrent.TimeUnit;

/**
 * NAS 文件缓存问题验证实验
 *
 * 实验目标：用「控制变量法」证明乱码是由 NAS 客户端缓存导致，而非编码转换本身的问题。
 *
 * 使用方式：
 *   javac NasCacheExperiment.java
 *   java NasCacheExperiment <nas_path> <tmp_path>
 *
 *   nas_path: NAS 挂载目录，如 /mnt/nas/testdir
 *   tmp_path: 本地或 NAS 临时目录，如 /tmp/convert_tmp
 *
 * 实验设计：
 *   实验1 - 基线验证：纯本地文件系统，排除编码转换逻辑本身的 bug
 *   实验2 - 复现问题：在 NAS 上同名写回，观察乱码
 *   实验3 - 精确定位：在实验2的基础上，分别插入"sleep等缓存过期"、
 *            "drop_caches"、"改名"三种手段，看哪种能恢复正常
 */
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
            System.out.println("用法: java NasCacheExperiment <nas_long> <nas_nocache> <tmp> <classdir> [sizeMultiplier]");
            System.exit(1);
        }
        Path nasLong    = Paths.get(args[0]);
        Path nasNocache = Paths.get(args[1]);
        Path tmpDir     = Paths.get(args[2]);
        Path classDir   = Paths.get(args[3]);  // FileReader.class 所在目录

        int sizeMultiplier = 500;
        if (args.length >= 5) {
            sizeMultiplier = Integer.parseInt(args[4]);
        }

        log("NAS长缓存路径 : " + nasLong.toAbsolutePath());
        log("NAS禁缓存路径 : " + nasNocache.toAbsolutePath());
        log("临时转换路径  : " + tmpDir.toAbsolutePath());
        log("文件大小倍数  : " + sizeMultiplier);

        // 前置校验：确认 TEST_CONTENT 能被 GBK 完整编码再解码，否则实验结果不可信
        validateGbkRoundtrip();

        exp1_LocalBaseline(tmpDir);
        exp2_NasReproduce(nasLong, tmpDir, sizeMultiplier);
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

    // ── 实验2：NAS 复现（无守护进程，独立复现）──────────────────────────────────
    //
    static void exp2_NasReproduce(Path nasDir, Path tmpDir, int sizeMultiplier) throws Exception {
        header("实验2：NAS 上复现写回乱码测试");

        Path nasFile    = nasDir.resolve("exp2_reproduce.txt");
        Path tmpFile    = tmpDir.resolve("exp2_reproduce.txt");

        // Step1: 写入 GBK 原始文件（大小通过参数控制，验证大小对缓存命中率的影响）
        StringBuilder bigContent = new StringBuilder();
        for (int i = 0; i < sizeMultiplier; i++) bigContent.append(TEST_CONTENT);
        String largeGbkContent = bigContent.toString();
        writeGbk(nasFile, largeGbkContent);
        logFileInfo(nasFile, "写入GBK后");
        log("文件大小: " + Files.size(nasFile) + " bytes (Multiplier: " + sizeMultiplier + ")");

        // Step2: 主进程读取一次预热缓存
        log("[主进程] 主动读取一次文件以预热 Page Cache...");
        String warmup = readGbk(nasFile);
        log("[主进程] 预热完成，GBK 数据进入 Page Cache");

        // Step3: 执行转换（move → GBK转UTF-8 → 同名写回）
        log("[转换进程] 执行 move → GBK转UTF-8 → 同名写回...");
        Files.move(nasFile, tmpFile, StandardCopyOption.REPLACE_EXISTING);
        convertBack(tmpFile, nasFile, false);
        logFileInfo(nasFile, "转换写回后");

        // Step4: 重新读取，判断是否命中旧缓存产生乱码
        String result = readUtf8(nasFile);
        boolean ok = largeGbkContent.equals(result);
        RESULTS.put("实验2 NAS复现", ok);

        // 打印可视化对比，直观展示乱码
        String preview = result.substring(0, Math.min(100, result.length()));
        String expected = largeGbkContent.substring(0, Math.min(100, largeGbkContent.length()));
        System.out.println();
        System.out.println("  ┌─────────────────────────────────────────────────────┐");
        System.out.println("  │              读取内容对比（前100字符）               │");
        System.out.println("  ├─────────────────────────────────────────────────────┤");
        System.out.println("  │ 期望内容: " + expected);
        System.out.println("  │ 实际读到: " + preview);
        System.out.println("  │ 前20字节hex: " + toHex(result.substring(0, Math.min(20, result.length()))));
        System.out.println("  │ 内容相同: " + (ok ? "✅ 是（没有拿到旧缓存）" : "❌ 否（读到旧GBK数据导致乱码）"));
        System.out.println("  └─────────────────────────────────────────────────────┘");
        System.out.println();
        result("实验2", ok,
            "读取到了正确的 UTF-8 数据（缓存已更新/未命中缓存）",
            "读到了旧 GBK 数据 ✓ 成功复现！Page / NAS Cache 返回了旧数据");
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
