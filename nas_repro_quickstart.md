# NAS 乱码复现（最简命令清单）

以下为**最简可复现路径**，包含 NFS 服务端初始化、客户端挂载、A/B 执行顺序。  
本次固定使用以下机器：
- NFS Server / A：`192.168.10.100`
- B Client：`192.168.10.102`

---

## 1. NFS Server（192.168.10.100 上执行）

```bash
sudo EXPORT_DIR=/data/nfs_share ALLOWED_CIDR=192.168.10.0/24 ./setup_nfs_server.sh
```

---

## 2. Client 挂载（192.168.10.100 与 192.168.10.102 都执行）

```bash
sudo SERVER_IP=192.168.10.100 EXPORT_DIR=/data/nfs_share MOUNT_POINT=/mnt/nas_share ./setup_nfs_client.sh
```

---

## 3. 复现执行顺序

### 3.1 B 机器（192.168.10.102）先 prime（等待 A 写完 GBK）
```bash
MODE=prime SHARE_DIR=/mnt/nas_share ./repro_b_nfs.sh
```
如需仅使用 `stat` 预热（只缓存元数据）：
```bash
MODE=prime PRIME_MODE=attr SHARE_DIR=/mnt/nas_share ./repro_b_nfs.sh
```

### 3.2 A 机器（192.168.10.100）写 GBK 并延迟转码
```bash
SLEEP_BEFORE_CONVERT=10 SHARE_DIR=/mnt/nas_share ./repro_a_nfs.sh
```

### 3.3 B 机器（192.168.10.102）读取
```bash
MODE=read SHARE_DIR=/mnt/nas_share ./repro_b_nfs.sh
```

---

## 4. 成功判据

B 机器输出中出现：
```
Match expected UTF-8 content: NO (mismatch/garbled)
```
并看到乱码内容或 GBK 字节的十六进制输出，即表示复现成功。
