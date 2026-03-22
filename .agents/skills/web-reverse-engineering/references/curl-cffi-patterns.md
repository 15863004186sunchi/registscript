# curl_cffi 常见模式与踩坑记录

## 为什么用 curl_cffi 而不是 requests？

| 特性 | requests | curl_cffi |
|------|---------|-----------|
| TLS 指纹 | Python 标准（容易被检测）| 精确模拟 Chrome / Firefox |
| HTTP/2 支持 | 需额外依赖 | 原生支持 |
| Cookie 管理 | Session | Session（兼容） |
| 风控绕过成功率 | 低 | 高（Cloudflare、Fastly 等）|

---

## 基础用法

```python
from curl_cffi import requests

# 创建 Session（推荐，自动管理 Cookie）
s = requests.Session(impersonate="chrome")

# GET 请求
resp = s.get("https://example.com", timeout=15)
print(resp.status_code)

# POST JSON
resp = s.post(
    "https://api.example.com/login",
    headers={"content-type": "application/json"},
    data='{"username": "foo", "password": "bar"}',  # 用 data，不用 json=
)

# 带代理
proxies = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
resp = s.get("https://example.com", proxies=proxies, impersonate="chrome")
```

---

## 常见坑点

### 坑 1：用了 `json=` 参数导致被检测

**错误写法：**
```python
s.post(url, json={"foo": "bar"})  # ❌ 会触发特殊的 Content-Type 头
```

**正确写法：**
```python
import json
s.post(url, headers={"content-type": "application/json"}, data=json.dumps({"foo": "bar"}))  # ✅
```

---

### 坑 2：把 requests 库和 curl_cffi 混用导致 Cookie 不同步

```python
from curl_cffi import requests  # ✅ 统一用 curl_cffi 的 requests
import requests as stdlib_requests  # ❌ 不要在同一 Session 生命周期混用
```

---

### 坑 3：同一个包中 requests 来自两个不同来源

**检查方式：**
```python
import sys
print([k for k in sys.modules if 'requests' in k])
```
如果同时出现 `curl_cffi.requests` 和 `requests`，需要统一。

---

### 坑 4：响应 body 是 gzip 压缩但未自动解码

**通常不需要手动处理，但如果乱码：**
```python
import gzip
raw = resp.content
try:
    body = gzip.decompress(raw).decode("utf-8")
except Exception:
    body = raw.decode("utf-8")
```

---

### 坑 5：impersonate 版本不匹配目标站点鉴别

常见可用值：
```python
impersonate="chrome"         # 最新 Chrome（推荐）
impersonate="chrome120"      # 固定版本
impersonate="safari"
impersonate="firefox"
```

如果某个网站对 Chrome 特别挑剔，可以尝试切换版本：
```python
for imp in ["chrome", "chrome120", "safari", "firefox"]:
    resp = requests.post(url, impersonate=imp)
    if resp.status_code == 200:
        print(f"成功版本: {imp}")
        break
```

---

## Sentinel Token 请求模板

```python
from curl_cffi import requests

def get_sentinel_token(did: str, flow: str, proxies=None) -> str:
    """申请 OpenAI Sentinel Token"""
    body = f'{{"p":"","id":"{did}","flow":"{flow}"}}'
    resp = requests.post(
        "https://sentinel.openai.com/backend-api/sentinel/req",
        headers={
            "origin": "https://sentinel.openai.com",
            "content-type": "text/plain;charset=UTF-8",
        },
        data=body,
        proxies=proxies,
        impersonate="chrome",
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Sentinel 请求失败: {resp.status_code}")
    token = resp.json()["token"]
    return f'{{"p": "", "t": "", "c": "{token}", "id": "{did}", "flow": "{flow}"}}'
```

---

## 完整 Session 模板

```python
from curl_cffi import requests
import json
import time
import random

def human_delay(min_s=1.0, max_s=3.0):
    time.sleep(random.uniform(min_s, max_s))

def create_session(proxy: str = None) -> requests.Session:
    s = requests.Session(impersonate="chrome")
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s

# 基础 Header 模板（模拟真实浏览器）
BASE_HEADERS = {
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "accept-encoding": "gzip, deflate, br",
    "content-type": "application/json",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
}
```

---

## 调试技巧

### 打印完整请求（包括头部和 body）：
```python
import logging
logging.basicConfig(level=logging.DEBUG)
# curl_cffi 会输出详细的请求/响应日志
```

### 手动检查 Cookie：
```python
print(dict(s.cookies))
```

### 捕获重定向链：
```python
resp = s.get(url, allow_redirects=False)
while resp.status_code in (301, 302, 303, 307, 308):
    location = resp.headers.get("Location")
    print(f"重定向 → {location}")
    resp = s.get(location, allow_redirects=False)
```
