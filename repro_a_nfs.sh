#!/bin/bash
# A node script: GBK -> UTF-8 conversion with move + rewrite
# Run on VM A (writer). Requires NFS share mounted.

set -euo pipefail

SHARE_DIR="${SHARE_DIR:-/mnt/nas_share}"
TMP_DIR="${TMP_DIR:-/tmp/nas_ab_tmp}"
FILE_NAME="${FILE_NAME:-ab_repro.txt}"
DONE_FILE="${DONE_FILE:-_A_DONE.sig}"
GBK_READY_FILE="${GBK_READY_FILE:-_A_GBK_READY.sig}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)_$RANDOM}"
REPEAT="${REPEAT:-500}"
DO_FSYNC="${DO_FSYNC:-0}"   # 1 = fsync after write
SLEEP_BEFORE_CONVERT="${SLEEP_BEFORE_CONVERT:-0}"  # seconds to wait after GBK write
USE_JAVA="${USE_JAVA:-1}"   # 1 = use embedded Java implementation
JAVA_DIR="${JAVA_DIR:-/tmp/nas_ab_java_a}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

CONTENT_UTF8="GBK sample line 1: 中文测试一二三. Line2: 中文字符用于触发乱码. Line3: end marker."

mkdir -p "$TMP_DIR"

log "Share: $SHARE_DIR"
log "Tmp  : $TMP_DIR"
log "Run  : $RUN_ID"

# Clear stale signals
rm -f "$SHARE_DIR/$DONE_FILE" "$SHARE_DIR/$GBK_READY_FILE"

# Java path (embedded)
if [[ "$USE_JAVA" == "1" ]]; then
  if ! command -v javac >/dev/null 2>&1; then
    echo "[ERR] javac not found. Install JDK or set USE_JAVA=0"
    exit 2
  fi
  mkdir -p "$JAVA_DIR"
  cat > "$JAVA_DIR/AConvert.java" << 'JAVA_EOF'
import java.io.*;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

public class AConvert {
    public static void main(String[] args) throws Exception {
        if (args.length < 9) {
            System.out.println("Usage: java AConvert <shareDir> <sleepSec> <fileName> <tmpDir> <gbkReady> <done> <repeat> <doFsync> <runId>");
            System.exit(1);
        }
        Path shareDir = Paths.get(args[0]);
        int sleepSec  = Integer.parseInt(args[1]);
        String fileName = args[2];
        Path tmpDir = Paths.get(args[3]);
        String gbkReady = args[4];
        String done = args[5];
        int repeat = Integer.parseInt(args[6]);
        boolean doFsync = "1".equals(args[7]);
        String runId = args[8];

        Path file = shareDir.resolve(fileName);
        Path tmp  = tmpDir.resolve(fileName);
        Files.createDirectories(tmpDir);

        String line = "GBK sample line 1: 中文测试一二三. Line2: 中文字符用于触发乱码. Line3: end marker.";
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < repeat; i++) sb.append(line).append("\n");

        try (Writer w = new OutputStreamWriter(new FileOutputStream(file.toFile()), Charset.forName("GBK"))) {
            w.write(sb.toString());
        }

        Files.write(shareDir.resolve(gbkReady), ("RUN_ID=" + runId).getBytes(StandardCharsets.UTF_8));

        if (sleepSec > 0) Thread.sleep(sleepSec * 1000L);

        Files.move(file, tmp, StandardCopyOption.REPLACE_EXISTING);

        String content;
        try (Reader r = new InputStreamReader(new FileInputStream(tmp.toFile()), Charset.forName("GBK"))) {
            StringBuilder s = new StringBuilder();
            char[] buf = new char[4096]; int n;
            while ((n = r.read(buf)) != -1) s.append(buf, 0, n);
            content = s.toString();
        }
        try (FileOutputStream fos = new FileOutputStream(file.toFile());
             Writer w = new OutputStreamWriter(fos, StandardCharsets.UTF_8)) {
            w.write(content);
            w.flush();
            if (doFsync) fos.getFD().sync();
        }

        Files.write(shareDir.resolve(done), ("RUN_ID=" + runId).getBytes(StandardCharsets.UTF_8));
    }
}
JAVA_EOF
  javac -encoding UTF-8 "$JAVA_DIR/AConvert.java" -d "$JAVA_DIR"
  log "Running Java AConvert..."
  java -cp "$JAVA_DIR" AConvert "$SHARE_DIR" "$SLEEP_BEFORE_CONVERT" "$FILE_NAME" "$TMP_DIR" \
    "$GBK_READY_FILE" "$DONE_FILE" "$REPEAT" "$DO_FSYNC" "$RUN_ID"
  exit 0
fi

# Build UTF-8 content and write as GBK to share (original file)
log "Writing GBK source..."
{
  for ((i=0; i<REPEAT; i++)); do
    echo "$CONTENT_UTF8"
  done
} | iconv -f UTF-8 -t GBK > "$SHARE_DIR/$FILE_NAME"

log "GBK written: $(stat -c 'inode=%i size=%s' "$SHARE_DIR/$FILE_NAME")"

# Signal GBK ready for B to prime cache
echo "RUN_ID=$RUN_ID" > "$SHARE_DIR/$GBK_READY_FILE"
log "GBK ready signal created: $GBK_READY_FILE"

if [[ "$SLEEP_BEFORE_CONVERT" != "0" ]]; then
  log "Sleeping $SLEEP_BEFORE_CONVERT seconds before convert..."
  sleep "$SLEEP_BEFORE_CONVERT"
fi

# Move to temp (local) and convert back to UTF-8, write to original path
log "Converting GBK -> UTF-8 (move -> rewrite)..."
mv -f "$SHARE_DIR/$FILE_NAME" "$TMP_DIR/$FILE_NAME"
iconv -f GBK -t UTF-8 "$TMP_DIR/$FILE_NAME" > "$SHARE_DIR/$FILE_NAME"

if [[ "$DO_FSYNC" == "1" ]]; then
  # best-effort fsync (write + sync)
  sync
  log "sync done"
fi

log "UTF-8 rewritten: $(stat -c 'inode=%i size=%s' "$SHARE_DIR/$FILE_NAME")"

# Signal done
echo "RUN_ID=$RUN_ID" > "$SHARE_DIR/$DONE_FILE"
log "Done signal created: $DONE_FILE"
