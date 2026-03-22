# HTTP 登录模式速查

## 1. 传统密码登录（Username + Password）

### 流程
```
GET  /login              → 获取 CSRF token / session
POST /login              → 提交 {username, password, csrf_token}
302  → /dashboard        → 检查 Set-Cookie
```

### 常见特征
- 请求体：`application/x-www-form-urlencoded` 或 `application/json`
- 响应：设置 `session_id` 或 `auth_token` Cookie
- 风控点：CSRF token 每次刷新页面都会变化，需要先 GET 再 POST

---

## 2. OAuth 2.0 授权码模式（Authorization Code + PKCE）

### 流程
```
[客户端] 生成 code_verifier (随机字符串) + code_challenge (SHA256 hash)
GET  /authorize?response_type=code&client_id=...&code_challenge=...&state=...
302  → /login            → 用户登录
302  → callback?code=xxx&state=xxx  → 客户端拦截
POST /token              → {grant_type=authorization_code, code=xxx, code_verifier=xxx}
200  → {access_token, refresh_token, id_token}
```

### OpenAI 特有变体
- `redirect_uri`：通常是 `https://chatgpt.com/api/auth/callback/openai`
- `screen_hint`：必须是 `"login_or_signup"`（不能是 `"login"`！否则强制要求密码）
- `state`：服务端反 CSRF 验证，必须与发起请求时携带的一致

---

## 3. Email OTP / 无密码登录（Magic Link / Code）

### 流程
```
POST /authorize/continue  → {username: {value: email, kind: "email"}, screen_hint: "login_or_signup"}
GET  /api/accounts/email-otp/send    → 触发发送验证码邮件
POST /api/accounts/email-otp/validate → {code: "123456", trust_device: true}
GET  /api/accounts/workspace/select  → 选择工作区
302  → callback?code=...             → 换取 access_token
```

### 注意事项
- **发送验证码必须是 POST 而非 GET**（部分场景）
- `trust_device: true` 可以避免下次重新验证
- 验证码有效期通常为 10 分钟
- IMAP 抓码时务必加 `UNSEEN` 条件，避免读取旧邮件

---

## 4. SSO / SAML 模式

### 流程
```
GET  /sso/start?idp=google    → 跳转 IdP
POST /auth/google/callback      → 带 SAML Assertion 或 OAuth code
302  → 主站，设置 session
```

---

## 5. 设备密码 / API Key 模式

### 常见场景
- 服务端颁发 `api_key` 或 `secret`
- 后续所有请求以 `Authorization: Bearer <api_key>` 携带
- 不涉及浏览器登录流程，直接 POST 获取

---

## 关键参数对照表

| 参数名 | 来源 | 特征 |
|--------|------|------|
| `csrf_token` | 首次 GET 页面响应的 `<meta>` 或 Cookie | 敏感，每页面唯一 |
| `state` | 客户端本地生成后携带 | 必须与 callback 回传值一致 |
| `code_verifier` | 本地随机生成（43-128字符）| 只在 PKCE 场景使用 |
| `sentinel-token` | `sentinel.openai.com/backend-api/sentinel/req` | 每次请求申请，短时有效 |
| `did` / `device_id` | 首次访问时 Cookie 下发 | 整个 Session 生命周期复用 |
| `otp_code` | 邮件 / SMS 中获取 | 一次性，有效期 5-10 分钟 |
