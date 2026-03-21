import re
from curl_cffi import requests

s = requests.Session(impersonate="chrome")
resp = s.get("https://auth.openai.com/log-in/password")
html = resp.text

# 提取所有的 js 链接
js_files = re.findall(r'src="(/_next/static/[^"]+\.js)"', html)
print(f"找到 {len(js_files)} 个 JS 文件")

endpoints = set()

for js in js_files:
    url = f"https://auth.openai.com{js}"
    try:
        r = s.get(url)
        # 查找所有类似 /api/accounts/ 开头的字符串
        matches = re.findall(r'"/api/accounts/[a-zA-Z0-9_/-]+"', r.text)
        for m in matches:
            endpoints.add(m.strip('"'))
    except Exception as e:
        print(f"Error fetching {url}: {e}")

print("\n".join(sorted(endpoints)))
