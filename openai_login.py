import os
import re
import sys
import time
import json
import argparse
from typing import Any

from curl_cffi import requests

# 导入 openai_registerv10 中的核心组件，复用原有基础设施
from openai_registerv10 import (
    human_delay,
    generate_oauth_url,
    _decode_jwt_segment,
    get_gmail_otp,
    ACCOUNTS_FILE
)

def get_account(email_pattern: str = "") -> tuple:
    """从 accounts.txt 获取最后注册的一个账号，或者匹配 email_pattern 的账号"""
    if not os.path.exists(ACCOUNTS_FILE):
        print(f"[Error] 找不到账号文件: {ACCOUNTS_FILE}")
        return "", ""
    
    selected_email, selected_pwd = "", ""
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        
        # 尝试匹配 email=... | password=...
        m_email = re.search(r"email=([^\|\s]+)", line)
        m_pwd = re.search(r"password=([^\|\s]+)", line)
        if m_email and m_pwd:
            email, pwd = m_email.group(1), m_pwd.group(1)
            # 如果指定了片段匹配，则筛选
            if email_pattern and email_pattern.lower() not in email.lower():
                continue
            
            selected_email, selected_pwd = email, pwd
            break
            
    return selected_email, selected_pwd


def login_openai(email: str, password: str, proxies: Any = None):
    print(f"\n[>>> 开始登录流程 <<<]")
    print(f"[*] 登录邮箱: {email}")
    
    s = requests.Session(proxies=proxies, impersonate="chrome")
    
    # 获取设备指纹
    oauth = generate_oauth_url()
    url = oauth.auth_url
    try:
        s.get(url, timeout=15)
        did = s.cookies.get("oai-did")
        print(f"[*] Device ID: {did}")

        # 1. 提交标识符 (login 意图)
        login_body = f'{{"username":{{"value":"{email}","kind":"email"}},"screen_hint":"login"}}'
        sen_req_body = f'{{"p":"","id":"{did}","flow":"authorize_continue"}}'
        
        sen_resp = requests.post(
            "https://sentinel.openai.com/backend-api/sentinel/req",
            headers={
                "origin": "https://sentinel.openai.com",
                "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
                "content-type": "text/plain;charset=UTF-8"
            },
            data=sen_req_body,
            proxies=proxies,
            impersonate="chrome",
            timeout=15,
        )
        if sen_resp.status_code != 200:
            print("[Error] 第一步 Sentinel 校验失败")
            return
        
        sen_token = sen_resp.json()["token"]
        sentinel1 = f'{{"p": "", "t": "", "c": "{sen_token}", "id": "{did}", "flow": "authorize_continue"}}'

        # 授权继续
        human_delay(1.0, 2.0)
        auth_resp = s.post(
            "https://auth.openai.com/api/accounts/authorize/continue",
            headers={
                "referer": oauth.auth_url,
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel1,
            },
            data=login_body,
        )
        print(f"[*] 提交登录意向状态: {auth_resp.status_code}")
        if auth_resp.status_code != 200:
            print("[Error] 提交登录意向失败，退出流程")
            return

        try:
            auth_json = auth_resp.json()
        except:
            auth_json = {}
            
        continue_url_page = str(auth_json.get("continue_url") or "").strip()
        if continue_url_page:
            print(f"[*] 追随 continue_url: {continue_url_page}")
            s.get(continue_url_page, timeout=15)
            human_delay(1.0, 2.0)
            
        # 2. 密码校验 (username_password_login)
        sen_req_body2 = f'{{"p":"","id":"{did}","flow":"username_password_login"}}'
        sen_resp2 = requests.post(
            "https://sentinel.openai.com/backend-api/sentinel/req",
            headers={
                "origin": "https://sentinel.openai.com",
                "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
                "content-type": "text/plain;charset=UTF-8"
            },
            data=sen_req_body2,
            proxies=proxies,
            impersonate="chrome",
            timeout=15,
        )
        sen_token2 = sen_resp2.json()["token"]
        sentinel2 = f'{{"p": "", "t": "", "c": "{sen_token2}", "id": "{did}", "flow": "username_password_login"}}'

        # 密码提交端点可能与注册不同，通常是 /api/accounts/user/login 或 /password
        pwd_body = f'{{"password":"{password}","username":"{email}"}}'
        pwd_resp = s.post(
            "https://auth.openai.com/api/accounts/user/login",
            headers={
                "referer": continue_url_page or "https://auth.openai.com/login/password",
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel2,
            },
            data=pwd_body,
        )
        print(f"[*] 密码提交状态: {pwd_resp.status_code}")
        if pwd_resp.status_code not in (200, 201):
            print("[Error] 密码验证失败，退出流程")
            print(f"[DEBUG] 错误响应: {pwd_resp.text[:300]}")
            return

        try:
            pwd_json = pwd_resp.json()
        except:
            pwd_json = {}
            
        # 3. 判断是否需要 OTP 等二次验证（风控）
        if "email-otp" in pwd_resp.text:
            print("[Warn] 触发登录二次邮箱验证 (MFA OTP)！")
            human_delay(1.5, 3.0)
            
            # 由于可能已经是发送过OTP的状态，如果不确定，最好这里显式调一下发送接口
            # 但很多时候登录流程的 MFA OTP 是直接由上一步自动下发的
            
            code = get_gmail_otp(email, proxies)
            if not code:
                return
                
            code_body = f'{{"code":"{code}","trust_device":true}}'
            code_resp = s.post(
                "https://auth.openai.com/api/accounts/email-otp/validate",
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                data=code_body,
            )
            print(f"[*] OTP 验证状态: {code_resp.status_code}")
        
        human_delay(1.0, 3.0)
        
        # 4. 获取登录凭证
        auth_cookie = s.cookies.get("oai-client-auth-session")
        if not auth_cookie:
            print("[Error] 未获取到 oai-client-auth-session Cookie")
            print("[DEBUG] 最后的响应: ", pwd_resp.text[:300])
            return
            
        auth_json = _decode_jwt_segment(auth_cookie.split(".")[0])
        workspaces = auth_json.get("workspaces") or []
        if not workspaces:
            print("[Warn] 授权 Cookie 里没有 workspace 信息")
            workspace_id = "ws-not-found"
        else:
            workspace_id = str((workspaces[0] or {}).get("id") or "").strip()

        # 5. 模拟选择工作区
        select_body = f'{{"workspace_id":"{workspace_id}"}}'
        select_resp = s.post(
            "https://auth.openai.com/api/workspaces/select",
            headers={
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=select_body,
        )
        print(f"[*] 工作区选择状态: {select_resp.status_code}")
        if select_resp.status_code != 200:
            print(f"[DEBUG] 工作区选择响应(可忽略): {select_resp.text[:200]}")
        
        # 获取最终的 Token 及各种授权 Cookie
        final_auth = s.cookies.get("oai-client-auth-session")
        if final_auth:
            token_json = _decode_jwt_segment(final_auth.split(".")[0])
            
            access_token = token_json.get("accessToken", "")
            refresh_token = token_json.get("refreshToken", "")
            ws_id = token_json.get("workspaceId", "")
            
            if not access_token:
                print("[Error] Token json 内无 accessToken！无法视为成功登录。")
                return
            
            cookies_dict = s.cookies.get_dict()
            
            out_data = {
                "update_time": time.time(),
                "email": email,
                "workspaceId": ws_id,
                "accessToken": access_token,
                "refreshToken": refresh_token,
                "oai-did": did,
                "cookies": cookies_dict,
                "status": "Login Successful"
            }
            
            fname = f"token_refresh_{email.replace('@','_')}.json"
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(out_data, f, indent=2, ensure_ascii=False)
            
            print(f"\n[✔] 登录成功！新的 Token 凭据已保存至: {fname}")
        else:
            print("[Error] 最终获取 Token 失败")

    except Exception as e:
        print(f"[Error] 登录流程断开: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenAI 自动登录/刷新Token 脚本")
    parser.add_argument("--proxy", type=str, help="代理地址，例如 http://127.0.0.1:7890", default=None)
    parser.add_argument("--email", type=str, help="指定要登录的邮箱（否则读取 accounts.txt 最后一条）", default="")
    parser.add_argument("--password", type=str, help="独立指定密码（如未提供则从 accounts.txt 获取）", default="")
    args = parser.parse_args()

    proxies = None
    if args.proxy:
        proxies = {"http": args.proxy, "https": args.proxy}

    email, password = args.email, args.password

    # 如果没有指定密码，试图从 accounts 读取
    if not email or not password:
        f_email, f_pwd = get_account(email)
        if not f_email:
            print("[Error] 未找到可用账号，请手动指定 --email 和 --password")
            sys.exit(1)
        # 用账号库里的补充
        email = email or f_email
        password = password or f_pwd

    login_openai(email, password, proxies)
