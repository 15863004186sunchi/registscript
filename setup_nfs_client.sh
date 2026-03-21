#!/bin/bash
# NFS client mount (CentOS 7+)
# Usage:
#   sudo SERVER_IP=192.168.10.100 EXPORT_DIR=/data/nfs_share MOUNT_POINT=/mnt/nas_share ./setup_nfs_client.sh

set -euo pipefail

SERVER_IP="${SERVER_IP:-}"
EXPORT_DIR="${EXPORT_DIR:-/data/nfs_share}"
MOUNT_POINT="${MOUNT_POINT:-/mnt/nas_share}"
MOUNT_OPTS="${MOUNT_OPTS:-rw,noac,lookupcache=none}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo $0"
  exit 1
fi

if [[ -z "$SERVER_IP" ]]; then
  echo "SERVER_IP is required, e.g.: SERVER_IP=192.168.10.100"
  exit 2
fi

# Install deps if missing (CentOS/RHEL)
if command -v yum &>/dev/null; then
  pkgs=()
  rpm -q nfs-utils &>/dev/null || pkgs+=(nfs-utils)
  if [[ ${#pkgs[@]} -gt 0 ]]; then
    log "Installing: ${pkgs[*]}"
    yum install -y -q "${pkgs[@]}"
  fi
fi

log "Preparing mount point: $MOUNT_POINT"
mkdir -p "$MOUNT_POINT"
umount -f "$MOUNT_POINT" 2>/dev/null || true

log "Mounting $SERVER_IP:$EXPORT_DIR -> $MOUNT_POINT ($MOUNT_OPTS)"
mount -t nfs "$SERVER_IP:$EXPORT_DIR" "$MOUNT_POINT" -o "$MOUNT_OPTS"

log "Mounted:"
mount | grep -F "$MOUNT_POINT" || true
log "Done."
