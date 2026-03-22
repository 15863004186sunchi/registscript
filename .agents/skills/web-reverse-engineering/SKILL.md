---
name: web-reverse-engineering
description: >
  面向 Web API 逆向分析的自动化技能套件。
  专注于 HTTP 登录流分析、API 端点变更检测、风控绕过策略、动态参数追踪，
  以及 Token/Session 提取与持久化。适用于高风控 Web 场景（如 OpenAI、Google 等平台）。
---

# Web 逆向自动化 Skill

## 授权声明
本 Skill 仅用于对**已取得合法使用权或授权渗透范围内**的系统进行分析与测试。
严格禁止对未授权系统使用。

---

## 触发条件

当用户遇到以下任意场景时，自动激活本 Skill：

- 需要分析某个网站（如 `auth.openai.com`）的 **登录 / 注册 / OAuth 流程**
- HTTP 请求返回非预期状态码（`404`、`400`、`401`、`403` 等），需要定位**真实端点**
- 遇到**反爬机制**或**风控拦截**：Turnstile、Cloudflare、Sentinel Token 等
- 需要提取并持久化 Web 会话中的 **Token、Cookie、Session 凭证**
- 进行 **Playwright / curl_cffi 脚本开发**，需要理解真实浏览器的请求结构

---

## 必要输入

执行任意阶段前，请提供以下信息（越详细越准确）：

```text
Target URL:         https://auth.openai.com/log-in/password   # 目标登录页或请求页
Parameters:         password, sentinel-token, screen_hint     # 需要分析的关键参数
Request Method:     POST                                       # HTTP 方法
Known Endpoint:     /api/accounts/user/login                  # 已知的请求端点（可选）
Browser HAR / Log:  <粘贴 F12 网络请求 HAR 导出或截图>          # 核心证据（强烈推荐）
Error:              404 / name not defined / ...              # 遇到的错误（可选）
```

---

## 阶段流程

### Phase 0：证据收集
**目标**：在触碰脚本之前，先将真实浏览器中的行为转化为可分析的原始证据。

1. 让用户在 F12 网络面板中完成目标操作，然后提供：
   - 关键请求的 **URL、Method、Payload、Response Body**
   - `Set-Cookie` 响应头内容
   - 关键 HTTP 状态码序列
2. 如果可以操控浏览器（通过 `chrome-devtools-mcp`）：
   - 打开目标页，复现完整操作序列
   - 记录 `auth.openai.com` 等域下所有 `Fetch/XHR` 请求日志
3. 将证据写入 `artifacts/phase0_evidence.json`

**成功条件**：能确定"真实浏览器发出的请求链"（URL + Payload + Cookie + 顺序）

---

### Phase 1：登录流 / 身份验证链路分析
**目标**：将真实请求序列映射成状态机，找出每个步骤的入口和依赖。

关注以下关键模式：

| 模式 | 识别特征 | 常见处理 |
|------|---------|---------|
| **OAuth PKCE 流** | `state=`, `code_verifier`, `redirect_uri` | 追踪 authorize -> callback 链路 |
| **Sentinel / CSRF Token** | 请求头中带 `openai-sentinel-token` | 分析其生成端点（通常是 `sentinel.openai.com/req`）|
| **状态机跳转** | 响应体中含 `continue_url`, `page.type` | 将 `page.type` 字段映射为状态节点 |
| **无密码登录 OTP** | `page.type == "email_otp_send"` | 区分 GET 触发 vs POST 触发 |
| **风控重定向** | `page.type == "add_phone"` / 302 到验证页 | 分析是否有 bypass 路由 |

输出：`artifacts/phase1_flow_map.json`（包含每个状态节点的 URL、Method、Payload 模板）

---

### Phase 2：动态参数与端点追踪
**目标**：确定哪些参数是动态生成的（每次请求不同），哪些是静态可复用的。

1. **动态参数识别**：
   - `did` / `device_id`：通常在首次访问时通过 Cookie 下发，后续复用
   - `sentinel-token`：每次请求前向 `sentinel.openai.com` 单独申请，有效期短
   - `auth_provider` Cookie：登录成功后下发，含加密 Session

2. **端点变更检测**：
   - 当脚本收到 `404` 或 `405`，对比真实浏览器请求路径
   - 对比策略：提取 JS bundle 中的 API 路径字符串（`/api/accounts/` 前缀）
   - 尝试路径变体：`/user/login` → `/login` → `/password` → `/authorize/continue`

3. **请求头差异分析**：
   - 与真实浏览器对比 `Accept`、`Referer`、`origin`、`content-type`
   - 识别自定义头：`openai-sentinel-token`、`oai-language`、`openai-version`

输出：`artifacts/phase2_params.json`

---

### Phase 3：反风控策略
**目标**：识别当前站点使用的风控手段并制定对应的绕过策略。

| 风控机制 | 识别方法 | 绕过策略 |
|---------|---------|---------|
| **Cloudflare Turnstile** | 请求头含 `cf-turnstile-response` | 使用 `curl_cffi` 浏览器指纹模拟（`impersonate="chrome"`）|
| **设备指纹 (DID)** | Cookie `oai-did` 的生成和绑定 | 在 Session 中持久化 `did`，不要每次重建 |
| **IP 风控** | 同 IP 连续失败 > N 次返回 429 / 403 | 代理轮换 + 随机等待 + 用户行为模拟延迟 |
| **邮件频率限制** | 同邮箱域名短时间内注册被拦截 | 控制每批次注册间隔，使用多个域名子地址 |
| **行为指纹** | 请求过快、缺少常规浏览器头 | 使用 `human_delay()`，补全 Accept-Language、DNT 等头 |
| **screen_hint 识别** | `screen_hint=login` vs `login_or_signup` | 严格与真实浏览器对齐，默认使用 `login_or_signup` |

---

### Phase 4：Python 自动化脚本生成
**目标**：根据分析结果生成可直接运行的 `curl_cffi` 或 `requests` 脚本。

生成规范：
- 始终使用 `requests.Session` 或 `curl_cffi.Session` 确保 Cookie 持久
- 每个 HTTP 步骤单独封装函数，函数名与 `phase1_flow_map` 中的节点一致
- 包含明确的**错误检测和降级逻辑**（如密码登录失败 → 自动切换验证码登录）
- 动态参数通过前置函数获取，不要硬编码
- 生成文件：`artifacts/generated_script.py`

---

### Phase 5：Token 提取与持久化
**目标**：在登录成功后，将必要的鉴权数据保存为可复用的 JSON 文件。

必填字段检查清单：

```json
{
  "access_token":   "<JWT，来自 OAuth callback 或 /session>",
  "id_token":       "<与 access_token 相同，或来自 id_token 字段>",
  "refresh_token":  "<rt_ 开头，或 HTTP-Only Cookie 中>",
  "account_id":     "<来自 JWT Payload: https://api.openai.com/auth.chatgpt_account_id>",
  "email":          "<用户邮箱>",
  "type":           "codex",
  "last_refresh":   "<ISO 8601 时间字符串>",
  "expired":        "<last_refresh + 10天>"
}
```

Token 提取方法优先级：
1. **自动提取**：从 OAuth callback 的 `code` 参数换取 token（精确，推荐）
2. **浏览器脚本提取**：`extract_token.js` 在 `/api/auth/session` 中获取 `accessToken`
3. **Cookie 解析**：从 `oai-client-auth-session` JWT 中手动解析

---

### Phase 6：校验与诊断
**目标**：验证生成的脚本或 Token 的有效性。

运行以下检查：

```
scripts/validate_token.py      # 验证 Token JSON 结构完整性
scripts/test_login_flow.py     # 端到端测试一次完整登录
scripts/check_endpoint.py      # 逐一探测 API 端点可用性
```

校验报告写入 `artifacts/validation_report.json`

---

## 产出要求

当所有阶段完成，本 Skill 必须输出：
- `phase0_evidence.json`：完整的原始请求证据
- `phase1_flow_map.json`：登录状态机地图
- `phase2_params.json`：动态参数与静态参数分类
- `generated_script.py`：可直接运行的 Python 脚本
- Token JSON 文件：字段完整，通过 validate_token.py 验证
- `validation_report.json`：包含全部通过/失败结论

---

## 失败处理原则

- **不要猜测端点**：如果无法通过浏览器证据确认端点，明确报告 Phase 0 失败，请求用户提供 HAR/截图
- **状态码 ≠ 成功**：`200` 但响应体含 `error` 字段也视为失败，深入解析 `page.type`
- **记录所有 4xx/5xx 尝试记录**，包括候选端点和响应内容，便于下次快速对比
- **风控触发时立即停止当前批次**，记录最后成功的状态，不盲目重试

---

## 验收标准

只有满足以下条件，才视为本次分析完成：

- [ ] Phase 0 证据完整（真实浏览器请求链已记录）
- [ ] Phase 1 状态机所有节点 URL 已确认（无猜测）
- [ ] 生成的脚本端到端运行至少一次成功
- [ ] Token JSON 通过结构验证
- [ ] validation_report 无 FAILED 项

---

## 参考资源

- `references/http-login-patterns.md`：常见 Web 登录模式（OAuth, PKCE, OTP, 密码）
- `references/anti-bot-guide.md`：主流反爬/风控机制分类与对策
- `references/token-extraction.md`：多平台 Token 提取方法速查
- `references/curl-cffi-patterns.md`：curl_cffi 常见使用模式与踩坑记录
