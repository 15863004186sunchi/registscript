import time
import random
import json
from curl_cffi import requests

def human_delay(min_s=1.0, max_s=3.0):
    time.sleep(random.uniform(min_s, max_s))

class LoginFlowTester:
    def __init__(self, proxy=None):
        self.s = requests.Session(impersonate="chrome")
        if proxy:
            self.s.proxies = {"http": proxy, "https": proxy}
        
    def step_0_get_authorize(self, url):
        print(f"[*] Step 0: GET {url}")
        resp = self.s.get(url, timeout=15)
        print(f"    Status: {resp.status_code}")
        return resp

    def step_1_post_credentials(self, url, payload):
        print(f"[*] Step 1: POST {url}")
        # Use custom headers to mimic browser exactly
        headers = {
            "Content-Type": "application/json",
            "Referer": url,
            "Origin": url.split('/api')[0] if '/api' in url else url
        }
        resp = self.s.post(url, headers=headers, data=json.dumps(payload), timeout=15)
        print(f"    Status: {resp.status_code}")
        return resp

    # Add more steps as needed for specific flows (email_otp, sentinel, etc.)

if __name__ == "__main__":
    # Example usage template
    # tester = LoginFlowTester(proxy="http://127.0.0.1:7890")
    # tester.step_0_get_authorize("https://auth.openai.com/authorize?...")
    # human_delay()
    # tester.step_1_post_credentials("...", {"username": "...", "password": "..."})
    print("This is a template file. Customize it for each specific reverse engineering task.")
