"""共享回复工具 — markdown 头像渲染 / 卡片回复 / 限次守卫。

参考娱乐助手同款写法: QQ markdown 支持 ![头像 #30px #30px](url) 渲染圆形头像,
配合 <@openid> 实现「头像 + @」前缀, 引用块 > 渲染浅色卡片。
"""

import re
import time
import contextlib
from datetime import datetime, timedelta

from .db import get_users, set_user, get_user
from . import config


def uid_of(event):
    return str(getattr(event, "user_id", "") or "")


def avatar_url(event, uid=None):
    """构造 openid 头像 URL (QQ 官方 qlogo 接口, 无需权限)"""
    uid = uid or uid_of(event)
    appid = str(getattr(event, "appid", "") or "") or "100000000"
    return f"https://q.qlogo.cn/qqapp/{appid}/{uid}/640"


def prefix_at(event):
    """「头像 + @」markdown 前缀 (群管同款写法)"""
    uid = uid_of(event)
    if not uid:
        return ""
    return f"![头像 #30px #30px]({avatar_url(event, uid)}) <@{uid}>\n\n"


def markdown_block(title, lines):
    """统一回复模板: emoji 标题 + 引用块内容 (QQ markdown 浅色卡片观感)"""
    return title + "\n" + "\n".join(f"> {r}" for r in lines)


async def reply_md(event, text, at=True):
    """发送 markdown 回复; at=True 前置「头像+@」一行"""
    if at:
        uid = uid_of(event)
        if uid and not text.startswith(("![头像", "<@")):
            text = f"{prefix_at(event)}{text}"
    try:
        await event.reply(text)
    except Exception:
        with contextlib.suppress(Exception):
            await event.reply(text)


async def reply_text_md(event, text, at=True):
    """纯文本回复 → md 化: 保持原文可读, 首行加粗。

    at=True 时前置「头像+@」一行 (命令类回复默认开启, 与娱乐助手观感一致)。
    """
    if at:
        uid = uid_of(event)
        if uid and not text.startswith(("![头像", "<@")):
            text = f"{prefix_at(event)}{text}"
    # md 化: 首行加粗 (若首行已含 ** 或已是 md 结构则原样)
    lines = str(text).split("\n")
    first = lines[0].strip() if lines else ""
    if first and "**" not in first and not first.startswith((">", "![", "<@", "#")):
        lines[0] = f"**{first}**"
    md_text = "\n".join(lines)
    try:
        await event.reply(md_text)
    except Exception:
        with contextlib.suppress(Exception):
            await event.reply(md_text)


async def reply_card(event, title, items=None, desc="", at=True):
    """卡片感回复: 头像+@ 一行 + 标题 + 引用块内容"""
    uid = uid_of(event)
    head = ""
    if at and uid:
        head = prefix_at(event)
    await reply_md(event, head + markdown_block(title, items or []), at=False)


def nick_of(uid: str) -> str:
    """从插件 user 库取昵称 (简短)"""
    try:
        u = get_user(uid)
        n = u.get("nickname", "") if isinstance(u, dict) else ""
        return str(n)[:10] if n else "?"
    except Exception:
        return "?"


# ========== 限次守卫 ==========

_DAILY_KEY = "daily_limits"
_COOLDOWN_KEY = "cooldowns"
_DEFAULT_DAILY = 5
_DEFAULT_COOLDOWN = 30


def _ensure_meta():
    """确保用户累积记录表存在 (全局, 键内带 gid 隔离)"""
    return get_user("_meta") or {}


def check_and_record_limit(gid, uid, key, daily=None, cooldown=None):
    """限次守卫: 返回 (ok, reason, extra, warned)
    reason: '' 放行 | 'daily' 每日次数用完 | 'cooldown' 冷却中
    """
    daily = daily or _DEFAULT_DAILY
    cooldown = cooldown if cooldown is not None else _DEFAULT_COOLDOWN
    meta = _ensure_meta()
    today = time.strftime("%Y%m%d")
    dk = f"d:{gid}:{uid}:{key}:{today}"
    ck = f"c:{gid}:{uid}:{key}"

    # 每日次数
    count = int(meta.get(dk, 0))
    if count >= daily:
        return False, "daily", daily, False

    # 冷却
    now = time.time()
    last = float(meta.get(ck, 0) or 0)
    if last and now - last < cooldown:
        remain = int(cooldown - (now - last)) + 1
        warned = meta.get(f"w:{gid}:{uid}:{key}", 0)
        # 冷却期第二次触发才标记惩罚
        if warned:
            return False, "cooldown", remain, True
        return False, "cooldown", remain, False

    # 记录
    meta[dk] = count + 1
    meta[ck] = str(now)
    meta.pop(f"w:{gid}:{uid}:{key}", None)
    set_user("_meta", meta)
    return True, "", 0, False


def warn_penalty(gid, uid, key):
    """标记冷却期内第二次违规 → 触发惩罚"""
    meta = _ensure_meta()
    meta[f"w:{gid}:{uid}:{key}"] = 1
    set_user("_meta", meta)


async def limit_mute(event, uid, minutes: int = 2):
    """惩罚性禁言 (频繁触发限次指令时), 失败静默"""
    gid = str(getattr(event, "group_id", "") or "")
    if not gid:
        return
    expire = (datetime.now().astimezone() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    try:
        await event.sender.set_group_member_mute(
            gid,
            [{"op": "add", "member_openid": uid, "mute_expire_at": expire}],
        )
    except Exception:
        pass