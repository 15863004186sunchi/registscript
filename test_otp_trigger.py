import json
import time
from curl_cffi import requests

# Re-using logic from openai_login.py mostly
from openai_registerv10 import generate_oauth_url

s = requests.Session(impersonate="chrome")
email = "vyem327f446d@geeksun.ccwu.cc" # using the 2nd account which hit login_password

# 1. Authorize
oauth = generate_oauth_url()
url = oauth.auth_url
s.get(url, timeout=15)
did = s.cookies.get("oai-did")

sen_resp = requests.post(
    "https://sentinel.openai.com/backend-api/sentinel/req",
    headers={"origin": "https://sentinel.openai.com", "content-type": "text/plain;charset=UTF-8"},
    data=f'{{"p":"","id":"{did}","flow":"authorize_continue"}}',
    impersonate="chrome"
)
sentinel1 = f'{{"p": "", "t": "", "c": "{sen_resp.json()["token"]}", "id": "{did}", "flow": "authorize_continue"}}'

auth_resp = s.post(
    "https://auth.openai.com/api/accounts/authorize/continue",
    headers={"referer": oauth.auth_url, "openai-sentinel-token": sentinel1, "content-type": "application/json"},
    data=json.dumps({"username": {"value": email, "kind": "email"}, "screen_hint": "login"}),
)
print("Auth resp:", auth_resp.status_code, auth_resp.text)
try:
    auth_json = auth_resp.json()
except:
    auth_json = {}

cont_url = auth_json.get("continue_url", "")
if cont_url:
    s.get(cont_url)

sen_resp2 = requests.post(
    "https://sentinel.openai.com/backend-api/sentinel/req",
    headers={"origin": "https://sentinel.openai.com", "content-type": "text/plain;charset=UTF-8"},
    data=f'{{"p":"","id":"{did}","flow":"username_password_login"}}',
    impersonate="chrome"
)
sentinel2 = f'{{"p": "", "t": "", "c": "{sen_resp2.json()["token"]}", "id": "{did}", "flow": "username_password_login"}}'

# Try POST to email-otp/send
otp_resp = s.post(
    "https://auth.openai.com/api/accounts/email-otp/send",
    headers={"referer": cont_url, "openai-sentinel-token": sentinel2, "content-type": "application/json"},
    data=json.dumps({})
)
print("OTP send POST:", otp_resp.status_code, otp_resp.text)

# Try GET to email-otp/send
otp_resp2 = s.get(
    "https://auth.openai.com/api/accounts/email-otp/send",
    headers={"referer": cont_url, "openai-sentinel-token": sentinel2}
)
print("OTP send GET:", otp_resp2.status_code, otp_resp2.text)

# Try to POST to authorize/continue again
otp_resp3 = s.post(
    "https://auth.openai.com/api/accounts/authorize/continue",
    headers={"referer": cont_url, "openai-sentinel-token": sentinel2, "content-type": "application/json"},
    data=json.dumps({"action": "default"})
)
print("Continue POST again:", otp_resp3.status_code, otp_resp3.text)
