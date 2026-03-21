#!/bin/bash
# NFS server setup (CentOS 7+)
# Usage:
#   sudo EXPORT_DIR=/data/nfs_share ALLOWED_CIDR=192.168.10.0/24 ./setup_nfs_server.sh

set -euo pipefail

EXPORT_DIR="${EXPORT_DIR:-/data/nfs_share}"
ALLOWED_CIDR="${ALLOWED_CIDR:-192.168.10.0/24}"
EXPORT_OPTS="${EXPORT_OPTS:-rw,sync,no_root_squash,no_all_squash}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo $0"
  exit 1
fi

# Install deps if missing (CentOS/RHEL)
if command -v yum &>/dev/null; then
  pkgs=()
  rpm -q nfs-utils &>/dev/null || pkgs+=(nfs-utils)
  rpm -q rpcbind   &>/dev/null || pkgs+=(rpcbind)
  if [[ ${#pkgs[@]} -gt 0 ]]; then
    log "Installing: ${pkgs[*]}"
    yum install -y -q "${pkgs[@]}"
  fi
fi

log "Preparing export dir: $EXPORT_DIR"
mkdir -p "$EXPORT_DIR"
chmod 777 "$EXPORT_DIR"

EXPORT_LINE="$EXPORT_DIR $ALLOWED_CIDR($EXPORT_OPTS)"
if ! grep -qF "$EXPORT_DIR" /etc/exports 2>/dev/null; then
  echo "$EXPORT_LINE" >> /etc/exports
else
  sed -i "\|$EXPORT_DIR|c\\$EXPORT_LINE" /etc/exports
fi

log "Starting NFS services..."
systemctl enable rpcbind >/dev/null 2>&1 || true
systemctl start  rpcbind >/dev/null 2>&1 || true
systemctl enable nfs >/dev/null 2>&1 || true
systemctl restart nfs >/dev/null 2>&1 || true
exportfs -ra

log "Export configured:"
exportfs -v | grep -F "$EXPORT_DIR" || true
log "Done."
