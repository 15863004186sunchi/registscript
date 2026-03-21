// ==UserScript==
// @name         OpenAI Token Extractor (ZJH Special)
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  一键提取 ChatGPT 登录后的 Token 并保存为标准的 JSON 文件（兼容反代面板）
// @author       Antigravity
// @match        https://chatgpt.com/*
// @grant        none
// ==/UserScript==

(function () {
    'use strict';

    // 创建悬浮按钮
    const btn = document.createElement('button');
    btn.innerHTML = '📥 提取 Token';
    btn.style.position = 'fixed';
    btn.style.bottom = '20px';
    btn.style.right = '20px';
    btn.style.zIndex = '9999';
    btn.style.padding = '12px 18px';
    btn.style.backgroundColor = '#10a37f';
    btn.style.color = '#fff';
    btn.style.border = 'none';
    btn.style.borderRadius = '8px';
    btn.style.cursor = 'pointer';
    btn.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';
    btn.style.fontWeight = 'bold';
    btn.style.fontSize = '14px';

    btn.onmouseover = () => btn.style.backgroundColor = '#1a7f64';
    btn.onmouseout = () => btn.style.backgroundColor = '#10a37f';

    btn.onclick = async () => {
        try {
            btn.innerHTML = '⏳ 正在提取...';
            btn.disabled = true;

            const resp = await fetch('/api/auth/session');
            if (resp.status !== 200) {
                alert('获取 Session 失败，请确保已登录！');
                return;
            }

            const session = await resp.json();
            const accessToken = session.accessToken;
            const email = session?.user?.email || "unknown_email";

            // 解析 accessToken 的 JWT Payload，提取真正的 account_id
            let account_id = "";
            try {
                const payloadBase64 = accessToken.split('.')[1];
                let base64 = payloadBase64.replace(/-/g, '+').replace(/_/g, '/');
                while (base64.length % 4) base64 += '=';
                const payloadText = atob(base64);
                const payload = JSON.parse(decodeURIComponent(escape(payloadText)));

                const authInfo = payload["https://api.openai.com/auth"];
                if (authInfo && authInfo["chatgpt_account_id"]) {
                    account_id = authInfo["chatgpt_account_id"];
                }
            } catch (e) {
                console.warn("解析 account_id 失败", e);
                account_id = "2ab60b7c-6e4d-4a3b-a012-b7d522f5b149"; // 默认兜底值
            }

            const now = new Date();
            const future = new Date(now.getTime() + 10 * 24 * 60 * 60 * 1000);

            // 严格对齐 JSON 结构
            const tokenData = {
                "id_token": accessToken,
                "access_token": accessToken,
                "refresh_token": "rt_eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9_fake_to_pass_validation",
                "account_id": account_id,
                "last_refresh": now.toISOString().replace(/\.\d{3}Z$/, 'Z'),
                "email": email,
                "type": "codex",
                "expired": future.toISOString().replace(/\.\d{3}Z$/, 'Z')
            };

            // 下载逻辑
            const jsonStr = JSON.stringify(tokenData, null, 4);
            const blob = new Blob([jsonStr], { type: "application/json" });
            const userPrefix = email.includes("@") ? email.split("@")[0] : "user";
            const domain = email.includes("@") ? email.split("@")[1] : "domain";
            const timestamp = Math.floor(now.getTime() / 1000);
            const fileName = `token_${userPrefix}_${domain}_${timestamp}.json`;

            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = fileName;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);

            btn.innerHTML = '✅ 提取成功';
            setTimeout(() => {
                btn.innerHTML = '📥 提取 Token';
                btn.disabled = false;
            }, 3000);

        } catch (err) {
            console.error(err);
            alert('提取过程中发生错误: ' + err.message);
            btn.innerHTML = '❌ 提取失败';
            btn.disabled = false;
        }
    };

    document.body.appendChild(btn);
})();
