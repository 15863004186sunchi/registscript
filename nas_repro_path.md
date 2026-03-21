# NAS 缓存乱码问题复现路径（NFS / 双 VM）

本文整理了我们讨论后的**可复现路径**与脚本使用方式，目标是复现：
> A 节点将 GBK 文件转码为 UTF-8 并写回同名路径；  
> B 节点在之后读取时仍读到旧 GBK 字节，导致 UTF-8 解码乱码。

---

## 1. 复现前提与设计思路

核心思路是让 B **先缓存旧文件内容**，A 再完成转码写回，之后 B 在**缓存未失效窗口内**读取。

关键点：
- B 端先 **prime（预热缓存）**：读到 GBK 字节
- A 端完成 **move + GBK->UTF-8 回写**
- B 端在缓存仍有效的窗口中读取，可能命中旧数据

避免“假阳性”的关键：
- B **必须在 A 转码完成后再读取**
- 需要清理旧信号文件（或使用带 RUN_ID 的信号）

---

## 2. 环境准备（两台虚拟机）

假设：
- VM1 = NFS Server + A 节点
- VM2 = B 节点

### 2.1 NFS 服务器端（VM1）

```bash
sudo EXPORT_DIR=/data/nfs_share ALLOWED_CIDR=192.168.10.0/24 ./setup_nfs_server.sh
```

### 2.2 客户端挂载（VM1 / VM2）

两台都挂载到相同目录 `/mnt/nas_share`：

```bash
sudo SERVER_IP=192.168.10.100 EXPORT_DIR=/data/nfs_share MOUNT_POINT=/mnt/nas_share ./setup_nfs_client.sh
```

可选：B 端更容易复现的挂载参数（可按需替换）
```bash
MOUNT_OPTS="rw,actimeo=60,lookupcache=all,nocto"
```

---

## 3. 复现脚本说明

脚本文件：
- `repro_a_nfs.sh`：A 端转码流程（GBK -> UTF-8）
- `repro_b_nfs.sh`：B 端 prime 和 read

脚本默认路径：
- 共享目录：`/mnt/nas_share`
- 文件名：`ab_repro.txt`
- 信号文件：`_A_GBK_READY.sig` / `_A_DONE.sig`

---

## 4. 标准复现步骤（推荐顺序）

### 步骤 1：B 端 prime（等待 GBK ready）

```bash
MODE=prime SHARE_DIR=/mnt/nas_share ./repro_b_nfs.sh
```

### 步骤 2：A 端写 GBK 并延迟转码

给 B 留出 prime 窗口（例如 10 秒）：
```bash
SLEEP_BEFORE_CONVERT=10 SHARE_DIR=/mnt/nas_share ./repro_a_nfs.sh
```

### 步骤 3：B 端读取

```bash
MODE=read SHARE_DIR=/mnt/nas_share ./repro_b_nfs.sh
```

---

## 5. 复现成功的判据

若复现成功，B 端应出现：
- `Match expected UTF-8 content: NO`
- 输出内容乱码（UTF-8 解码 GBK）
- 十六进制里出现 GBK 字节（如 `d6 d0 ce c4 ...`）

示例特征（仅示意）：
```
Actual head:
GBK sample line 1: אτ²㋔...
Actual hex head:
... d6 d0 ce c4 b2 e2 ca d4 d2 bb b6 fe c8 ...
```

---

## 6. 常见“复现失败”原因

1. **B 读取发生在 A 转码之前**  
   会误以为缓存导致，其实是时序问题

2. **信号文件残留导致 B 过早读取**  
   需清理 `_A_DONE.sig` / `_A_GBK_READY.sig`

3. **本机 NFS 回环难复现**  
   同机 client/server 缓存一致性太强，推荐双 VM

---

## 7. 常用变量（可选调整）

- `SLEEP_BEFORE_CONVERT=10`  
  A 写 GBK 后等待 N 秒再转码

- `WAIT_SECS=60`  
  B 等待信号的最长时间

- `REPEAT=500`  
  文件大小放大，增加缓存命中概率

---

## 8. 复现脚本文件位置

请查看以下文件：
- `setup_nfs_server.sh`
- `setup_nfs_client.sh`
- `repro_a_nfs.sh`
- `repro_b_nfs.sh`

