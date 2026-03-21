#!/bin/bash
# Repro for A/B NAS clients:
# - A converts GBK -> UTF-8 by move + rewrite to same path
# - B opens the file before conversion, holds fd, then reads again
# - B reads with UTF-8, but may see old GBK bytes -> garbled text

set -euo pipefail

NFS_EXPORT_DIR="${NFS_EXPORT_DIR:-/data/nfs_share}"
NFS_SERVER="${NFS_SERVER:-localhost}"
MOUNT_A="${MOUNT_A:-/mnt/nas_share}"
MOUNT_B="${MOUNT_B:-/mnt/nas_share}"
TMP_DIR="${TMP_DIR:-/tmp/nas_ab_tmp}"
WORK_DIR="${WORK_DIR:-/tmp/nas_ab_java}"
LOG_FILE="${LOG_FILE:-/tmp/nas_ab_repro.log}"
SKIP_NFS_SERVER="${SKIP_NFS_SERVER:-0}"
EXPORT_OPTS="${EXPORT_OPTS:-rw,sync,no_root_squash}"
MOUNT_OPTS_A="${MOUNT_OPTS_A:-rw,noac,lookupcache=none}"
MOUNT_OPTS_B="${MOUNT_OPTS_B:-rw,actimeo=60,lookupcache=all}"
MODE="${MODE:-post_open}"   # post_open | hold_fd
PRIME_B="${PRIME_B:-1}"     # 1 = prime B client cache before conversion
SLEEP_AFTER_A="${SLEEP_AFTER_A:-0}"  # seconds to sleep after A finishes before B reads

log()  { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
ok()   { echo "[OK] $*" | tee -a "$LOG_FILE"; }
warn() { echo "[WARN] $*" | tee -a "$LOG_FILE"; }
err()  { echo "[ERR] $*" | tee -a "$LOG_FILE"; }

check_root() {
  if [[ $EUID -ne 0 ]]; then
    err "This script needs root to manage NFS and mounts."
    echo "Please run: sudo $0"
    exit 1
  fi
}

install_deps() {
  local pkgs=()
  command -v javac &>/dev/null || pkgs+=(java-1.8.0-openjdk-devel)
  rpm -q nfs-utils &>/dev/null || pkgs+=(nfs-utils)
  rpm -q rpcbind   &>/dev/null || pkgs+=(rpcbind)

  if [[ ${#pkgs[@]} -gt 0 ]]; then
    log "Installing: ${pkgs[*]}"
    yum install -y -q "${pkgs[@]}"
    ok "Dependencies installed"
  else
    ok "Dependencies already installed"
  fi
}

setup_nfs_server() {
  if [[ "$SKIP_NFS_SERVER" == "1" ]]; then
    warn "SKIP_NFS_SERVER=1 -> skipping local NFS server setup"
    return
  fi

  mkdir -p "$NFS_EXPORT_DIR"
  chmod 777 "$NFS_EXPORT_DIR"

  local export_line="$NFS_EXPORT_DIR *(${EXPORT_OPTS})"
  if ! grep -qF "$NFS_EXPORT_DIR" /etc/exports 2>/dev/null; then
    echo "$export_line" >> /etc/exports
  else
    sed -i "\|$NFS_EXPORT_DIR|c\\$export_line" /etc/exports
  fi

  systemctl enable rpcbind &>/dev/null || true
  systemctl start  rpcbind || true
  systemctl enable nfs &>/dev/null || true
  systemctl restart nfs || true
  exportfs -ra
  ok "Local NFS server ready: $NFS_EXPORT_DIR"
}

setup_mounts() {
  mkdir -p "$MOUNT_A" "$MOUNT_B" "$TMP_DIR" "$WORK_DIR"

  umount -f "$MOUNT_A" 2>/dev/null || true
  umount -f "$MOUNT_B" 2>/dev/null || true

  # A (writer)
  mount -t nfs "$NFS_SERVER":"$NFS_EXPORT_DIR" "$MOUNT_A" \
    -o "$MOUNT_OPTS_A"

  # B (reader)
  mount -t nfs "$NFS_SERVER":"$NFS_EXPORT_DIR" "$MOUNT_B" \
    -o "$MOUNT_OPTS_B"

  ok "Mounted A: $MOUNT_A ($MOUNT_OPTS_A)"
  ok "Mounted B: $MOUNT_B ($MOUNT_OPTS_B)"
}

compile_java() {
  cat > "$WORK_DIR/FileReaderDaemon.java" << 'JAVA_EOF'
import java.io.*;
import java.nio.charset.*;
import java.nio.file.*;

// Long-lived reader holding fd
// Usage: java FileReaderDaemon <targetFile> <charset> <readyFile> <goFile> <resultFile>
public class FileReaderDaemon {
    public static void main(String[] args) throws Exception {
        Path targetFile = Paths.get(args[0]);
        Charset cs      = Charset.forName(args[1]);
        Path readyFile  = Paths.get(args[2]);
        Path goFile     = Paths.get(args[3]);
        Path resultFile = Paths.get(args[4]);

        FileInputStream fis = new FileInputStream(targetFile.toFile());
        InputStreamReader reader = new InputStreamReader(fis, cs);
        String firstRead = readAll(reader);

        writeSignal(readyFile, "READY:" + firstRead.length());

        for (int i = 0; i < 300; i++) {
            if (Files.exists(goFile)) break;
            Thread.sleep(100);
        }

        fis.getChannel().position(0);
        reader = new InputStreamReader(fis, cs);
        String secondRead = readAll(reader);

        writeSignal(resultFile, secondRead);
        fis.close();
    }

    static String readAll(InputStreamReader r) throws Exception {
        StringBuilder sb = new StringBuilder();
        char[] buf = new char[4096];
        int n;
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
JAVA_EOF

  cat > "$WORK_DIR/ABRepro.java" << 'JAVA_EOF'
import java.io.*;
import java.nio.charset.*;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.TimeUnit;

public class ABRepro {
    static final String TEST_CONTENT =
        "GBK sample line 1: 中文测试一二三. " +
        "Line2: 中文字符用于触发乱码. " +
        "Line3: end marker.";
    static final SimpleDateFormat SDF = new SimpleDateFormat("HH:mm:ss.SSS");

    public static void main(String[] args) throws Exception {
        if (args.length < 5) {
            System.out.println("Usage: java ABRepro <mountA> <mountB> <tmpDir> <classDir> <mode>");
            System.exit(1);
        }
        Path mountA  = Paths.get(args[0]);
        Path mountB  = Paths.get(args[1]);
        Path tmpDir  = Paths.get(args[2]);
        Path classDir= Paths.get(args[3]);
        String mode   = args[4];

        Files.createDirectories(tmpDir);

        Path fileA    = mountA.resolve("ab_repro.txt");
        Path fileB    = mountB.resolve("ab_repro.txt");
        Path tmpFile  = tmpDir.resolve("ab_repro.tmp");
        Path ready    = tmpDir.resolve("ab_ready.sig");
        Path go       = tmpDir.resolve("ab_go.sig");
        Path result   = tmpDir.resolve("ab_result.txt");

        Files.deleteIfExists(ready);
        Files.deleteIfExists(go);
        Files.deleteIfExists(result);

        String largeContent = buildLargeContent();
        writeGbk(fileA, largeContent);
        logInfo(fileA, "GBK written (A)");

        if ("hold_fd".equalsIgnoreCase(mode)) {
            // Old behavior: B holds fd open across conversion.
            Process daemon = startReaderDaemon(fileB, ready, go, result, classDir);
            waitForFile(ready, 150, "reader ready");

            Files.move(fileA, tmpFile, StandardCopyOption.REPLACE_EXISTING);
            convertGbkToUtf8(tmpFile, fileA, false);
            logInfo(fileA, "UTF-8 rewritten (A)");

            writeSignal(go, "GO");
            waitForFile(result, 150, "reader result");
            daemon.waitFor(5, TimeUnit.SECONDS);

            String readBack = readUtf8(result);
            printResult(largeContent, readBack, "hold_fd");
        } else {
            // New behavior: B opens after A finishes, but with cached attrs from prior access.
            primeBClient(fileB);

            Files.move(fileA, tmpFile, StandardCopyOption.REPLACE_EXISTING);
            convertGbkToUtf8(tmpFile, fileA, false);
            logInfo(fileA, "UTF-8 rewritten (A)");

            int sleepSec = 0;
            try {
                String env = System.getenv("SLEEP_AFTER_A");
                if (env != null && !env.isEmpty()) sleepSec = Integer.parseInt(env);
            } catch (Exception ignored) {}
            if (sleepSec > 0) Thread.sleep(sleepSec * 1000L);

            String readBack = readUtf8(fileB);
            printResult(largeContent, readBack, "post_open");
        }
    }

    static Process startReaderDaemon(Path targetFile, Path ready, Path go, Path result, Path classDir) throws Exception {
        String javaExe = Paths.get(System.getProperty("java.home"), "bin", "java").toString();
        ProcessBuilder pb = new ProcessBuilder(
            javaExe, "-cp", classDir.toString(),
            "FileReaderDaemon",
            targetFile.toString(),
            "UTF-8",
            ready.toString(),
            go.toString(),
            result.toString()
        );
        pb.redirectErrorStream(true);
        pb.redirectOutput(result.getParent().resolve("ab_reader.log").toFile());
        return pb.start();
    }

    static void primeBClient(Path fileB) throws Exception {
        // Prime B client cache to simulate prior access on the same NAS client
        if (!"1".equals(System.getenv("PRIME_B"))) return;
        if (!Files.exists(fileB)) return;
        // Force attribute + data cache population
        Files.readAttributes(fileB, BasicFileAttributes.class);
        try (FileInputStream fis = new FileInputStream(fileB.toFile())) {
            byte[] buf = new byte[32];
            fis.read(buf);
        }
    }

    static void waitForFile(Path p, int maxWait100ms, String label) throws Exception {
        for (int i = 0; i < maxWait100ms; i++) {
            if (Files.exists(p)) return;
            Thread.sleep(100);
        }
        throw new RuntimeException("Timeout waiting for " + label + ": " + p);
    }

    static String buildLargeContent() {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 500; i++) sb.append(TEST_CONTENT).append("\n");
        return sb.toString();
    }

    static void writeGbk(Path p, String content) throws Exception {
        try (OutputStreamWriter w = new OutputStreamWriter(
                new FileOutputStream(p.toFile()), Charset.forName("GBK"))) {
            w.write(content); w.flush();
        }
    }

    static void convertGbkToUtf8(Path src, Path dst, boolean fsync) throws Exception {
        String content = readGbk(src);
        FileOutputStream fos = new FileOutputStream(dst.toFile());
        try (OutputStreamWriter w = new OutputStreamWriter(fos, StandardCharsets.UTF_8)) {
            w.write(content); w.flush();
            if (fsync) fos.getFD().sync();
        }
    }

    static String readGbk(Path p) throws Exception {
        try (InputStreamReader r = new InputStreamReader(
                new FileInputStream(p.toFile()), Charset.forName("GBK"))) {
            return readAll(r);
        }
    }

    static String readUtf8(Path p) throws Exception {
        try (InputStreamReader r = new InputStreamReader(
                new FileInputStream(p.toFile()), StandardCharsets.UTF_8)) {
            return readAll(r);
        }
    }

    static String readAll(Reader r) throws Exception {
        StringBuilder sb = new StringBuilder();
        char[] buf = new char[4096];
        int n;
        while ((n = r.read(buf)) != -1) sb.append(buf, 0, n);
        return sb.toString();
    }

    static void writeSignal(Path p, String content) throws Exception {
        try (OutputStreamWriter w = new OutputStreamWriter(
                new FileOutputStream(p.toFile()), StandardCharsets.UTF_8)) {
            w.write(content); w.flush();
        }
    }

    static void logInfo(Path p, String label) throws Exception {
        BasicFileAttributes a = Files.readAttributes(p, BasicFileAttributes.class);
        String inode = "N/A";
        try { inode = Files.getAttribute(p, "unix:ino").toString(); } catch (Exception ignored) {}
        System.out.println("[" + SDF.format(new Date()) + "] " + label +
            " size=" + a.size() + " inode=" + inode);
    }

    static String preview(String s) {
        int n = Math.min(80, s.length());
        return s.substring(0, n).replace("\n", "\\n");
    }

    static void printResult(String expected, String actual, String mode) {
        boolean ok = expected.equals(actual);
        System.out.println();
        System.out.println("=== Result (" + mode + ") ===");
        System.out.println("Match expected UTF-8 content: " + (ok ? "YES" : "NO (garbled/stale)"));
        System.out.println("Expected head: " + preview(expected));
        System.out.println("Actual head  : " + preview(actual));
    }
}
JAVA_EOF

  javac -encoding UTF-8 "$WORK_DIR/FileReaderDaemon.java" "$WORK_DIR/ABRepro.java" -d "$WORK_DIR"
  ok "Java compiled: $WORK_DIR"
}

run_repro() {
  : > "$LOG_FILE"
  log "Running AB repro... mode=$MODE prime_b=$PRIME_B"
  JAVA_TOOL_OPTIONS="" java -cp "$WORK_DIR" ABRepro "$MOUNT_A" "$MOUNT_B" "$TMP_DIR" "$WORK_DIR" "$MODE" \
    2>&1 | tee -a "$LOG_FILE"
  ok "Done. Log: $LOG_FILE"
}

cleanup() {
  read -rp "Cleanup mounts and temp files? [y/N] " confirm
  if [[ "$confirm" =~ ^[Yy]$ ]]; then
    umount -f "$MOUNT_A" 2>/dev/null || true
    umount -f "$MOUNT_B" 2>/dev/null || true
    rm -rf "$TMP_DIR" "$WORK_DIR"
    ok "Cleanup done"
  else
    warn "Cleanup skipped"
  fi
}

main() {
  check_root
  install_deps
  setup_nfs_server
  setup_mounts
  compile_java
  run_repro
  cleanup
}

main "$@"
