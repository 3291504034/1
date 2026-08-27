"""豆包 AI 聊天 — 网页版扫码登录 + Playwright 自动化。

登录流程:
1. get_qrcode(): 打开豆包登录页, 捕获二维码返回前端, 同时监听页面自身的
   check_qrconnect 轮询, 把最新登录状态存到 _qr_status
2. check_login(): 返回 _qr_status; status 离开 "new" 且页面出现登录态时
   保存全部 cookie
3. chat(): 用保存的 cookie 打开豆包对话页, 输入消息, 提取回复
"""

import asyncio
import base64
import json
import time

from playwright.async_api import async_playwright

from .db import get_doubao_cookie, set_doubao_cookie

_browser = None
_login_ctx = None      # 扫码登录专用上下文（保持到登录成功）
_chat_ctx = None       # 聊天专用上下文
_chat_page = None
_lock = asyncio.Lock()
_qr_status = "new"     # 最新 check_qrconnect 状态
_QR_URL = "https://www.doubao.com/chat/"


async def _ensure_browser():
    global _browser
    if _browser is None:
        p = await async_playwright().start()
        _browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
    return _browser


# ==================== 登录 ====================

async def get_qrcode() -> dict:
    """打开豆包登录页, 获取二维码, 返回 {token, qr(base64), expire}

    登录成功的真实信号: 页面请求响应头中出现 set-cookie: sessionid=xxx。
    监听该信号, 由 check_login() 轮询确认后保存 cookie。
    """
    global _login_ctx, _qr_status, _login_success
    browser = await _ensure_browser()
    if _login_ctx is not None:
        try:
            await _login_ctx.close()
        except Exception:
            pass
    _login_ctx = await browser.new_context(viewport={"width": 400, "height": 600})
    page = await _login_ctx.new_page()
    _qr_status = "new"
    _login_success = False

    qr_data = None

    async def on_response(resp):
        nonlocal qr_data
        url = resp.url
        if "get_qrcode" in url:
            try:
                qr_data = json.loads(await resp.text())
            except Exception:
                pass
        elif "check_qrconnect" in url:
            # 捕获页面自身轮询的扫码状态
            try:
                d = json.loads(await resp.text())
                st = (d.get("data") or {}).get("status", "")
                if st:
                    global _qr_status
                    _qr_status = st
            except Exception:
                pass
        # 登录成功核心信号: set-cookie 出现 sessionid
        if "sessionid" in url or "sso" in url or "passport" in url:
            try:
                headers = await resp.all_headers()
                sc = headers.get("set-cookie", "")
                if sc and ("sessionid=" in sc or "sid_tt=" in sc):
                    global _login_success
                    _login_success = True
            except Exception:
                pass

    page.on("response", on_response)

    await page.goto(_QR_URL, timeout=30000, wait_until="domcontentloaded")
    await page.wait_for_timeout(4000)

    btn = await page.query_selector("text=登录")
    if btn:
        await btn.click()
        await page.wait_for_timeout(6000)

    data = (qr_data or {}).get("data", {})
    if data.get("qrcode"):
        return {
            "token": data.get("token", ""),
            "qr": data.get("qrcode", ""),
            "expire": data.get("expire_time", 0),
        }

    # 兜底: 截屏整页
    img_bytes = await page.screenshot()
    return {"token": "", "qr": base64.b64encode(img_bytes).decode(), "expire": 0}


async def check_login(token: str = "") -> dict:
    """返回最新登录状态: {'status': str, 'logged_in': bool}"""
    global _login_ctx, _qr_status, _login_success
    if _login_ctx is None:
        return {"status": "", "logged_in": bool(get_doubao_cookie())}

    if _login_success:
        # 确认登录: 重读最终 cookie（登录成功后 sessionid 已更新）
        try:
            cookies = await _login_ctx.cookies()
            names = [ck["name"] for ck in cookies]
            if "sessionid" in names or "sid_tt" in names:
                set_doubao_cookie(cookies)
        except Exception:
            pass
        try:
            await _login_ctx.close()
        except Exception:
            pass
        _login_ctx = None
        _qr_status = ""
        return {"status": "success", "logged_in": True}

    # 等待页面自身轮询更新状态
    for _ in range(3):
        await asyncio.sleep(1)
        if _qr_status not in ("new", ""):
            break
    return {"status": _qr_status, "logged_in": False}


async def _detect_login_success() -> bool:
    """(保留) 检测登录是否成功, 成功则保存 cookie 并返回 True"""
    global _login_ctx
    if _login_ctx is None:
        return False
    page = _login_ctx.pages[0] if _login_ctx.pages else None
    if page is None:
        return False
    try:
        cookies = await _login_ctx.cookies()
        names = [ck["name"] for ck in cookies]
        session_hit = any(n in ("sessionid", "sid_tt", "uid_tt", "sessionid_ss") for n in names)
        if session_hit and _qr_status not in ("new", "scan", "confirming"):
            set_doubao_cookie(cookies)
            try:
                await _login_ctx.close()
            except Exception:
                pass
            _login_ctx = None
            return True
    except Exception:
        pass
    return False


# ==================== 聊天 ====================

async def _ensure_chat_ctx():
    global _chat_ctx
    cookies = get_doubao_cookie()
    if not cookies:
        return None
    if _chat_ctx is None or _chat_ctx.is_closed():
        browser = await _ensure_browser()
        _chat_ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        await _chat_ctx.add_cookies(cookies)
    return _chat_ctx


async def chat(message: str) -> str:
    global _chat_page
    cookies = get_doubao_cookie()
    if not cookies:
        return "豆包未登录，请在Web后台扫码登录"
    has_session = any(c.get("name") in ("sessionid", "sid_tt", "uid_tt") for c in cookies)
    if not has_session:
        return "豆包登录已失效，请在Web后台重新扫码"

    async with _lock:
        try:
            ctx = await _ensure_chat_ctx()
            if ctx is None:
                return "豆包未登录"
            if _chat_page is None or _chat_page.is_closed():
                _chat_page = await ctx.new_page()
                await _chat_page.goto(_QR_URL, timeout=20000, wait_until="domcontentloaded")
                await _chat_page.wait_for_timeout(5000)
            else:
                try:
                    await _chat_page.reload(wait_until="domcontentloaded", timeout=15000)
                    await _chat_page.wait_for_timeout(4000)
                except Exception:
                    pass

            # 关键: 以输入框是否存在判定登录态, 而非页面上的"登录"文字
            # 豆包输入框是 contenteditable 元素，textareas 可能是隐藏输入
            input_box = await _chat_page.query_selector('[contenteditable]')
            if not input_box:
                await _chat_page.wait_for_timeout(5000)
                input_box = await _chat_page.query_selector('[contenteditable]')
            if not input_box:
                input_box = await _chat_page.query_selector('textarea')
            if not input_box:
                return "豆包页面加载失败，请确认登录状态"

            await input_box.click()
            await _chat_page.keyboard.type(message, delay=10)
            await _chat_page.wait_for_timeout(800)
            # 优先点击发送按钮（豆包新版 UI），失败则回车发送
            sent = False
            try:
                send_btn = await _chat_page.query_selector(".send-btn-wrapper")
                if send_btn:
                    await send_btn.click()
                    sent = True
            except Exception:
                pass
            if not sent:
                await _chat_page.keyboard.press("Enter")

            # 发送后检查是否被登出（cookie 失效）
            await _chat_page.wait_for_timeout(4000)
            try:
                if "from_logout" in _chat_page.url or "login" in _chat_page.url:
                    return "豆包登录已失效，请在Web后台重新扫码"
            except Exception:
                pass

            # 等待回复生成（页面可能导航导致 context destroyed，需容错）
            for _ in range(20):
                await _chat_page.wait_for_timeout(2000)
                try:
                    stop_btn = await _chat_page.query_selector("text=停止生成")
                    if stop_btn is None:
                        break
                except Exception:
                    await _chat_page.wait_for_timeout(3000)

            text = await _get_last_reply(_chat_page)
            return text[:800] if text else "豆包回复超时"
        except Exception as e:
            return f"豆包聊天失败: {e}"


async def _get_last_reply(page) -> str:
    """提取 AI 回复：发送后页面正文里最后的一段有效文本"""
    try:
        body = await page.inner_text("body")
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        noise = {"登录", "下载豆包电脑版", "关于豆包", "API 服务", "更多", "新对话",
                 "新工作任务", "定时任务", "技能 · 连接器 · 伙伴", "云盘",
                 "有什么我能帮你的吗？", "为你推荐", "对话", "工作",
                 "PPT 生成", "图像生成", "帮我写作", "视频生成", "翻译",
                 "深入研究", "录音转写", "豆包", "最近", "主对话", "项目",
                 "发消息", "停止生成", "回复", "资讯:".split(":")[0] + "：",
                 "资讯：", "为你推荐", "生成中", "已复制"},
        cands = [l for l in lines if l not in noise and len(l) > 2 and not l.startswith("|")]
        # 从后往前找AI回复: 最后一条不是UI的文本
        return "\n".join(cands[-5:]) if cands else ""
    except Exception:
        return ""


async def close():
    global _chat_ctx, _chat_page, _login_ctx, _browser
    for ctx in (_chat_ctx, _login_ctx):
        if ctx is not None:
            try:
                await ctx.close()
            except Exception:
                pass
    _chat_ctx = _login_ctx = None
    _chat_page = None
    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            pass
    _browser = None