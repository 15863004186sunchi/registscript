# 反爬与风控机制速查

## 1. Cloudflare 系列

### Turnstile（人机验证）
- **识别特征**：请求体含 `cf-turnstile-response` 参数，或页面含 `<div class="cf-turnstile">` 元素
- **强度**：中～高
- **绕过策略**：
  - 使用 `curl_cffi` + `impersonate="chrome"` 模拟浏览器 TLS 指纹
  - 使用真实浏览器 Playwright/Puppeteer 等待 Challenge 处理完成
  - 短期内：携带合法 `cfuvid` Cookie

### Bot Management（Cloudflare Bot score）
- **识别特征**：返回 403 或 429，响应头含 `cf-mitigated: challenge`
- **绕过策略**：
  - 控制请求速率（同 IP < 10 req/min）
  - 使用 `curl_cffi`，避免使用 `requests` 等标准库（TLS 指纹区别巨大）
  - 设置真实的 `User-Agent`、`Accept-Language`、`Accept-Encoding`

---

## 2. Sentinel Token（OpenAI 特有）

- **识别特征**：请求头含 `openai-sentinel-token`，其值为 JSON 字符串（`{"p":"","t":"","c":"...","id":"...","flow":"..."}`)
- **Token 获取流程**：
  ```
  POST https://sentinel.openai.com/backend-api/sentinel/req
  Body: {"p":"","id":"<did>","flow":"<flow_name>"}
  Response: {"token": "xxx"}
  ```
- **Flow 命名规则**：
  - 注册时：`"flow": "authorize_continue"`
  - 密码登录时：`"flow": "username_password_login"`
  - 验证码登录时：`"flow": "email_otp"`
- **注意**：Token **有效期极短**（约 30s），必须请求后立即使用

---

## 3. 设备指纹 / Device ID

- **识别特征**：Cookie `oai-did` 或 `dotcom-did`
- **工作机制**：OpenAI 在首次访问时生成并绑定到 Session，用于追踪行为轨迹
- **绕过策略**：
  - 在整个注册 / 登录 Session 中**复用同一个** `did`，不要每次重新生成
  - 如果使用虚假 `did`，需保证全程一致（请求体、Cookie、日志都要一致）

---

## 4. IP 频率限制 / 地理封禁

- **识别特征**：短时间内返回 `429 Too Many Requests` 或 `403`
- **绕过策略**：
  - 每批次之间加随机等待（5-30 秒）
  - 使用代理 IP 轮换，每个账号用独立 IP
  - 避免并发请求（批量脚本改为串行）

---

## 5. 邮件域名/账号频率封控

- **识别特征**：同域名邮箱短时间内多次注册失败；或触发 `add_phone` 拦截
- **绕过策略**：
  - 使用自定义域名 + Gmail IMAP 组合（每次不同前缀子地址）
  - 不同批次间隔 5 分钟以上
  - 控制每批次数量（< 5 个/小时）

---

## 6. 行为指纹 / 机器人检测

- **识别特征**：请求速度远超人类（< 200ms）、缺少关键浏览器头
- **遗漏头部黑名单**（容易暴露的缺失项）：
  - `Accept-Language`（必须）
  - `Accept-Encoding`（通常需要 `gzip, deflate, br`）
  - `Referer`（每步骤需对应上一步的 URL）
  - `DNT`
- **绕过策略**：
  - 使用 `human_delay(min, max)` 在每步之间随机等待
  - 补全所有浏览器常见请求头
  - 统一使用 `curl_cffi` 的 `impersonate="chrome"` 而非 `requests`

---

## 7. screen_hint / action 字段风控

- **识别特征**：`screen_hint: "login"` 触发强密码验证，`"login_or_signup"` 则更宽松
- **规律总结**：OpenAI 根据 `screen_hint` 值选择不同的验证策略
  - `"login"` → 要求密码 → 密码端点 404
  - `"login_or_signup"` → 直接发验证码 → 无密登录
- **绕过策略**：**始终与真实浏览器行为对齐，使用浏览器 F12 抓包确认正确值**

---

## 风控强度速查

| 风控类型 | 强度 | 可自动绕过 | 降级方案 |
|---------|------|----------|---------|
| Cloudflare Turnstile | 高 | 部分（curl_cffi） | 真实浏览器 |
| Sentinel Token | 中 | ✅ 是 | 复现申请流程 |
| IP 频率 | 中 | ✅ 是 | 代理 + 等待 |
| 邮件频率 | 中 | ✅ 是 | 多域名轮换 |
| 设备指纹 | 中 | ✅ 是 | 复用 DID |
| 手机验证 (add_phone) | 高 | 部分（二次登录绕过）| SMS API / 人工 |
| 行为指纹 | 低～中 | ✅ 是 | 加延迟、补头部 |
