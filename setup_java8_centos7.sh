#!/bin/bash
# Install Java 8 (OpenJDK) on CentOS 7

set -euo pipefail

log() { echo "[$(date '+%H:%M:%S')] $*"; }

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo $0"
  exit 1
fi

if ! command -v yum >/dev/null 2>&1; then
  echo "yum not found. This script is for CentOS/RHEL 7."
  exit 2
fi

log "Installing OpenJDK 8..."
yum install -y -q java-1.8.0-openjdk java-1.8.0-openjdk-devel

log "Java version:"
java -version
log "Javac version:"
javac -version

log "Done."
