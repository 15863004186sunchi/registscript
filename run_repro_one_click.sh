#!/bin/bash
# One-click repro orchestrator via SSH (requires sshpass).
#
# Usage:
#   chmod +x run_repro_one_click.sh
#   ./run_repro_one_click.sh
#
# Notes:
# - Uses password auth with sshpass (root/000000 as provided).
# - Copies required scripts to /root/nas_repro on both machines.

set -euo pipefail

SERVER_IP="${SERVER_IP:-192.168.10.100}"
CLIENT_IP="${CLIENT_IP:-192.168.10.102}"
SSH_USER="${SSH_USER:-root}"
SSH_PASS="${SSH_PASS:-000000}"

REMOTE_DIR="${REMOTE_DIR:-/root/nas_repro}"
EXPORT_DIR="${EXPORT_DIR:-/data/nfs_share}"
MOUNT_POINT="${MOUNT_POINT:-/mnt/nas_share}"
ALLOWED_CIDR="${ALLOWED_CIDR:-192.168.10.0/24}"

SLEEP_BEFORE_CONVERT="${SLEEP_BEFORE_CONVERT:-10}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing command: $1"
    exit 2
  }
}

need_cmd ssh
need_cmd scp
need_cmd sshpass

log "Copying scripts to remote machines..."
for host in "$SERVER_IP" "$CLIENT_IP"; do
  sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "$SSH_USER@$host" "mkdir -p $REMOTE_DIR"
  sshpass -p "$SSH_PASS" scp -o StrictHostKeyChecking=no \
    setup_nfs_server.sh setup_nfs_client.sh repro_a_nfs.sh repro_b_nfs.sh \
    "$SSH_USER@$host:$REMOTE_DIR/"
done

log "Server setup on $SERVER_IP..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "$SSH_USER@$SERVER_IP" \
  "cd $REMOTE_DIR && chmod +x *.sh && sudo EXPORT_DIR=$EXPORT_DIR ALLOWED_CIDR=$ALLOWED_CIDR ./setup_nfs_server.sh"

log "Client mount on $SERVER_IP..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "$SSH_USER@$SERVER_IP" \
  "cd $REMOTE_DIR && sudo SERVER_IP=$SERVER_IP EXPORT_DIR=$EXPORT_DIR MOUNT_POINT=$MOUNT_POINT ./setup_nfs_client.sh"

log "Client mount on $CLIENT_IP..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "$SSH_USER@$CLIENT_IP" \
  "cd $REMOTE_DIR && sudo SERVER_IP=$SERVER_IP EXPORT_DIR=$EXPORT_DIR MOUNT_POINT=$MOUNT_POINT ./setup_nfs_client.sh"

log "Start B prime (background) on $CLIENT_IP..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "$SSH_USER@$CLIENT_IP" \
  "cd $REMOTE_DIR && MODE=prime SHARE_DIR=$MOUNT_POINT ./repro_b_nfs.sh" &

sleep 1

log "Run A conversion on $SERVER_IP..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "$SSH_USER@$SERVER_IP" \
  "cd $REMOTE_DIR && SLEEP_BEFORE_CONVERT=$SLEEP_BEFORE_CONVERT SHARE_DIR=$MOUNT_POINT ./repro_a_nfs.sh"

log "Run B read on $CLIENT_IP..."
sshpass -p "$SSH_PASS" ssh -o StrictHostKeyChecking=no "$SSH_USER@$CLIENT_IP" \
  "cd $REMOTE_DIR && MODE=read SHARE_DIR=$MOUNT_POINT ./repro_b_nfs.sh"

log "Done."
