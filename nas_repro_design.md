# 复现脚本设计思路（结合代码解释）

本文解释当前复现脚本的**设计目的**与**关键实现**，帮助理解为什么这些步骤能复现“B 端读旧数据导致乱码”的现象。

脚本清单：
- `repro_a_nfs.sh`：A 端转码流程
- `repro_b_nfs.sh`：B 端 prime + read 流程

---

## 1. 设计目标

复现场景的关键不是“编码转换错误”，而是：
> B 端在 A 转码完成后仍读取旧 GBK 字节，按 UTF‑8 解码出现乱码。

要实现这一点，需要同时满足：
- **B 必须在 A 转码前访问文件**（缓存旧内容/旧属性）
- **B 必须在 A 转码后读取**（看到错误结果）

脚本设计即围绕这两点展开。

---

## 2. A 端脚本设计（`repro_a_nfs.sh`）

### 2.1 写入 GBK 原文件

核心逻辑：
```bash
echo "$CONTENT_UTF8" | iconv -f UTF-8 -t GBK > "$SHARE_DIR/$FILE_NAME"
```

目的：
- 生成**旧版本（GBK）**数据
- 作为 B 端缓存的“旧内容”

### 2.2 发出 GBK ready 信号

```bash
echo "RUN_ID=$RUN_ID" > "$SHARE_DIR/$GBK_READY_FILE"
```

目的：
- 告诉 B 端：“现在可以 prime（缓存旧内容）”
- 避免 B 端过早 prime 或读到新文件

### 2.3 延迟窗口（可选）

```bash
sleep "$SLEEP_BEFORE_CONVERT"
```

目的：
- 给 B 端留出 prime 窗口
- 确保 B 端缓存到的是旧 GBK

### 2.4 move + 转码回写

```bash
mv -f "$SHARE_DIR/$FILE_NAME" "$TMP_DIR/$FILE_NAME"
iconv -f GBK -t UTF-8 "$TMP_DIR/$FILE_NAME" > "$SHARE_DIR/$FILE_NAME"
```

目的：
- 模拟生产流程：**先 move 到临时目录，再转码写回同名路径**
- 这是线上真实路径变化 + 数据变化的组合

### 2.5 发出 Done 信号

```bash
echo "RUN_ID=$RUN_ID" > "$SHARE_DIR/$DONE_FILE"
```

目的：
- 通知 B 端可以开始“后读”
- 避免 B 端过早读取

---

## 3. B 端脚本设计（`repro_b_nfs.sh`）

### 3.1 prime 阶段（缓存旧数据）

关键代码：
```bash
stat "$SHARE_DIR/$FILE_NAME"
head -c 32 "$SHARE_DIR/$FILE_NAME"
```

含义：
- `stat`：触发**属性缓存**
- `head`：触发**数据缓存**

通过 `PRIME_MODE` 可控制只 prime 元数据或数据。

### 3.2 读取阶段

```bash
cmp -s "$expected" "$SHARE_DIR/$FILE_NAME"
```

对比预期 UTF‑8 内容和实际读到的数据：
- 一致 → 说明缓存已刷新
- 不一致 → 说明 B 端仍读旧数据

若不一致，脚本输出：
```bash
head -n 1 "$expected"
head -n 1 "$SHARE_DIR/$FILE_NAME"
head -c 64 "$SHARE_DIR/$FILE_NAME" | hexdump -C
```
用于直接观察乱码与 GBK 字节。

### 3.3 信号协调

`_A_GBK_READY.sig` 与 `_A_DONE.sig` 用于确保流程顺序。

顺序约束：
1. B 等待 `_A_GBK_READY.sig` → prime
2. A 转码完成后写 `_A_DONE.sig`
3. B 等待 `_A_DONE.sig` → read

---

## 4. 为什么这种设计能复现

因为它人为制造了**缓存一致性窗口**：

1. **旧数据进入 B 端缓存**  
   通过 prime 操作强制缓存旧 GBK

2. **A 修改同一路径数据**  
   触发 inode/元数据变化，但 B 端缓存未必立即失效

3. **B 在缓存有效期内读取**  
   读取到旧数据 → UTF‑8 解码乱码

这与生产中的“调度依赖 + 客户端缓存”机制一致。

---

## 5. 设计取舍说明

### 为什么不使用长驻 fd？

因为业务描述是：  
**B 在 A 完成后才启动读取**。  
因此复现应基于“后启动 + 客户端缓存”场景，而非“长驻 fd”。

---

## 6. 可选对照（非必需）

- `PRIME_MODE=attr`：仅属性缓存  
- `PRIME_MODE=data`：仅数据缓存  
- `PRIME_MODE=both`：二者都缓存（默认）

