import json
import requests
import sys
import argparse
from curl_cffi import requests as curl_requests

def probe_endpoint(url, method="GET", body=None, proxy=None):
    print(f"[*] Probing {method} {url}...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Content-Type": "application/json"
    }
    
    proxies = {"http": proxy, "https": proxy} if proxy else None
    
    try:
        # Use curl_cffi to mimic browser TLS fingerprint
        if method.upper() == "POST":
            resp = curl_requests.post(url, headers=headers, data=body, proxies=proxies, impersonate="chrome", timeout=15)
        else:
            resp = curl_requests.get(url, headers=headers, proxies=proxies, impersonate="chrome", timeout=15)
            
        print(f"[Result] Status Code: {resp.status_code}")
        if resp.status_code == 404:
            print("FAILED: Endpoint not found (404). It might have changed.")
        elif resp.status_code == 405:
            print("FAILED: Method not allowed (405). Check if GET/POST is correct.")
        elif resp.status_code == 200:
            print("SUCCESS: Endpoint responded 200 OK.")
        else:
            print(f"INFO: Endpoint returned {resp.status_code}")
            
        # Try to parse response type
        content_type = resp.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                print(f"Body: {json.dumps(resp.json(), indent=2)}")
            except:
                print(f"Body: {resp.text[:200]}...")
        else:
            print(f"Body Snippet: {resp.text[:200]}...")
            
    except Exception as e:
        print(f"ERROR during probe: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Probe a Web API endpoint.")
    parser.add_argument("url", help="Target URL")
    parser.add_argument("--method", default="GET", help="HTTP Method (GET/POST)")
    parser.add_argument("--data", help="POST body (JSON string)")
    parser.add_argument("--proxy", help="Proxy URL")
    
    args = parser.parse_args()
    probe_endpoint(args.url, args.method, args.data, args.proxy)
