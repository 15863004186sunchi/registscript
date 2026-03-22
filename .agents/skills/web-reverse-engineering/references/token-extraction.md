# Token 提取与持久化速查

## 标准 Token JSON 结构（OpenAI Codex）

```json
{
  "id_token":      "<JWT，来自 OAuth callback 中 id_token 字段，或与 access_token 相同>",
  "access_token":  "<JWT，Audience 为 https://api.openai.com/v1>",
  "refresh_token": "<rt_ 开头的长字符串，用于在 access_token 过期后换新>",
  "account_id":    "<UUID，来自 JWT Payload 的 chatgpt_account_id 字段>",
  "email":         "<用户邮箱>",
  "type":          "codex",
  "last_refresh":  "2026-03-21T06:44:51Z",
  "expired":       "2026-03-31T06:44:51Z"
}
```

---

## 提取方法 1：OAuth Callback 直接获取（最准确）

当 OAuth 授权码完成换 Token 时，响应体中直接包含：

```json
{
  "access_token":  "eyJ...",
  "id_token":      "eyJ...",
  "refresh_token": "rt_xxx",
  "token_type":    "Bearer",
  "expires_in":    86400
}
```

**Python 解析代码：**
```python
import json, time
from datetime import datetime, timezone

def save_token(token_resp: dict, email: str, file_prefix: str) -> str:
    """将 OAuth 换取的 token 保存为标准 JSON 文件"""
    access_token = token_resp["access_token"]
    
    # 从 JWT Payload 中提取 account_id
    import base64
    payload_b64 = access_token.split('.')[1]
    padding = 4 - len(payload_b64) % 4
    payload = json.loads(base64.b64decode(payload_b64 + '=' * padding))
    account_id = payload.get("https://api.openai.com/auth", {}).get("chatgpt_account_id", "")

    now = datetime.now(timezone.utc)
    expired = datetime(now.year, now.month, now.day + 10, tzinfo=timezone.utc)

    token_data = {
        "id_token":      token_resp.get("id_token", access_token),
        "access_token":  access_token,
        "refresh_token": token_resp.get("refresh_token", ""),
        "account_id":    account_id,
        "email":         email,
        "type":          "codex",
        "last_refresh":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expired":       expired.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    file_name = f"token_{file_prefix}_{int(time.time())}.json"
    with open(file_name, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=4, ensure_ascii=False)
    return file_name
```

---

## 提取方法 2：浏览器 JS 脚本（人工登录辅助）

在已登录的 `chatgpt.com` 页面中，F12 控制台运行（见 `extract_token.js`）：

```javascript
// 关键：安全的 Base64 解码
const payloadBase64 = accessToken.split('.')[1];
let base64 = payloadBase64.replace(/-/g, '+').replace(/_/g, '/');
while (base64.length % 4) base64 += '=';  // 必须补齐等号
const payload = JSON.parse(decodeURIComponent(escape(atob(base64))));
const account_id = payload["https://api.openai.com/auth"]["chatgpt_account_id"];
```

**坑点**：如果不补等号，`atob()` 会直接抛出 `InvalidCharacterError`，导致 `account_id` 提取失败为空，上传到管理面板时报"缺少账号 ID"。

---

## 提取方法 3：从 Cookie 解析（备用方案）

登录成功后，某些响应会在 `Set-Cookie` 中下发 `auth_provider` 字段，其值是 Base64 编码的 Token：

```python
import base64
auth_cookie = session.cookies.get("auth_provider") or ""
if auth_cookie.startswith(":"):
    auth_cookie = auth_cookie[1:]  # 去掉前缀冒号

# 解析：尝试直接 base64 decode
try:
    decoded = base64.b64decode(auth_cookie + '==')  # 补等号
    token_json = json.loads(decoded)
    access_token = token_json.get("access_token", "")
except Exception:
    pass
```

---

## Token 有效期规则

| Token 类型 | 有效期 | 刷新方式 |
|-----------|-------|---------|
| `access_token` | ~1 小时（见 `exp` 字段）| 使用 `refresh_token` 换新 |
| `refresh_token` (`rt_...`) | ~30 天 | 无法刷新，需重新登录 |
| `oai-client-auth-session` Cookie | 与 session 同生命周期 | 每次登录时更新 |

---

## 校验方法

运行脚本校验 Token 完整性：

```python
REQUIRED_FIELDS = ["id_token", "access_token", "account_id", "email", "type", "expired"]

def validate_token_file(path: str) -> bool:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    missing = [k for k in REQUIRED_FIELDS if not str(data.get(k, "")).strip()]
    if missing:
        print(f"[FAILED] 缺少字段: {missing}")
        return False
    # 检查 account_id 不是占位默认值
    if data["account_id"] == "2ab60b7c-6e4d-4a3b-a012-b7d522f5b149":
        print("[WARN] account_id 是默认兜底值，建议重新提取")
    print("[PASS] Token 结构完整")
    return True
```
