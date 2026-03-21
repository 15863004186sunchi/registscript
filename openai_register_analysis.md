# `openai_register.py` 技术实现原理分析报告

## 1. 脚本概述

`openai_register.py` 是一个用于自动化注册 OpenAI（面向 Codex/ChatGPT 相关服务）账户的 Python 脚本。它通过完全模拟浏览器行为，配合临时邮箱服务和 OAuth 2.0 PKCE 授权流，实现了免密码验证码注册，并最终获取到 OpenAI 平台全套鉴权 Token (包含 `access_token`, `refresh_token` 和 `id_token`)。

## 2. 核心技术依赖

- **`curl_cffi`**: 这是该脚本最核心的网络请求库，替代了传统的 `requests`。由于 OpenAI 前方部署了严格的 Cloudflare 防火墙和 TLS 指纹识别，普通的 Python 网络请求库会被立刻拦截（报 403 HTTP 错误或者被标记为 Bot）。该脚本运用了 `requests.get(impersonate="chrome")` 伪装底层 JA3/TLS 握手特征，从而欺骗并绕过防护系统，达到与真机浏览器相同的效果。
- **Mail.tm API**: 免费且提供 REST API 的开源临时邮箱服务，用于接收和抓取 OpenAI 的六位注册验证码 (Email OTP)。
- **OAuth 2.0 (PKCE 扩展)**: 用于处理免密登录和获取访问令牌授权。

## 3. 核心业务流程分析

整个脚本 `run()` 函数的执行流程犹如一个状态机，严格匹配了用户在真实浏览器中操作的内容：

### 3.1 运行前置检测
1. **网络与代理组装**: 可以通过命令行 `--proxy` 指定代理地址。
2. **基于 Cloudflare 的 IP 锁区验证**:
   访问 `https://cloudflare.com/cdn-cgi/trace` 获取当前代理的出口 `loc`（地区代码）。如果不巧落在了受限的区域（如 `CN`、`HK` ），脚本会判断 IP 不可用，主动抛出异常终止。

### 3.2 临时邮箱申请
1. 调用内部的 `_mailtm_domains` API 获取当前系统可用的后缀域名。
2. 随机生成一组 12 位字符前缀的邮箱地址和随机密码（`oc + token_hex`），向 API 请求注册临时账户。
3. 利用该生成的账号密码换取 Mail.tm 的访问凭证 `Bearer Token`，用于后续请求其收件箱读取验证邮件。

### 3.3 OAuth PKCE 授权请求的发起
执行函数 `generate_oauth_url`：
- 使用 `secrets` 随机生成 `state`（防 CSRF）和 `code_verifier`（PKCE 验证码）。
- 对 `code_verifier` 采用 SHA-256 哈希处理，并使用 Base64 URL Safe 编码生成最终传递的 `code_challenge`。
- 将以上参数拼接在 `https://auth.openai.com/oauth/authorize` 请求之后，设定 `prompt=login`、`codex_cli_simplified_flow=true`，发起授权登录流程请求。

### 3.4 绕过 Sentinel 防管与反爬虫策略
OpenAI 在登录/注册流程中嵌入了内部的 Sentinel 流量监控与防篡改系统：
- 脚本首先提取出最初生成的 `oai-did` (Device ID) 的 Cookie。
- 向 `https://sentinel.openai.com/backend-api/sentinel/req` 请求发送分析报文。在此调用中获取到了一串名为 `sen_token` 的通行证数据。此行为对应了正常用户访问网页时的底层无感验证环节。
- 将验证成功的 Sentinel Token 搭载到特有且关键的 `openai-sentinel-token` Header 请求头内，并正式发起后续的 `/api/accounts/authorize/continue`。如果不用这层逻辑，请求关联联机接口就会直接触发 Cloudflare WAF 拦截风控。

### 3.5 无密注册与 OTP (One Time Password) 验证
采取邮箱免密（Passwordless）流程，极大简化了验证流：
1. 发起验证码触发信件流程：请求 `/api/accounts/passwordless/send-otp`。
2. 调用 `get_oai_code` 函数，通过至多 40 次挂起轮询机制请求 Mail.tm 的账户 `messages` 接口（共计等待约两分钟），当检测到 OpenAI 的信件后，利用正则表达式 `(?<!\d)(\d{6})(?!\d)` 精准捕获邮件正文中的 6 位数字验证码。
3. 填入验证码发送校验：`/api/accounts/email-otp/validate`。

### 3.6 账户初始化与工作空间绑定
1. 调用 `/api/accounts/create_account` 初始化配置，提交硬编码配置属性字典（设定注册名称统一为 "Neo"，生日固定为 "2000-02-20"）。
2. 从响应头的 Cookie 信息中解码截获 `oai-client-auth-session` 这一 JWT（JSON Web Token）明文数据。
3. 利用自带的 Base64 拆解方法提取载荷内容（Payload），提取当前账号绑定分配出来的初始 `workspace_id`。
4. 提交 Workspace 绑定选定：`/api/accounts/workspace/select`，最终响应会给出一个非常长的 `continue_url`。

### 3.7 回调链拦截及利用 Code 换取最终 Token
1. 使用 `requests.get(current_url, allow_redirects=False)`，关闭自动跟随重定向行为。这样可以通过逐级拦截解析 Response Headers 中的 `Location`，手动控制网络流向下的所有的 301/302 重定向链条。
2. 直到重定向目标地址带有 `code=` 和 `state=` 查询参数时，拦截该 URL（其实际过程对应网页上：账号登录逻辑完成并跳转至回调本地 `http://localhost:1455` 这个伪造客户端监听进程）。
3. 调用 `submit_callback_url`，同时携带之前生成的 PKCE `code_verifier` 以及返回包里的 `code` 并向 `TOKEN_URL` 端点发起 Code Exchange Token 认证交互过程。
4. 获得 OpenAI 系统下发的最底层 `access_token`、`refresh_token` 并组合序列化打包持久保存到当前运行目录磁盘生成的 `.json` 文件内。

## 4. 技术亮点总结

- **无客户端协议级自动化 (Headless Automation Without WebDriver)**: 这种技术不同于 Selenium/Playwright 通过底层打开浏览器 GUI 与渲染树。脚本完全基于协议层面的报文拆解和请求重排（Traffic Replay），配合 `curl_cffi` 的底层握手级别欺骗，具备极佳的运行速度及资源极简占用率。使得多线程/协程、低成本地高并发注册行为变得可能。
- **无依赖剥离实现 (No Extra Dependencies JWT Parsing)**: 没有额外接入如 `PyJWT` 等庞大组件，直接用 Standard 库手撸底层 JWT 轻量级解码、PKCE 加密算法及 Callback URL 参数剥离映射器，兼顾了精干体积及部署迁移维护成本。
- **动态防抖与断流恢复**: 设计上在异常捕捉后通过长短不一的睡眠机制 `time.sleep` 以及错误 `Exception` 跳过方式实现了业务的鲁棒性保障。

## 5. 项目拓展与风险提示
- 随机账号硬编码写死的名称与出生年月（Neo, 2000-02-20）。在大规模执行场景下容易积累非常明显的行为指纹库从而陷入集群注册模式被全盘批量 Block。
- API 和重定向端点（例如 Sentinel 鉴权链路）往往都是被各大厂安全团队随时修改迭代的对象，当 OpenAI 系统结构改版或鉴权路径发生变迁（例如增加 Turnstile、Arkose 等新一代前端人机验证器）时，此类硬编码基于重放大范围会立刻失去有效性。
