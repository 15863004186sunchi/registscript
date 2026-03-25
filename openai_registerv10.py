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
CUSTOM_EMAIL_DOMAIN = ""          # Cloudflare 托管的域名 (填空则自动使用随机公共短邮箱)
GMAIL_USER          = ""          # 接收转发的 Gmail 地址
GMAIL_APP_PASSWORD  = ""          # Gmail 应用专用密码（去掉空格）


def generate_custom_email() -> str:
    """用自定义域名生成一个随机邮箱地址"""
    prefix = "".join(random.choices(string.ascii_lowercase, k=random.randint(3, 5)))
    local = f"{prefix}{secrets.token_hex(4)}"
    return f"{local}@{CUSTOM_EMAIL_DOMAIN}"

def get_gmail_otp(recipient_email: str, proxies: Any = None, ignore_code: str = "") -> str:
    """
    通过 Gmail IMAP 轮询，找到转发自 OpenAI 的邮件并提取 6 位验证码。
    同时检查 INBOX 和 [Gmail]/Spam 文件夹，避免因垃圾邮件过滤而漏读。
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
                        status, _ = imap.select(folder, readonly=False)
                        if status != "OK":
                            continue

                        # 搜索来自 openai.com 的未读邮件
                        _, msg_ids = imap.search(None, 'UNSEEN FROM "openai.com"')
                        for num in (msg_ids[0].split() or [])[-10:]:
                            if num in seen_ids:
                                continue
                            seen_ids.add(num)

                            _, data = imap.fetch(num, "(RFC822)")
                            if not data or not data[0]:
                                continue

                            msg = emaillib.message_from_bytes(data[0][1])

                            # 检查收件人是否匹配
                            to_header = str(msg.get("To") or "").lower()
                            local_part = recipient_email.split("@")[0].lower()
                            if local_part not in to_header and recipient_email.lower() not in to_header:
                                continue

                            # 提取邮件正文
                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    ct = part.get_content_type()
                                    if ct in ("text/plain", "text/html"):
                                        try:
                                            body += part.get_payload(decode=True).decode("utf-8", "replace")
                                        except Exception:
                                            pass
                            else:
                                try:
                                    body = msg.get_payload(decode=True).decode("utf-8", "replace")
                                except Exception:
                                    body = str(msg.get_payload())

                            m = re.search(regex, body)
                            if m:
                                code = m.group(1)
                                if ignore_code and code == ignore_code:
                                    continue
                                # 标记为已读
                                imap.store(num, "+FLAGS", "\\Seen")
                                print(" 抓到啦! 验证码:", code)
                                return code
                    except Exception:
                        continue
        except Exception as e:
            pass  # 网络抖动时静默重试

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

    for item in items:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "").strip()
        is_active = item.get("isActive", True)
        is_private = item.get("isPrivate", False)
        if domain and is_active and not is_private:
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
    if CUSTOM_EMAIL_DOMAIN and GMAIL_USER and GMAIL_APP_PASSWORD:
        email = generate_custom_email()
        print(f"[*] 使用服务商: 自定义域名 + Gmail IMAP ({CUSTOM_EMAIL_DOMAIN})")
        return email, "gmail_imap_token", "custom_gmail"

    # 将所有免费的临时服务商放进列表后随机打乱遍历
    providers = [
        get_tempmail_lol_email,
        get_guerrilla_email,
        get_mailtm_email
    ]
    random.shuffle(providers)

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


def _post_form(url: str, data: Dict[str, str], timeout: int = 30) -> Dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.status != 200:
                raise RuntimeError(
                    f"token exchange failed: {resp.status}: {raw.decode('utf-8', 'replace')}"
                )
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        raise RuntimeError(
            f"token exchange failed: {exc.code}: {raw.decode('utf-8', 'replace')}"
        ) from exc


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
        )
        print(f"[*] 验证码发送状态: {otp_resp.status_code}")
        if otp_resp.status_code != 200:
            # === 诊断：打印 send-otp 错误详情 ===
            print(f"[DEBUG] send-otp 响应体: {otp_resp.text[:500]}")
            print(f"[DEBUG] 当前邮箱域名: {email.split('@')[-1]}")
        human_delay(2.0, 5.0)  # 模拟用户切换到邮箱/等待验证码

        # 根据邮箱服务商选择对应的验证码轮询函数
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
        human_delay(1.0, 3.0)  # 模拟用户手动输入验证码

        code_body = f'{{"code":"{code}"}}'
        code_resp = s.post(
            "https://auth.openai.com/api/accounts/email-otp/validate",
            headers={
                "referer": "https://auth.openai.com/email-verification",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=code_body,
        )
        print(f"[*] 验证码校验状态: {code_resp.status_code}")
        human_delay(1.5, 3.5)  # 模拟用户填写个人信息页面的停留时间

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
        )
        create_account_status = create_account_resp.status_code
        print(f"[*] 账户创建状态: {create_account_status}")
        print(f"[DEBUG] create_account 响应体: {create_account_resp.text[:500]}")
        print(f"[DEBUG] create_account Set-Cookie: {create_account_resp.headers.get('Set-Cookie', '(无)')[:120]}...")

        if create_account_status != 200:
            print(create_account_resp.text)
            return None

        # ------------------------------------------------------------------
        # 账号创建成功。即刻发起标准重登录流程 (Re-Login) 提取 Token
        # ------------------------------------------------------------------
        print("[*] 注册完成，准备执行重新登录流程获取 Token...")
        human_delay(1.0, 3.0)
        
        # 1. 重新发起 OAuth 授权
        login_oauth = generate_oauth_url()
        s.get(login_oauth.auth_url, timeout=15)
        did = s.cookies.get("oai-did")
        if not did:
            print("[Error] 重新登录时未获取到 oai-did")
            return None
            
        print(f"[DEBUG] Re-Login Device ID: {did}")
        human_delay(1.0, 2.0)

        # 2. 申请登录 Sentinel Token
        sen_req_login = f'{{"p":"","id":"{did}","flow":"authorize_continue"}}'
        sen_resp_login = requests.post(
            "https://sentinel.openai.com/backend-api/sentinel/req",
            headers={
                "origin": "https://sentinel.openai.com",
                "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
                "content-type": "text/plain;charset=UTF-8"
            },
            data=sen_req_login,
            proxies=proxies,
            impersonate="chrome",
            timeout=15,
        )
        sen_token_login = sen_resp_login.json().get("token", "")
        sentinel_login = f'{{"p": "", "t": "", "c": "{sen_token_login}", "id": "{did}", "flow": "authorize_continue"}}'

        # 3. 提交登录入口意图 (screen_hint: login)
        login_body = f'{{"username":{{"value":"{email}","kind":"email"}},"screen_hint":"login"}}'
        auth_cont_resp = s.post(
            "https://auth.openai.com/api/accounts/authorize/continue",
            headers={
                "referer": "https://auth.openai.com/log-in",
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel_login,
            },
            data=login_body,
        )
        print(f"[*] 提交登录意向状态: {auth_cont_resp.status_code}")
        human_delay(1.0, 2.0)

        # 4. 提交登录密码 (正确的 /password/verify 端点)
        pwd_body = json.dumps({"password": reg_password})
        pwd_resp = s.post(
            "https://auth.openai.com/api/accounts/password/verify",
            headers={
                "referer": "https://auth.openai.com/log-in/password",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=pwd_body
        )
        print(f"[*] /password/verify 提交状态: {pwd_resp.status_code}")
        
        if pwd_resp.status_code != 200:
            print(f"[Error] 登录密码验证失败: {pwd_resp.text[:200]}")
            return None
            
        pwd_json = {}
        try: pwd_json = pwd_resp.json()
        except: pass
        
        page_type = str(pwd_json.get("page", {}).get("type", "")).strip()
        print(f"[*] 登录后续流程: {page_type}")

        # 5. 判断是否触发登录侧 Email OTP 检查
        if page_type == "email_otp_verification":
            print("[*] 触发登录二次验证 (Email OTP)，等待系统发送...")
            human_delay(2.0, 5.0)
            
            if mail_base == "custom_gmail":
                login_otp = get_gmail_otp(email, proxies, ignore_code=reg_otp)
            elif mail_base == "tempmail_lol":
                login_otp = get_tempmail_lol_code(dev_token, email, proxies, ignore_code=reg_otp)
            elif mail_base == "guerrilla":
                login_otp = get_guerrilla_code(dev_token, email, proxies, ignore_code=reg_otp)
            else:
                login_otp = get_oai_code(dev_token, email, proxies, base=mail_base, ignore_code=reg_otp)
                
            if not login_otp:
                print("[Error] 登录验证码获取失败")
                return None
                
            # 提交登录验证码
            otp_val_resp = s.post(
                "https://auth.openai.com/api/accounts/email-otp/validate",
                headers={
                    "referer": "https://auth.openai.com/email-verification",
                    "accept": "application/json", 
                    "content-type": "application/json"
                },
                data=json.dumps({"code": login_otp})
            )
            print(f"[*] 登录密码OTP校验状态: {otp_val_resp.status_code}")
            if otp_val_resp.status_code != 200:
                print(f"[Error] 登录验证码校验失败: {otp_val_resp.text[:200]}")
                return None
            human_delay(1.0, 2.0)

        # 6. 从成功会话中提取 Web 会话 JWT 并读取 workspace_id
        auth_cookie = s.cookies.get("oai-client-auth-session")
        if not auth_cookie:
             print("[Error] 重登录流程完成后仍未获取到 auth Cookie")
             return None
             
        auth_json = _decode_jwt_segment(auth_cookie.split(".")[0])
        workspaces = auth_json.get("workspaces") or []

        if not workspaces:
            print("[Error] 最终授权 Cookie 中缺失 workspace，登录状态不完整")
            return None

        workspace_id = str((workspaces[0] or {}).get("id") or "").strip()
        print(f"[*] 选择工作区 ID: {workspace_id}")
        
        select_resp = s.post(
            "https://auth.openai.com/api/accounts/workspace/select",
            headers={"content-type": "application/json"},
            data=f'{{"workspace_id":"{workspace_id}"}}'
        )
        if select_resp.status_code != 200:
            print(f"[Error] 工作区选择失败: {select_resp.status_code}")
            return None

        continue_url = str((select_resp.json() or {}).get("continue_url") or "").strip()
        if not continue_url:
            print("[Error] workspace/select 响应里缺少 continue_url")
            return None

        current_url = continue_url
        for _ in range(6):
            final_resp = s.get(current_url, allow_redirects=False, timeout=15)
            location = final_resp.headers.get("Location") or ""

            if final_resp.status_code not in [301, 302, 303, 307, 308]:
                break
            if not location:
                break

            next_url = urllib.parse.urljoin(current_url, location)
            if "code=" in next_url and "state=" in next_url:
                return submit_callback_url(
                    callback_url=next_url,
                    code_verifier=oauth.code_verifier,
                    redirect_uri=oauth.redirect_uri,
                    expected_state=oauth.state,
                )
            current_url = next_url

        print("[Error] 未能在重定向链中捕获到最终 Callback URL")
        return None

    except Exception as e:
        print(f"[Error] 运行时发生错误: {e}")
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
