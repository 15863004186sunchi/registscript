import json
import os
import re
import sys
import time
import uuid
import math
import random
import string
import secrets
import hashlib
import base64
import threading
import argparse
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs, urlencode, quote
from dataclasses import dataclass
from typing import Any, Dict, Optional, List
import urllib.parse
import urllib.request
import urllib.error
from faker import Faker

from curl_cffi import requests

# ==========================================
# OpenAI Sentinel POW Solver (Anti-Bot)
# ==========================================

DEFAULT_SENTINEL_DIFF = "0fffff"
DEFAULT_MAX_ITERATIONS = 500_000
_SCREEN_SIGNATURES = (3000, 3120, 4000, 4160)
_LANGUAGE_SIGNATURE = "en-US,es-US,en,es"
_NAVIGATOR_KEYS = ("location", "ontransitionend", "onprogress")
_WINDOW_KEYS = ("window", "document", "navigator")

def _format_browser_time() -> str:
    browser_now = datetime.now(timezone(timedelta(hours=-5)))
    return browser_now.strftime("%a %b %d %Y %H:%M:%S") + " GMT-0500 (Eastern Standard Time)"

def build_sentinel_config(user_agent: str) -> list:
    perf_ms = time.perf_counter() * 1000
    epoch_ms = (time.time() * 1000) - perf_ms
    return [
        random.choice(_SCREEN_SIGNATURES),
        _format_browser_time(),
        4294705152,
        0,
        user_agent,
        "",
        "",
        "en-US",
        _LANGUAGE_SIGNATURE,
        0,
        random.choice(_NAVIGATOR_KEYS),
        "location",
        random.choice(_WINDOW_KEYS),
        perf_ms,
        str(uuid.uuid4()),
        "",
        8,
        epoch_ms,
    ]

def _encode_pow_payload(config: list, nonce: int) -> bytes:
    prefix = (json.dumps(config[:3], separators=(",", ":"), ensure_ascii=False)[:-1] + ",").encode("utf-8")
    middle = (
        "," + json.dumps(config[4:9], separators=(",", ":"), ensure_ascii=False)[1:-1] + ","
    ).encode("utf-8")
    suffix = ("," + json.dumps(config[10:], separators=(",", ":"), ensure_ascii=False)[1:]).encode("utf-8")
    body = prefix + str(nonce).encode("ascii") + middle + str(nonce >> 1).encode("ascii") + suffix
    return base64.b64encode(body)

def solve_sentinel_pow(seed: str, difficulty: str, config: list, max_iterations: int = DEFAULT_MAX_ITERATIONS) -> str:
    seed_bytes = seed.encode("utf-8")
    target = bytes.fromhex(difficulty)
    prefix_length = len(target)
    for nonce in range(max_iterations):
        encoded = _encode_pow_payload(config, nonce)
        digest = hashlib.sha3_512(seed_bytes + encoded).digest()
        if digest[:prefix_length] <= target:
            return encoded.decode("ascii")
    return ""

def get_sentinel_pow_token(user_agent: str) -> str:
    config = build_sentinel_config(user_agent)
    seed = format(random.random())
    solution = solve_sentinel_pow(seed, DEFAULT_SENTINEL_DIFF, config)
    return f"gAAAAAC{solution}" if solution else ""

def get_real_sentinel_token(did: str, flow: str, proxies: Any, ua: str) -> str:
    """获取真正的 OpenAI Sentinel Token (包含 POW 求解)"""
    p_token = get_sentinel_pow_token(ua)
    try:
        resp = requests.post(
            "https://sentinel.openai.com/backend-api/sentinel/req",
            headers={
                "origin": "https://sentinel.openai.com",
                "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
                "content-type": "text/plain;charset=UTF-8",
                "user-agent": ua
            },
            data=json.dumps({"p": p_token, "id": did, "flow": flow}),
            proxies=proxies,
            impersonate="chrome",
            timeout=15,
        )
        if resp.status_code == 200:
            token = resp.json().get("token", "")
            if token:
                return f'{{"p": "", "t": "", "c": "{token}", "id": "{did}", "flow": "{flow}"}}'
    except Exception as e:
        print(f"[Error] Sentinel 请求失败: {e}")
    return ""

# ==========================================
# 重定向追踪工具
# ==========================================

def follow_openai_redirects(s: requests.Session, start_url: str, proxies: Any = None) -> str:
    """跟随 OpenAI 的重定向链，找到最终的回调 URL"""
    current_url = start_url
    for i in range(10):
        try:
            resp = s.get(current_url, allow_redirects=False, timeout=15, proxies=proxies)
            location = resp.headers.get("Location")
            if not location:
                # 如果没重定向了，看看当前 URL 是否就是回调
                if "code=" in current_url and "state=" in current_url:
                    return current_url
                break
            
            # 构建完整 URL
            current_url = urllib.parse.urljoin(current_url, location)
            if "code=" in current_url and "state=" in current_url:
                print(f"[*] 找到回调 URL (重定向 {i+1} 步)")
                return current_url
        except Exception as e:
            print(f"[Error] 跟随重定向出错: {e}")
            break
    return ""


# ==========================================
# 行为抖动 & 身份随机化工具
# ==========================================

_fake = Faker("en_US")


def human_delay(min_sec: float = 1.0, max_sec: float = 3.5) -> None:
    """模拟人类操作的随机停顿，降低规律性行为特征"""
    time.sleep(random.uniform(min_sec, max_sec))


def generate_random_identity() -> tuple:
    """随机生成注册用名字和生日，避免硬编码带来的特征指纹"""
    name = f"{_fake.first_name()} {_fake.last_name()}"
    # 生日落在 1980-01-01 ~ 2003-12-31 之间，确保成年且分布自然
    start = datetime(1980, 1, 1)
    end = datetime(2003, 12, 31)
    days_range = (end - start).days
    birthdate = (start + timedelta(days=random.randint(0, days_range))).strftime("%Y-%m-%d")
    return name, birthdate


ACCOUNTS_FILE = "accounts.txt"


def save_credentials(email: str, password: str, token_file: str = "") -> None:
    """将注册账号的邮箱、密码、token文件名追加写入 accounts.txt"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] email={email} | password={password}"
    if token_file:
        line += f" | token_file={token_file}"
    line += "\n"
    with open(ACCOUNTS_FILE, "a", encoding="utf-8") as f:
        f.write(line)
    print(f"[*] 账号信息已追加到 {ACCOUNTS_FILE}")


# ==========================================
# 自定义域名 + Gmail IMAP（最高优先级，域名不在任何黑名单）
# ==========================================

# ⚙️ 配置区（根据你的实际信息填写）
# 支持多域名：每次注册时从列表中随机选一个，提升通过率
CUSTOM_EMAIL_DOMAINS = [
    "geeksun.cc.cd",
    "geeksun.ccwu.cc",
    "geeksun.us.ci",
]                                    # Cloudflare Email Routing 托管的域名列表（留空列表则使用随机公共邮箱）
CUSTOM_EMAIL_DOMAIN  = ""          # 兼容旧字段（单域名模式，留空即走多域名逻辑）
GMAIL_USER           = "geeksunchi@gmail.com"  # 接收转发的 Gmail 地址
GMAIL_APP_PASSWORD   = "jcfk oprb igpm wbwh"          # Gmail 应用专用密码（去掉空格后填入）


def _pick_custom_domain() -> str:
    """从多域名列表中随机选一个；若旧字段 CUSTOM_EMAIL_DOMAIN 有值则优先使用。"""
    if CUSTOM_EMAIL_DOMAIN:
        return CUSTOM_EMAIL_DOMAIN
    if CUSTOM_EMAIL_DOMAINS:
        return random.choice(CUSTOM_EMAIL_DOMAINS)
    return ""


def generate_custom_email() -> str:
    """随机生成一个基于 Cloudflare 域名转发的邮箱地址，每次注册换一个域名"""
    domain = _pick_custom_domain()
    prefix = "".join(random.choices(string.ascii_lowercase, k=random.randint(3, 5)))
    local = f"{prefix}{secrets.token_hex(4)}"
    return f"{local}@{domain}"

def get_gmail_otp(recipient_email: str, proxies: Any = None, ignore_code: str = "") -> str:
    """
    通过 Gmail IMAP 轮询提取验证码。
    改进点：不再仅依赖 UNSEEN 标记，因为用户手动预览或 Gmail 自动加载可能会清除未读状态。
    逻辑：获取最新的 15 封来自 openai.com 的邮件，排除掉 ignore_code 后返回第一个符合 6 位数字格式的代码。
    """
    import imaplib
    import email as emaillib
    from email.header import decode_header

    regex = r"(?<!\d)(\d{6})(?!\d)"
    seen_ids: set = set()
    folders_to_check = ["INBOX", "[Gmail]/Spam", "[Gmail]/All Mail"]

    print(f"[*] 正在等待邮箱 {recipient_email} 的验证码...", end="", flush=True)

    for _ in range(40):
        print(".", end="", flush=True)
        try:
            with imaplib.IMAP4_SSL("imap.gmail.com", 993) as imap:
                imap.login(GMAIL_USER, GMAIL_APP_PASSWORD)

                for folder in folders_to_check:
                    try:
                        status, _ = imap.select(folder, readonly=True) # 使用只读模式避免干扰标记
                        if status != "OK":
                            continue

                        # 搜索来自 openai.com 的邮件（包含已读和未读）
                        _, msg_ids = imap.search(None, 'FROM "openai.com"')
                        # 取最新的 10 个数据
                        target_ids = (msg_ids[0].split() or [])[-10:]
                        for num in reversed(target_ids): # 从最新的开始处理
                            if num in seen_ids:
                                continue
                            seen_ids.add(num)

                            _, data = imap.fetch(num, "(RFC822)")
                            if not data or not data[0]:
                                continue

                            msg = emaillib.message_from_bytes(data[0][1])
                            # 检查收件人（支持 Cloudflare 转发后的 To 头）
                            to_header = str(msg.get("To") or "").lower()
                            if recipient_email.lower() not in to_header and recipient_email.split("@")[0].lower() not in to_header:
                                continue

                            # 提取正文
                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() in ("text/plain", "text/html"):
                                        try:
                                            body += part.get_payload(decode=True).decode("utf-8", "replace")
                                        except: pass
                            else:
                                try:
                                    body = msg.get_payload(decode=True).decode("utf-8", "replace")
                                except:
                                    body = str(msg.get_payload())

                            m = re.search(regex, body)
                            if m:
                                code = m.group(1)
                                if ignore_code and code == ignore_code:
                                    # 抓到了旧的记录，继续找
                                    continue
                                print(f" 抓到啦! 验证码: {code}")
                                return code
                    except Exception:
                        continue
        except Exception:
            pass

        time.sleep(3)

    print(" 超时，未收到验证码")
    return ""


# ==========================================
# Tempmail.lol 临时邮箱 API（最新添加，第一优先级）
# ==========================================
TEMPMAIL_LOL_API = "https://api.tempmail.lol/v2"

def get_tempmail_lol_email(proxies: Any = None) -> tuple:
    try:
        resp = requests.post(f"{TEMPMAIL_LOL_API}/inbox/create", json={}, proxies=proxies, impersonate="chrome", timeout=15)
        if resp.status_code in (200, 201):
            data = resp.json()
            email = str(data.get("address", "")).strip()
            token = str(data.get("token", "")).strip()
            if email and token:
                print(f"[*] 使用服务商: Tempmail.lol")
                return email, token, "tempmail_lol"
    except Exception as e:
        print(f"[Error] Tempmail.lol 初始化失败: {e}")
    return "", "", ""

def get_tempmail_lol_code(token: str, email: str, proxies: Any = None, ignore_code: str = "") -> str:
    regex = r"(?<!\d)(\d{6})(?!\d)"
    seen_ids: set = set()
    print(f"[*] 正在等待邮箱 {email} 的验证码...", end="", flush=True)

    for _ in range(40):
        print(".", end="", flush=True)
        try:
            resp = requests.get(
                f"{TEMPMAIL_LOL_API}/inbox",
                params={"token": token},
                headers={"Accept": "application/json"},
                proxies=proxies,
                impersonate="chrome",
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                emails = data.get("emails", []) if isinstance(data, dict) else []
                for msg in emails:
                    if not isinstance(msg, dict): continue
                    msg_date = msg.get("date", 0)
                    if not msg_date or msg_date in seen_ids: continue
                    seen_ids.add(msg_date)

                    sender = str(msg.get("from", "")).lower()
                    subject = str(msg.get("subject", ""))
                    body = str(msg.get("body", ""))
                    html = str(msg.get("html", ""))
                    content = f"{sender}\n{subject}\n{body}\n{html}"

                    if "openai" in sender or "openai" in content.lower():
                        m = re.search(regex, content)
                        if m:
                            code = m.group(1)
                            if ignore_code and code == ignore_code:
                                continue
                            print(" 抓到啦! 验证码:", code)
                            return code
        except Exception:
            pass
        time.sleep(3)
    print(" 超时，未收到验证码")
    return ""


# ==========================================
# Guerrilla Mail 临时邮箱（优先使用，域名未被 OpenAI 批量屏蔽）
# ==========================================

GUERRILLA_API = "https://api.guerrillamail.com/ajax.php"



def _guerrilla_session(proxies: Any = None) -> tuple:
    """获取 Guerrilla Mail 的 sid_token 和随机邮箱地址"""
    resp = requests.get(
        GUERRILLA_API,
        params={"f": "get_email_address", "lang": "en"},
        proxies=proxies,
        impersonate="chrome",
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Guerrilla Mail 初始化失败: {resp.status_code}")
    data = resp.json()
    sid = str(data.get("sid_token") or "").strip()
    email_addr = str(data.get("email_addr") or "").strip()
    if not sid or not email_addr:
        raise RuntimeError("Guerrilla Mail 返回数据异常")
    return sid, email_addr


def _guerrilla_set_email(sid: str, local: str, proxies: Any = None) -> str:
    """指定邮箱前缀（本地部分），返回完整邮箱地址"""
    resp = requests.get(
        GUERRILLA_API,
        params={"f": "set_email_user", "email_user": local, "sid_token": sid, "lang": "en"},
        proxies=proxies,
        impersonate="chrome",
        timeout=15,
    )
    if resp.status_code == 200:
        data = resp.json()
        addr = str(data.get("email_addr") or "").strip()
        if addr:
            return addr
    return ""


def get_guerrilla_email(proxies: Any = None) -> tuple:
    """创建 Guerrilla Mail 邮箱，返回 (email, sid_token, 'guerrilla')"""
    try:
        sid, default_addr = _guerrilla_session(proxies)
        # 用 oc+随机串 作为本地部分，保持与其他流程一致的格式
        local = f"oc{secrets.token_hex(5)}"
        custom_addr = _guerrilla_set_email(sid, local, proxies)
        email = custom_addr if custom_addr else default_addr
        print(f"[*] 使用服务商: Guerrilla Mail")
        return email, sid, "guerrilla"
    except Exception as e:
        print(f"[Error] Guerrilla Mail 初始化失败: {e}")
        return "", "", ""


def get_guerrilla_code(sid: str, email: str, proxies: Any = None, ignore_code: str = "") -> str:
    """轮询 Guerrilla Mail 收件箱获取 OpenAI 验证码"""
    regex = r"(?<!\d)(\d{6})(?!\d)"
    seen_ids: set = set()
    print(f"[*] 正在等待邮箱 {email} 的验证码...", end="", flush=True)

    for _ in range(40):
        print(".", end="", flush=True)
        try:
            resp = requests.get(
                GUERRILLA_API,
                params={"f": "get_email_list", "offset": 0, "sid_token": sid},
                proxies=proxies,
                impersonate="chrome",
                timeout=15,
            )
            if resp.status_code != 200:
                time.sleep(3)
                continue

            data = resp.json()
            messages = data.get("list") or []

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                msg_id = str(msg.get("mail_id") or "").strip()
                if not msg_id or msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id)

                from_addr = str(msg.get("mail_from") or "").lower()
                subject = str(msg.get("mail_subject") or "")
                excerpt = str(msg.get("mail_excerpt") or "")
                combined = f"{from_addr} {subject} {excerpt}"

                if "openai" not in combined.lower():
                    # 拉取邮件全文再检查
                    fetch_resp = requests.get(
                        GUERRILLA_API,
                        params={"f": "fetch_email", "email_id": msg_id, "sid_token": sid},
                        proxies=proxies,
                        impersonate="chrome",
                        timeout=15,
                    )
                    if fetch_resp.status_code != 200:
                        continue
                    mail_body = str(fetch_resp.json().get("mail_body") or "")
                    if "openai" not in (from_addr + mail_body).lower():
                        continue
                    combined = mail_body

                m = re.search(regex, combined)
                if m:
                    code = m.group(1)
                    if ignore_code and code == ignore_code:
                        continue
                    print(" 抓到啦! 验证码:", code)
                    return code
        except Exception:
            pass

        time.sleep(3)

    print(" 超时，未收到验证码")
    return ""


# ==========================================
# Mail.tm 临时邮箱 API（备用）
# ==========================================

# 兼容 Mail.tm API 的服务商列表（备用）
MAILTM_BASES = [
    "https://api.mail.gw",
    "https://api.mail.tm",
]

MAILTM_BASE = "https://api.mail.tm"   # 供内部函数默认使用


def _mailtm_headers(*, token: str = "", use_json: bool = False) -> Dict[str, Any]:
    headers = {"Accept": "application/json"}
    if use_json:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _mailtm_domains(proxies: Any = None, base: str = MAILTM_BASE) -> List[str]:
    resp = requests.get(
        f"{base}/domains",
        headers=_mailtm_headers(),
        proxies=proxies,
        impersonate="chrome",
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"获取 Mail.tm 域名失败，状态码: {resp.status_code}")

    data = resp.json()
    domains = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("hydra:member") or data.get("items") or []
    else:
        items = []

    blacklist = ["geeksun.ccwu.cc", "tempmail.icu", "mail.icu"]  # 排除已知的 OpenAI 黑名单/不可用域名
    for item in items:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "").strip()
        is_active = item.get("isActive", True)
        is_private = item.get("isPrivate", False)
        if domain and is_active and not is_private:
            if domain in blacklist:
                continue
            domains.append(domain)

    return domains


def get_mailtm_email(proxies: Any = None) -> tuple:
    """内部辅助：尝试使用 Mail.tm 及其镜像获取邮箱"""
    try:
        bases_shuffled = MAILTM_BASES[:]
        random.shuffle(bases_shuffled)

        for base in bases_shuffled:
            try:
                domains = _mailtm_domains(proxies, base=base)
            except Exception:
                continue
            if not domains:
                continue

            domain = random.choice(domains)
            for _ in range(5):
                local = f"oc{secrets.token_hex(5)}"
                email = f"{local}@{domain}"
                password = secrets.token_urlsafe(18)

                create_resp = requests.post(
                    f"{base}/accounts",
                    headers=_mailtm_headers(use_json=True),
                    json={"address": email, "password": password},
                    proxies=proxies,
                    impersonate="chrome",
                    timeout=15,
                )
                if create_resp.status_code not in (200, 201):
                    continue

                token_resp = requests.post(
                    f"{base}/token",
                    headers=_mailtm_headers(use_json=True),
                    json={"address": email, "password": password},
                    proxies=proxies,
                    impersonate="chrome",
                    timeout=15,
                )
                if token_resp.status_code == 200:
                    tok = str(token_resp.json().get("token") or "").strip()
                    if tok:
                        print(f"[*] 使用服务商: {base}")
                        return email, tok, base
    except Exception as e:
        print(f"[Error] 请求 Mail.tm API 出错: {e}")
    return "", "", ""


def get_email_and_token(proxies: Any = None) -> tuple:
    """创建临时邮箱并获取轮询凭证，自定义域名优先，其他免费服务商随机"""
    if (CUSTOM_EMAIL_DOMAINS or CUSTOM_EMAIL_DOMAIN) and GMAIL_USER and GMAIL_APP_PASSWORD:
        email = generate_custom_email()
        domain = email.split("@")[-1]
        print(f"[*] 使用服务商: 自定义域名 + Gmail IMAP ({domain})")
        return email, "gmail_imap_token", "custom_gmail"

    # 按反封禁通过率设置优先级（不要倒序或打乱）
    providers = [
        get_tempmail_lol_email,  # 成功率目前最高
        get_guerrilla_email,
        get_mailtm_email
    ]

    for provider_func in providers:
        email, token, provider_name = provider_func(proxies)
        if email and token:
            return email, token, provider_name

    print("[Error] 所有临时邮箱服务商均尝试失败")
    return "", "", ""


def get_oai_code(token: str, email: str, proxies: Any = None, base: str = MAILTM_BASE, ignore_code: str = "") -> str:
    """使用指定服务商的 Token 轮询获取 OpenAI 验证码"""
    url_list = f"{base}/messages"
    regex = r"(?<!\d)(\d{6})(?!\d)"
    seen_ids: set[str] = set()

    print(f"[*] 正在等待邮箱 {email} 的验证码...", end="", flush=True)

    for _ in range(40):
        print(".", end="", flush=True)
        try:
            resp = requests.get(
                url_list,
                headers=_mailtm_headers(token=token),
                proxies=proxies,
                impersonate="chrome",
                timeout=15,
            )
            if resp.status_code != 200:
                time.sleep(3)
                continue

            data = resp.json()
            if isinstance(data, list):
                messages = data
            elif isinstance(data, dict):
                messages = data.get("hydra:member") or data.get("messages") or []
            else:
                messages = []

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                msg_id = str(msg.get("id") or "").strip()
                if not msg_id or msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id)

                read_resp = requests.get(
                    f"{base}/messages/{msg_id}",
                    headers=_mailtm_headers(token=token),
                    proxies=proxies,
                    impersonate="chrome",
                    timeout=15,
                )
                if read_resp.status_code != 200:
                    continue

                mail_data = read_resp.json()
                sender = str(
                    ((mail_data.get("from") or {}).get("address") or "")
                ).lower()
                subject = str(mail_data.get("subject") or "")
                intro = str(mail_data.get("intro") or "")
                text = str(mail_data.get("text") or "")
                html = mail_data.get("html") or ""
                if isinstance(html, list):
                    html = "\n".join(str(x) for x in html)
                content = "\n".join([subject, intro, text, str(html)])

                if "openai" not in sender and "openai" not in content.lower():
                    continue

                m = re.search(regex, content)
                if m:
                    code = m.group(1)
                    if ignore_code and code == ignore_code:
                        continue
                    print(" 抓到啦! 验证码:", code)
                    return code
        except Exception:
            pass

        time.sleep(3)

    print(" 超时，未收到验证码")
    return ""


# ==========================================
# OAuth 授权与辅助函数
# ==========================================

AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"

DEFAULT_REDIRECT_URI = f"http://localhost:1455/auth/callback"
DEFAULT_SCOPE = "openid email profile offline_access"


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sha256_b64url_no_pad(s: str) -> str:
    return _b64url_no_pad(hashlib.sha256(s.encode("ascii")).digest())


def _random_state(nbytes: int = 16) -> str:
    return secrets.token_urlsafe(nbytes)


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def _parse_callback_url(callback_url: str) -> Dict[str, Any]:
    candidate = callback_url.strip()
    if not candidate:
        return {"code": "", "state": "", "error": "", "error_description": ""}

    if "://" not in candidate:
        if candidate.startswith("?"):
            candidate = f"http://localhost{candidate}"
        elif any(ch in candidate for ch in "/?#") or ":" in candidate:
            candidate = f"http://{candidate}"
        elif "=" in candidate:
            candidate = f"http://localhost/?{candidate}"

    parsed = urllib.parse.urlparse(candidate)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    fragment = urllib.parse.parse_qs(parsed.fragment, keep_blank_values=True)

    for key, values in fragment.items():
        if key not in query or not query[key] or not (query[key][0] or "").strip():
            query[key] = values

    def get1(k: str) -> str:
        v = query.get(k, [""])
        return (v[0] or "").strip()

    code = get1("code")
    state = get1("state")
    error = get1("error")
    error_description = get1("error_description")

    if code and not state and "#" in code:
        code, state = code.split("#", 1)

    if not error and error_description:
        error, error_description = error_description, ""

    return {
        "code": code,
        "state": state,
        "error": error,
        "error_description": error_description,
    }


def _jwt_claims_no_verify(id_token: str) -> Dict[str, Any]:
    if not id_token or id_token.count(".") < 2:
        return {}
    payload_b64 = id_token.split(".")[1]
    pad = "=" * ((4 - (len(payload_b64) % 4)) % 4)
    try:
        payload = base64.urlsafe_b64decode((payload_b64 + pad).encode("ascii"))
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return {}


def _decode_jwt_segment(seg: str) -> Dict[str, Any]:
    raw = (seg or "").strip()
    if not raw:
        return {}
    pad = "=" * ((4 - (len(raw) % 4)) % 4)
    try:
        decoded = base64.urlsafe_b64decode((raw + pad).encode("ascii"))
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}


def _to_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _post_form(url: str, data: Dict[str, str], timeout: int = 30, proxies: Any = None) -> Dict[str, Any]:
    """发送 POST 表单请求，支持代理和浏览器指纹"""
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    }
    try:
        resp = requests.post(
            url,
            data=data,
            headers=headers,
            timeout=timeout,
            proxies=proxies,
            impersonate="chrome"
        )
        if resp.status_code != 200:
            raise RuntimeError(f"token exchange failed: {resp.status_code}: {resp.text}")
        return resp.json()
    except Exception as e:
        raise RuntimeError(f"token exchange failed: {e}") from e


@dataclass(frozen=True)
class OAuthStart:
    auth_url: str
    state: str
    code_verifier: str
    redirect_uri: str


def generate_oauth_url(
    *, redirect_uri: str = DEFAULT_REDIRECT_URI, scope: str = DEFAULT_SCOPE
) -> OAuthStart:
    state = _random_state()
    code_verifier = _pkce_verifier()
    code_challenge = _sha256_b64url_no_pad(code_verifier)

    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "login",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return OAuthStart(
        auth_url=auth_url,
        state=state,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
    )


def submit_callback_url(
    *,
    callback_url: str,
    expected_state: str,
    code_verifier: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    proxies: Any = None,
) -> str:
    cb = _parse_callback_url(callback_url)
    if cb["error"]:
        desc = cb["error_description"]
        raise RuntimeError(f"oauth error: {cb['error']}: {desc}".strip())

    if not cb["code"]:
        raise ValueError("callback url missing ?code=")
    if not cb["state"]:
        raise ValueError("callback url missing ?state=")
    if cb["state"] != expected_state:
        raise ValueError("state mismatch")

    token_resp = _post_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": cb["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
        proxies=proxies
    )

    access_token = (token_resp.get("access_token") or "").strip()
    refresh_token = (token_resp.get("refresh_token") or "").strip()
    id_token = (token_resp.get("id_token") or "").strip()
    expires_in = _to_int(token_resp.get("expires_in"))

    claims = _jwt_claims_no_verify(id_token)
    email = str(claims.get("email") or "").strip()
    auth_claims = claims.get("https://api.openai.com/auth") or {}
    account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()

    now = int(time.time())
    expired_rfc3339 = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + max(expires_in, 0))
    )
    now_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

    config = {
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": account_id,
        "last_refresh": now_rfc3339,
        "email": email,
        "type": "codex",
        "expired": expired_rfc3339,
    }

    return json.dumps(config, ensure_ascii=False, separators=(",", ":"))


# ==========================================
# 核心注册逻辑
# ==========================================


def run(proxy: Optional[str]) -> Optional[str]:
    proxies: Any = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    s = requests.Session(proxies=proxies, impersonate="chrome")

    try:
        trace = s.get("https://cloudflare.com/cdn-cgi/trace", timeout=10)
        trace = trace.text
        loc_re = re.search(r"^loc=(.+)$", trace, re.MULTILINE)
        loc = loc_re.group(1) if loc_re else None
        print(f"[*] 当前 IP 所在地: {loc}")
        if loc == "CN" or loc == "HK":
            raise RuntimeError("检查代理哦w - 所在地不支持")
    except Exception as e:
        print(f"[Error] 网络连接检查失败: {e}")
        return None

    email, dev_token, mail_base = get_email_and_token(proxies)
    if not email or not dev_token:
        return None
    print(f"[*] 成功获取临时邮箱与授权: {email} (via {mail_base})")

    oauth = generate_oauth_url()
    url = oauth.auth_url

    try:
        resp = s.get(url, timeout=15)
        did = s.cookies.get("oai-did")
        print(f"[*] Device ID: {did}")

        signup_body = f'{{"username":{{"value":"{email}","kind":"email"}},"screen_hint":"signup"}}'
        sen_req_body = f'{{"p":"","id":"{did}","flow":"authorize_continue"}}'

        sen_resp = requests.post(
            "https://sentinel.openai.com/backend-api/sentinel/req",
            headers={
                "origin": "https://sentinel.openai.com",
                "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
                "content-type": "text/plain;charset=UTF-8",
            },
            data=sen_req_body,
            proxies=proxies,
            impersonate="chrome",
            timeout=15,
        )

        if sen_resp.status_code != 200:
            print(f"[Error] Sentinel 异常拦截，状态码: {sen_resp.status_code}")
            return None

        sen_token = sen_resp.json()["token"]
        sentinel = f'{{"p": "", "t": "", "c": "{sen_token}", "id": "{did}", "flow": "authorize_continue"}}'

        signup_resp = s.post(
            "https://auth.openai.com/api/accounts/authorize/continue",
            headers={
                "referer": "https://auth.openai.com/create-account",
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel,
            },
            data=signup_body,
        )
        print(f"[*] 提交注册表单状态: {signup_resp.status_code}")
        # === 诊断：打印 authorize/continue 响应，检查是否返回了新的 token/state ===
        try:
            signup_json = signup_resp.json()
            print(f"[DEBUG] authorize/continue 响应体: {json.dumps(signup_json, ensure_ascii=False)[:500]}")
        except Exception:
            print(f"[DEBUG] authorize/continue 响应体(raw): {signup_resp.text[:500]}")
            signup_json = {}
        print(f"[DEBUG] authorize/continue Set-Cookie: {signup_resp.headers.get('Set-Cookie', '(无)')[:80]}...")
        # =======================================================================
        human_delay(1.5, 4.0)  # 模拟用户阅读页面/等待跳转

        # ------------------------------------------------------------------
        # 追随 continue_url（维持 session 状态进入密码设置页）
        # ------------------------------------------------------------------
        continue_url_page = str((signup_json or {}).get("continue_url") or "").strip()
        if continue_url_page:
            print(f"[*] 追随 continue_url: {continue_url_page}")
            s.get(continue_url_page, timeout=15)
            human_delay(1.0, 2.5)

        # ------------------------------------------------------------------
        # 重新申请 Sentinel token（密码设置页需要新的验证）
        # ------------------------------------------------------------------
        sen_req_body2 = f'{{"p":"","id":"{did}","flow":"username_password_create"}}'
        sen_resp2 = requests.post(
            "https://sentinel.openai.com/backend-api/sentinel/req",
            headers={
                "origin": "https://sentinel.openai.com",
                "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
                "content-type": "text/plain;charset=UTF-8",
            },
            data=sen_req_body2,
            proxies=proxies,
            impersonate="chrome",
            timeout=15,
        )
        print(f"[DEBUG] Sentinel2 状态码: {sen_resp2.status_code}")
        if sen_resp2.status_code != 200:
            print(f"[Error] 第二次 Sentinel 失败")
            return None
        sen_token2 = sen_resp2.json()["token"]
        sentinel2 = f'{{"p": "", "t": "", "c": "{sen_token2}", "id": "{did}", "flow": "username_password_create"}}'

        # ------------------------------------------------------------------
        # 设置随机密码（替代无密验证流）
        # ------------------------------------------------------------------
        reg_password = secrets.token_urlsafe(18)  # 随机强密码
        print(f"[*] 生成注册密码: {reg_password}")
        password_body = json.dumps({
            "password": reg_password,
            "username": email,          # 纯字符串，与浏览器行为一致
        })
        password_resp = s.post(
            "https://auth.openai.com/api/accounts/user/register",
            headers={
                "referer": "https://auth.openai.com/create-account/password",
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel2,
            },
            data=password_body,
        )
        print(f"[*] 设置密码状态: {password_resp.status_code}")
        try:
            print(f"[DEBUG] 设置密码响应体: {password_resp.json()}")
        except Exception:
            print(f"[DEBUG] 设置密码响应体(raw): {password_resp.text[:300]}")
        if password_resp.status_code not in (200, 201, 204):
            print("[Error] 设置密码失败")
            return None

        # 密码设置成功后立即记录账号信息（不含 token 文件名，稍后由 main 补充）
        save_credentials(email, reg_password)
        human_delay(1.0, 2.5)

        # ------------------------------------------------------------------
        # 触发邀请验证邮件 OTP（新的端点）
        # ------------------------------------------------------------------
        otp_resp = s.post(
            "https://auth.openai.com/api/accounts/email-otp/send",
            headers={
                "referer": "https://auth.openai.com/create-account/verify-email",
                "accept": "application/json",
                "content-type": "application/json",
            },
            proxies=proxies
        )
        print(f"[*] 验证码发送状态: {otp_resp.status_code}")
        if otp_resp.status_code != 200:
            print(f"[DEBUG] send-otp 响应体: {otp_resp.text[:500]}")
        human_delay(2.0, 5.0)

        if mail_base == "custom_gmail":
            code = get_gmail_otp(email, proxies)
        elif mail_base == "tempmail_lol":
            code = get_tempmail_lol_code(dev_token, email, proxies)
        elif mail_base == "guerrilla":
            code = get_guerrilla_code(dev_token, email, proxies)
        else:
            code = get_oai_code(dev_token, email, proxies, base=mail_base)
            
        if not code:
            return None
            
        reg_otp = code
        human_delay(1.0, 3.0)

        code_body = f'{{"code":"{code}"}}'
        code_resp = s.post(
            "https://auth.openai.com/api/accounts/email-otp/validate",
            headers={
                "referer": "https://auth.openai.com/email-verification",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=code_body,
            proxies=proxies
        )
        print(f"[*] 验证码校验状态: {code_resp.status_code}")
        human_delay(1.5, 3.5)

        reg_name, reg_birthdate = generate_random_identity()
        print(f"[*] 本次注册身份: {reg_name} / {reg_birthdate}")
        create_account_body = f'{{"name":"{reg_name}","birthdate":"{reg_birthdate}"}}'
        create_account_resp = s.post(
            "https://auth.openai.com/api/accounts/create_account",
            headers={
                "referer": "https://auth.openai.com/about-you",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=create_account_body,
            proxies=proxies
        )
        create_account_status = create_account_resp.status_code
        print(f"[*] 账户创建状态: {create_account_status}")

        if create_account_status != 200:
            print(f"[DEBUG] 注册失败响应: {create_account_resp.text[:200]}")
            return None

        # ------------------------------------------------------------------
        # 启动重登录逻辑，获取最终 Token
        # ★ 根据 Issue #62：复用注册阶段已初始化的 oauth 对象（state/verifier 必须一致）
        # ------------------------------------------------------------------
        # ------------------------------------------------------------------
        # 启动重登录逻辑 (借鉴 back_gao.py 的高稳定性闭环流程)
        # ------------------------------------------------------------------
        print("[*] 注册完成，彻底解耦并启动静默重登录...")
        human_delay(5.0, 10.0)
        
        s = requests.Session()
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        s.headers.update({"user-agent": ua})

        # ★ 借鉴点 1：完全重新生成 OAuth URL (不再复用，避免 Session 串扰)
        login_start_oauth = generate_oauth_url()
        s.get(login_start_oauth.auth_url, timeout=15, proxies=proxies)
        
        did = s.cookies.get("oai-did")
        if not did:
            print("[Error] 登录阶段获取 Device ID 失败")
            return None
        print(f"[DEBUG] Re-Login DID: {did}")

        # ★ 借鉴点 2：逐步分阶段校验
        # 1. 提交登录意向
        sentinel_login = get_real_sentinel_token(did, "authorize_continue", proxies, ua)
        login_init_body = json.dumps({"username": {"value": email, "kind": "email"}, "screen_hint": "login"})
        auth_cont_resp = s.post(
            "https://auth.openai.com/api/accounts/authorize/continue",
            headers={
                "referer": "https://auth.openai.com/log-in",
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel_login,
            },
            data=login_init_body,
            proxies=proxies
        )
        print(f"[*] 登录开始意向状态: {auth_cont_resp.status_code}")
        human_delay(2.0, 4.0)

        # 2. 校验密码并获取 page 状态
        sentinel_pwd = get_real_sentinel_token(did, "authorize_continue", proxies, ua) or sentinel_login
        pwd_body = json.dumps({"password": reg_password})
        pwd_resp = s.post(
            "https://auth.openai.com/api/accounts/password/verify",
            headers={
                "referer": "https://auth.openai.com/log-in/password",
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel_pwd,
            },
            data=pwd_body,
            proxies=proxies
        )
        print(f"[*] 登录密码校验状态: {pwd_resp.status_code}")
        
        if pwd_resp.status_code != 200:
            print(f"[Error] 登录失败: {pwd_resp.text[:200]}")
            return None

        # ★ 借鉴点 3：阶梯式轮询 + 自动 Resend
        # 如果页面指示需要 OTP，则开启 5 轮“尝试-重发”大循环
        try:
            pwd_json = pwd_resp.json()
            page_type = (pwd_json.get("page") or {}).get("type", "")
            need_login_otp = "otp" in page_type or "verify" in str(pwd_json.get("continue_url", ""))
        except:
            need_login_otp = True # 默认兜底开启验证

        login_otp = ""
        if need_login_otp:
            print("[*] 登录触发二次验证，开启“尝试-重发”五阶段轮询...")
            for attempt in range(5):
                if attempt > 0:
                    print(f"\n[*] 验证码重试 ({attempt}/5)，主动触发重发接口...")
                    try:
                        s.post(
                            "https://auth.openai.com/api/accounts/email-otp/resend",
                            headers={
                                "openai-sentinel-token": get_real_sentinel_token(did, "authorize_continue", proxies, ua) or sentinel_pwd,
                                "content-type": "application/json",
                            },
                            json={},
                            proxies=proxies,
                            timeout=15
                        )
                    except: pass
                    time.sleep(3)

                # 每个轮询阶段大约 30 秒
                if mail_base == "custom_gmail":
                    login_otp = get_gmail_otp(email, proxies, ignore_code=reg_otp)
                elif mail_base == "tempmail_lol":
                    login_otp = get_tempmail_lol_code(dev_token, email, proxies, ignore_code=reg_otp)
                else:
                    login_otp = get_oai_code(dev_token, email, proxies, base=mail_base, ignore_code=reg_otp)

                if login_otp:
                    break
            
            if not login_otp:
                print("[Error] 多次重发后仍未收到登录验证码")
                return None
            print(f"[*] 成功获取登录验证码: {login_otp}")

            # 3. 校验登录验证码
            sentinel_val = get_real_sentinel_token(did, "authorize_continue", proxies, ua) or sentinel_pwd
            val_resp = s.post(
                "https://auth.openai.com/api/accounts/email-otp/validate",
                headers={
                    "referer": "https://auth.openai.com/log-in/email-otp",
                    "accept": "application/json",
                    "content-type": "application/json",
                    "openai-sentinel-token": sentinel_val,
                },
                json={"code": login_otp},
                proxies=proxies
            )
            print(f"[*] 登录验证码校验完成: {val_resp.status_code}")
            if val_resp.status_code != 200:
                print(f"[Error] 登录验证失败: {val_resp.text[:200]}")
                return None
        else:
            print("[*] 极速通过：本次登录无需二次邮箱验证")
            
        otp_val_resp = s.post(
            "https://auth.openai.com/api/accounts/email-otp/validate",
            headers={
                "referer": "https://auth.openai.com/log-in/email-otp",
                "accept": "application/json", 
                "content-type": "application/json"
            },
            data=json.dumps({"code": login_otp}),
            proxies=proxies
        )
        print(f"[*] 登录验证码校验状态: {otp_val_resp.status_code}")
        if otp_val_resp.status_code != 200:
            print(f"[Error] 登录验证码校验失败: {otp_val_resp.text[:200]}")
            return None
        human_delay(2.0, 4.0)

        # 解析 auth Cookie 获取 workspace 列表
        auth_cookie = s.cookies.get("oai-client-auth-session")
        if not auth_cookie:
             print("[Error] 缺失 auth Cookie")
             return None
             
        auth_json = _decode_jwt_segment(auth_cookie.split(".")[0])
        workspaces = auth_json.get("workspaces") or []
        if not workspaces:
            print("[Error] 授权 Cookie 中缺失 workspace 列表")
            return None
        workspace_id = str((workspaces[0] or {}).get("id") or "").strip()
        print(f"[*] 选择工作区: {workspace_id}")
        
        select_resp = s.post(
            "https://auth.openai.com/api/accounts/workspace/select",
            headers={"content-type": "application/json", "referer": "https://auth.openai.com/workspace-select"},
            data=f'{{"workspace_id":"{workspace_id}"}}',
            proxies=proxies
        )
        if select_resp.status_code != 200:
            print(f"[Error] workspace 选择失败: {select_resp.status_code}")
            return None

        # 从 workspace/select 响应中获取 continue_url，跟踪重定向链
        continue_url = str((select_resp.json() or {}).get("continue_url") or "").strip()
        if not continue_url:
            print("[Error] 缺失 continue_url")
            return None
        
        print("[*] 追踪 OAuth 重定向链...")
        final_callback_url = follow_openai_redirects(s, continue_url, proxies=proxies)
        if not final_callback_url:
            print("[Error] 重定向追踪失败，未捕获到回调 URL")
            return None
        
        print("[*] 准备兑换最终 Token...")
        ret = submit_callback_url(
            callback_url=final_callback_url, 
            expected_state=login_oauth.state, 
            code_verifier=login_oauth.code_verifier, 
            proxies=proxies
        )
        return ret

    except Exception as e:
        print(f"[Error] 运行时异常: {e}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAI 自动注册脚本")
    parser.add_argument(
        "--proxy", default=None, help="代理地址，如 http://127.0.0.1:7890"
    )
    parser.add_argument("--once", action="store_true", help="只运行一次")
    parser.add_argument("--sleep-min", type=int, default=5, help="循环模式最短等待秒数")
    parser.add_argument(
        "--sleep-max", type=int, default=30, help="循环模式最长等待秒数"
    )
    args = parser.parse_args()

    sleep_min = max(1, args.sleep_min)
    sleep_max = max(sleep_min, args.sleep_max)

    count = 0
    print("[Info] Yasal's Seamless OpenAI Auto-Registrar Started for ZJH")

    while True:
        count += 1
        print(
            f"\n[{datetime.now().strftime('%H:%M:%S')}] >>> 开始第 {count} 次注册流程 <<<"
        )

        try:
            token_json = run(args.proxy)

            if token_json:
                try:
                    t_data = json.loads(token_json)
                    fname_email = t_data.get("email", "unknown").replace("@", "_")
                except Exception:
                    fname_email = "unknown"

                file_name = f"token_{fname_email}_{int(time.time())}.json"

                with open(file_name, "w", encoding="utf-8") as f:
                    f.write(token_json)

                # 在 accounts.txt 最新的账号记录末尾补写 token 文件名
                try:
                    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    if lines:
                        # 找到最后一条没有 token_file 的记录，补写文件名
                        last_idx = len(lines) - 1
                        if "token_file=" not in lines[last_idx]:
                            lines[last_idx] = lines[last_idx].rstrip("\n") + f" | token_file={file_name}\n"
                            with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                                f.writelines(lines)
                except Exception:
                    pass

                print(f"[*] 成功! Token 已保存至: {file_name}")
            else:
                print("[-] 本次注册失败。")

        except Exception as e:
            print(f"[Error] 发生未捕获异常: {e}")

        if args.once:
            break

        wait_time = random.randint(sleep_min, sleep_max)
        print(f"[*] 休息 {wait_time} 秒...")
        time.sleep(wait_time)


if __name__ == "__main__":
    main()
