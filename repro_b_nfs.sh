#!/bin/bash
# B node script: read UTF-8 after A finishes
# Run on VM B (reader). Requires NFS share mounted.

set -euo pipefail

SHARE_DIR="${SHARE_DIR:-/mnt/nas_share}"
TMP_DIR="${TMP_DIR:-/tmp/nas_ab_tmp_b}"
FILE_NAME="${FILE_NAME:-ab_repro.txt}"
DONE_FILE="${DONE_FILE:-_A_DONE.sig}"
GBK_READY_FILE="${GBK_READY_FILE:-_A_GBK_READY.sig}"
REPEAT="${REPEAT:-500}"
MODE="${MODE:-read}"       # prime | read
WAIT_SECS="${WAIT_SECS:-60}"
WAIT_FOR_FILE="${WAIT_FOR_FILE:-1}"  # 1 = wait for file in prime mode
WAIT_FOR_GBK="${WAIT_FOR_GBK:-1}"    # 1 = wait for GBK ready signal before prime
RUN_ID_FILE="${RUN_ID_FILE:-$TMP_DIR/last_run_id.txt}"
PRIME_MODE="${PRIME_MODE:-both}"     # attr | data | both
USE_JAVA="${USE_JAVA:-1}"            # 1 = use embedded Java implementation
JAVA_DIR="${JAVA_DIR:-/tmp/nas_ab_java_b}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

CONTENT_UTF8="GBK sample line 1: 中文测试一二三. Line2: 中文字符用于触发乱码. Line3: end marker."

mkdir -p "$TMP_DIR"

if [[ "$USE_JAVA" == "1" ]]; then
  if ! command -v javac >/dev/null 2>&1; then
    echo "[ERR] javac not found. Install JDK or set USE_JAVA=0"
    exit 2
  fi
  mkdir -p "$JAVA_DIR"
  cat > "$JAVA_DIR/BReader.java" << 'JAVA_EOF'
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;

public class BReader {
    public static void main(String[] args) throws Exception {
        if (args.length < 10) {
            System.out.println("Usage: java BReader <shareDir> <mode> <fileName> <gbkReady> <done> <repeat> <primeMode> <waitSecs> <waitForGbk> <runIdFile>");
            System.exit(1);
        }
        Path shareDir = Paths.get(args[0]);
        String mode = args[1];
        String fileName = args[2];
        String gbkReady = args[3];
        String done = args[4];
        int repeat = Integer.parseInt(args[5]);
        String primeMode = args[6];
        int waitSecs = Integer.parseInt(args[7]);
        boolean waitForGbk = "1".equals(args[8]);
        Path runIdFile = Paths.get(args[9]);

        Path file = shareDir.resolve(fileName);
        Path gbkReadyPath = shareDir.resolve(gbkReady);
        Path donePath = shareDir.resolve(done);

        if ("prime".equalsIgnoreCase(mode)) {
            if (waitForGbk) {
                log("Waiting for GBK ready signal: " + gbkReady);
                waitForExists(gbkReadyPath, waitSecs);
            }
            if (Files.exists(gbkReadyPath)) {
                String runId = readRunId(gbkReadyPath);
                if (runId != null && !runId.isEmpty()) {
                    Files.createDirectories(runIdFile.getParent());
                    Files.write(runIdFile, runId.getBytes(StandardCharsets.UTF_8));
                    log("Captured RUN_ID: " + runId);
                }
            }
            if (Files.exists(file)) {
                if ("attr".equalsIgnoreCase(primeMode) || "both".equalsIgnoreCase(primeMode)) {
                    Files.readAttributes(file, BasicFileAttributes.class);
                }
                if ("data".equalsIgnoreCase(primeMode) || "both".equalsIgnoreCase(primeMode)) {
                    try (InputStream in = new FileInputStream(file.toFile())) {
                        byte[] buf = new byte[32];
                        in.read(buf);
                    }
                }
                log("Primed cache on " + file);
            } else {
                log("File not found to prime: " + file);
            }
            return;
        }

        if ("read".equalsIgnoreCase(mode)) {
            log("Waiting for A done signal: " + done);
            String runId = null;
            if (Files.exists(runIdFile)) {
                runId = new String(Files.readAllBytes(runIdFile), StandardCharsets.UTF_8).trim();
                log("Using RUN_ID: " + runId);
            } else {
                log("RUN_ID_FILE not found: " + runIdFile + " (may read stale done signal)");
            }
            waitForDone(donePath, runId, waitSecs);

            BasicFileAttributes attrs = Files.readAttributes(file, BasicFileAttributes.class);
            Object ino = null;
            try { ino = Files.getAttribute(file, "unix:ino"); } catch (Exception ignored) {}
            log("File info: inode=" + (ino == null ? "N/A" : ino) + " size=" + attrs.size());

            String expected = buildExpected(repeat);
            String actual = readUtf8(file);
            if (expected.equals(actual)) {
                log("Match expected UTF-8 content: YES");
            } else {
                log("Match expected UTF-8 content: NO (mismatch/garbled)");
                log("Expected head:");
                System.out.println(preview(expected));
                log("Actual head:");
                System.out.println(preview(actual));
                log("Actual hex head:");
                System.out.println(hexHead(file, 64));
            }
        }
    }

    static void waitForExists(Path p, int waitSecs) throws Exception {
        long max = waitSecs * 1000L;
        long start = System.currentTimeMillis();
        while (!Files.exists(p)) {
            if (System.currentTimeMillis() - start > max) break;
            Thread.sleep(100);
        }
    }

    static void waitForDone(Path donePath, String runId, int waitSecs) throws Exception {
        long max = waitSecs * 1000L;
        long start = System.currentTimeMillis();
        while (true) {
            if (Files.exists(donePath)) {
                if (runId == null || runId.isEmpty()) break;
                String doneId = readRunId(donePath);
                if (runId.equals(doneId)) break;
            }
            if (System.currentTimeMillis() - start > max) break;
            Thread.sleep(100);
        }
    }

    static String readRunId(Path p) {
        try {
            for (String line : Files.readAllLines(p, StandardCharsets.UTF_8)) {
                if (line.startsWith("RUN_ID=")) return line.substring("RUN_ID=".length()).trim();
            }
        } catch (Exception ignored) {}
        return null;
    }

    static String buildExpected(int repeat) {
        String line = "GBK sample line 1: 中文测试一二三. Line2: 中文字符用于触发乱码. Line3: end marker.";
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < repeat; i++) sb.append(line).append("\n");
        return sb.toString();
    }

    static String readUtf8(Path p) throws Exception {
        try (Reader r = new InputStreamReader(new FileInputStream(p.toFile()), StandardCharsets.UTF_8)) {
            StringBuilder sb = new StringBuilder();
            char[] buf = new char[4096]; int n;
            while ((n = r.read(buf)) != -1) sb.append(buf, 0, n);
            return sb.toString();
        }
    }

    static String preview(String s) {
        int n = Math.min(80, s.length());
        return s.substring(0, n).replace("\n", "\\n");
    }

    static String hexHead(Path p, int n) {
        try (InputStream in = new FileInputStream(p.toFile())) {
            byte[] buf = new byte[n];
            int len = in.read(buf);
            if (len <= 0) return "";
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < len; i++) {
                if (i % 16 == 0) sb.append(String.format("%08x  ", i));
                sb.append(String.format("%02x ", buf[i]));
                if (i % 16 == 15 || i == len - 1) sb.append("\n");
            }
            return sb.toString();
        } catch (Exception e) {
            return "";
        }
    }

    static void log(String msg) {
        System.out.println("[" + new java.text.SimpleDateFormat("HH:mm:ss").format(new java.util.Date()) + "] " + msg);
    }
}
JAVA_EOF
  javac -encoding UTF-8 "$JAVA_DIR/BReader.java" -d "$JAVA_DIR"
  log "Running Java BReader..."
  java -cp "$JAVA_DIR" BReader "$SHARE_DIR" "$MODE" "$FILE_NAME" "$GBK_READY_FILE" "$DONE_FILE" \
    "$REPEAT" "$PRIME_MODE" "$WAIT_SECS" "$WAIT_FOR_GBK" "$RUN_ID_FILE"
  exit 0
fi

expected="$TMP_DIR/expected_utf8.txt"
{
  for ((i=0; i<REPEAT; i++)); do
    echo "$CONTENT_UTF8"
  done
} > "$expected"

if [[ "$MODE" == "prime" ]]; then
  # Prime attribute/data cache and exit
  if [[ "$WAIT_FOR_GBK" == "1" ]]; then
    log "Waiting for GBK ready signal: $GBK_READY_FILE"
    for ((i=0; i<WAIT_SECS*10; i++)); do
      [[ -f "$SHARE_DIR/$GBK_READY_FILE" ]] && break
      sleep 0.1
    done
  fi
  if [[ -f "$SHARE_DIR/$GBK_READY_FILE" ]]; then
    run_id="$(sed -n 's/^RUN_ID=//p' "$SHARE_DIR/$GBK_READY_FILE" | head -n 1)"
    if [[ -n "$run_id" ]]; then
      echo "$run_id" > "$RUN_ID_FILE"
      log "Captured RUN_ID: $run_id"
    fi
  fi
  if [[ ! -f "$SHARE_DIR/$FILE_NAME" && "$WAIT_FOR_FILE" == "1" ]]; then
    log "Waiting for file to appear before priming..."
    for ((i=0; i<WAIT_SECS*10; i++)); do
      [[ -f "$SHARE_DIR/$FILE_NAME" ]] && break
      sleep 0.1
    done
  fi
  if [[ -f "$SHARE_DIR/$FILE_NAME" ]]; then
    case "$PRIME_MODE" in
      attr)
        stat "$SHARE_DIR/$FILE_NAME" >/dev/null 2>&1 || true
        ;;
      data)
        head -c 32 "$SHARE_DIR/$FILE_NAME" >/dev/null 2>&1 || true
        ;;
      both|*)
        stat "$SHARE_DIR/$FILE_NAME" >/dev/null 2>&1 || true
        head -c 32 "$SHARE_DIR/$FILE_NAME" >/dev/null 2>&1 || true
        ;;
    esac
    log "Primed cache on $SHARE_DIR/$FILE_NAME"
  else
    log "File not found to prime: $SHARE_DIR/$FILE_NAME (run A first or disable WAIT_FOR_FILE=1)"
  fi
  exit 0
fi

log "Waiting for A done signal: $DONE_FILE"
run_id=""
if [[ -f "$RUN_ID_FILE" ]]; then
  run_id="$(cat "$RUN_ID_FILE" | head -n 1)"
  log "Using RUN_ID: $run_id"
else
  log "RUN_ID_FILE not found: $RUN_ID_FILE (may read stale done signal)"
fi
for ((i=0; i<WAIT_SECS*10; i++)); do
  if [[ -f "$SHARE_DIR/$DONE_FILE" ]]; then
    if [[ -z "$run_id" ]]; then
      break
    fi
    done_id="$(sed -n 's/^RUN_ID=//p' "$SHARE_DIR/$DONE_FILE" | head -n 1)"
    if [[ "$done_id" == "$run_id" ]]; then
      break
    fi
  fi
  sleep 0.1
done

if [[ ! -f "$SHARE_DIR/$DONE_FILE" ]]; then
  log "Timeout waiting for done signal."
  exit 2
fi

log "Reading file..."
log "File info: $(stat -c 'inode=%i size=%s' "$SHARE_DIR/$FILE_NAME")"

if cmp -s "$expected" "$SHARE_DIR/$FILE_NAME"; then
  log "Match expected UTF-8 content: YES"
else
  log "Match expected UTF-8 content: NO (mismatch/garbled)"
  log "Expected head:"
  head -n 1 "$expected" | sed -n '1p'
  log "Actual head:"
  head -n 1 "$SHARE_DIR/$FILE_NAME" | sed -n '1p'
  log "Actual hex head:"
  head -c 64 "$SHARE_DIR/$FILE_NAME" | hexdump -C | head -n 2
fi
