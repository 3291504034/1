"""群管模块 — 禁言、解禁、黑名单、违规处理。"""

import asyncio
import re
import time
import sqlite3
import glob
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.base.logger import get_logger, PLUGIN

from .db import get_blacklist, set_blacklist, get_violations, set_violations, add_log
from . import config

log = get_logger(PLUGIN, "管理娱乐群管")

_DATA_DIR = Path(__file__).resolve().parent.parent
# 框架数据目录: <elainabot>/data/log/<appid>/<date>/message.db
_FRAMEWORK_DATA = Path(__file__).resolve().parent.parent.parent.parent / "data"


def _gid(event):
    return str(getattr(event, "group_id", "0"))


def _iso_expire(minutes: int) -> str:
    """生成禁言到期时间的 ISO 字符串"""
    return (
        datetime.now(timezone.utc) + timedelta(minutes=minutes)
    ).isoformat(timespec="seconds")


async def mute(event, target_uid, minutes: int, reason: str = "") -> str:
    """禁言用户（分钟）"""
    gid = _gid(event)
    try:
        sender = event.sender
        payload = [
            {"op": "add", "member_openid": str(target_uid), "mute_expire_at": _iso_expire(minutes)}
        ]
        success, response = await sender.set_group_member_mute(gid, payload)
        log.info(f"禁言API gid={gid} uid={target_uid} min={minutes} -> success={success} resp={response}")
        if not success:
            return f"禁言失败: {response.get('message', '')}"
        add_log(f"禁言 {target_uid} {minutes}分钟 原因:{reason}")
        return f"🔇 已禁言 {minutes} 分钟"
    except Exception as e:
        return f"禁言失败: {e}"


async def unmute(event, target_uid) -> str:
    """解禁"""
    gid = _gid(event)
    try:
        sender = event.sender
        payload = [{"op": "del", "member_openid": str(target_uid)}]
        success, response = await sender.set_group_member_mute(gid, payload)
        log.info(f"解禁API gid={gid} uid={target_uid} -> success={success} resp={response}")
        if not success:
            return f"解禁失败: {response.get('message', '')}"
        add_log(f"解禁 {target_uid}")
        return "🔊 已解禁"
    except Exception as e:
        return f"解禁失败: {e}"


async def blacklist_add(event, target_uid, reason: str = "", expire_days: int = 0) -> str:
    """拉黑用户（QQ官方无踢出接口，改用永久禁言 + 黑名单）"""
    gid = _gid(event)
    # 变通: 永久禁言(≈踢出效果) + 记黑名单
    await mute(event, target_uid, 43200, f"拉黑({reason or '无原因'})")

    bl = get_blacklist(gid)
    bl[target_uid] = {
        "reason": reason,
        "time": time.strftime("%Y-%m-%d %H:%M"),
        "expire": time.time() + expire_days * 86400 if expire_days > 0 else 0,
    }
    set_blacklist(gid, bl)
    add_log(f"拉黑 {target_uid} 原因:{reason}")
    expire_str = f" {expire_days}天" if expire_days > 0 else " 永久"
    return f"🚫 已拉黑{expire_str} 原因: {reason}"


async def blacklist_remove(event, target_uid) -> str:
    """解除拉黑"""
    gid = _gid(event)
    bl = get_blacklist(gid)
    if str(target_uid) in bl:
        del bl[str(target_uid)]
        set_blacklist(gid, bl)
        add_log(f"解除拉黑 {target_uid}")
        return "✅ 已解除拉黑"
    return "该用户不在黑名单中"


def blacklist_list(event) -> str:
    """查看黑名单"""
    gid = _gid(event)
    bl = get_blacklist(gid)
    if not bl:
        return "黑名单为空"
    now = time.time()
    lines = ["📋 黑名单:"]
    for uid, info in list(bl.items())[:20]:
        expire = info.get("expire", 0)
        if expire and expire < now:
            continue
        reason = info.get("reason", "")
        expire_str = f" {int((expire - now) / 86400)}天后" if expire else " 永久"
        lines.append(f"  {uid} | {reason} | {expire_str}")
    return "\n".join(lines)


def check_blacklist(gid, uid) -> bool:
    """检查是否在黑名单中"""
    bl = get_blacklist(gid)
    info = bl.get(str(uid))
    if not info:
        return False
    expire = info.get("expire", 0)
    if expire and expire < time.time():
        return False
    return True


def add_violation(gid, uid) -> tuple:
    """记录违规，返回 (级别, 惩罚)"""
    from . import config as c
    v = get_violations(gid)
    u = v.get(uid, {"count": 0, "reset": 0})

    now = time.time()
    if u["reset"] < now:
        u = {"count": 0, "reset": now + c.VIOLATION_RESET * 3600}

    u["count"] += 1
    v[uid] = u
    set_violations(gid, v)

    count = u["count"]
    if count == 1:
        return "warn", 0
    elif count == 2:
        return "mute", c.STEP1_MUTE
    elif count == 3:
        return "mute", c.STEP2_MUTE
    else:
        return "kick", 0


async def recall(event, message_id=None) -> str:
    """撤回消息 — 三重识别(引用ref_msg_idx/REFIDX/内容指纹) + 失败重试3次 + retcode 校验"""
    try:
        sender = event.sender
        mid = message_id or ""

        # 引用撤回: 用户@机器人撤回时, 提取被引用消息
        if not mid:
            mid = _ref_msg_id_from_raw(event)

        # 显式传入的若是 REFIDX, 尝试映射为完整 id
        if mid and not str(mid).startswith("ROBOT1.0"):
            full = _refid_to_msgid(str(mid))
            if full:
                mid = full

        # 兜底: 当前事件消息 (违禁词拦截时即违规消息本身)
        if not mid:
            mid = getattr(event, "message_id", None)

        log.info(f"撤回API 尝试撤回 mid={mid}")
        if not mid:
            return "❌ 撤回失败(无消息ID)"

        # 撤回执行: 失败自动重试3次 (网络抖动/限频/瞬时错误)
        ok, data = False, {}
        last_err = ""
        endpoint = getattr(event, "recall_endpoint", "")
        for attempt in range(1, 4):
            try:
                if sender and endpoint:
                    ok, data = await sender.delete(endpoint.format(message_id=mid))
                else:
                    ok = bool(await sender.recall(event, mid))
                log.info(f"撤回API 响应[%d]: ok=%r data=%s", attempt, ok, str(data)[:120] if data else "")
                if ok:
                    break
                last_err = (data.get("message") or data.get("msg") or "") if isinstance(data, dict) else ""
                await asyncio.sleep(0.6)
            except Exception as e:
                last_err = str(e)
                log.warning("撤回API 异常[%d]: %s", attempt, e)
                await asyncio.sleep(0.6)

        # 业务校验: QQ 即使 HTTP 200 也可能 retcode != 0
        business_ok = bool(ok)
        if isinstance(data, dict):
            rc = data.get("retcode")
            if rc is not None and rc != 0:
                business_ok = False
                last_err = data.get("msg") or data.get("message") or last_err

        if business_ok:
            add_log(f"撤回 {mid[:32]}")
            return "✅ 已撤回"
        msg = last_err or "无权限或消息不存在"
        return f"⚠️ 撤回失败:{msg}"
    except Exception as e:
        log.info(f"撤回API 异常: {e}")
        return f"⚠️ 撤回失败: {e}"


def _scene_ref_id(event) -> str:
    """从事件 message_scene.ext 提取被引用消息的 REFIDX(ref_msg_idx)"""
    for item in (getattr(event, "message_scene", {}) or {}).get("ext", []) or []:
        m = re.search(r"(?:^|[?&])ref_msg_idx=([^&\s]+)", str(item))
        if m:
            return m.group(1)
    return ""


def _ref_msg_id_from_raw(event) -> str:
    """从被引用消息的 ref_msg_idx 反查 log 表, 拿到被引用消息的真实 message_id"""
    ref_idx = _scene_ref_id(event) or str(getattr(event, "message_reference_id", "") or "").strip()
    if not ref_idx:
        return ""
    # 提取被引用消息的多个指纹: 文本 / faceId / fileid(QQ 把被引用消息元素塞在 msg_elements)
    fingerprints: list = []
    for el in getattr(event, "msg_elements", None) or []:
        if not isinstance(el, dict):
            continue
        c = (el.get("content") or "").strip()
        for fid in re.findall(r'faceId\s*=\s*"?\s*(\d+)', c):
            fingerprints.append(f"[face id={fid}]")
            fingerprints.append(f"face id={fid}")
        if c:
            fingerprints.append(re.sub(r"\s+", "", c)[:24])
        for att in (el.get("attachments") or []):
            if not isinstance(att, dict):
                continue
            u = att.get("url") or ""
            fm = re.search(r"fileid=([^&]+)", u)
            if fm:
                fingerprints.append(fm.group(1)[:48])
            fn = (att.get("filename") or "")[:40]
            if fn:
                fingerprints.append(fn)
    ts = str(getattr(event, "timestamp", "") or "").strip()
    mid = str(getattr(event, "message_id", "") or "")
    return _message_id_by_refidx(ref_idx, before_ts=ts, exclude_mid=mid, fingerprints=fingerprints)


def _message_id_by_refidx(ref_idx, before_ts="", exclude_mid="", fingerprints=None) -> str:
    """按 REFIDX 反查消息 id; 查不到且有一致指纹时回退内容匹配"""
    mid = _refid_to_msgid(ref_idx)
    if mid:
        return mid
    # 指纹回退: 内容匹配 (需要群id — 从消息记录交叉)
    if fingerprints:
        for fp in fingerprints:
            if not fp or len(fp) < 4:
                continue
            m = _find_message_by_fingerprint(fp, before_ts=before_ts, exclude_mid=exclude_mid)
            if m:
                return m
    return ""


def _find_message_by_fingerprint(fp, before_ts="", exclude_mid="", limit=5) -> str:
    """按内容指纹(规范化子串)在日志中匹配最近一条消息的 message_id（不限发送方）"""
    if not fp:
        return ""
    needle = re.sub(r"\s+", "", fp)
    needle = needle[:24].replace("%", "\\%").replace("_", "\\_")
    if len(needle) < 4:
        return ""
    ts_norm = str(before_ts or "").replace("T", " ")[:19]
    for db in sorted(glob.glob(str(_FRAMEWORK_DATA / "log" / "*" / "*" / "message.db")), reverse=True):
        try:
            con = sqlite3.connect(db)
            rows = con.execute(
                "SELECT message_id, content FROM log "
                "WHERE substr(replace(timestamp,'T',' '),1,19)<=? AND replace(content,' ','') LIKE ? "
                "ORDER BY id DESC LIMIT ?",
                (ts_norm, f"%{needle}%", limit * 3),
            ).fetchall()
            con.close()
            for mid, c in rows:
                if not mid:
                    continue
                if exclude_mid and mid == exclude_mid:
                    continue
                if re.sub(r"\s+", "", c or "") == needle:
                    return str(mid)
            if rows:
                return str(rows[0][0])
        except Exception:
            continue
    return ""


def _refid_to_msgid(ref_id) -> str:
    """REFIDX → 完整消息id: 消息记录里 reference_id 与 message_id 同条记录"""
    try:
        import sqlite3, glob
        ref_id = str(ref_id)
        for db in sorted(glob.glob(str(_FRAMEWORK_DATA / "log" / "*" / "*" / "message.db")), reverse=True):
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT message_id FROM log WHERE reference_id=? \
                     ORDER BY id DESC LIMIT 1",
                    (ref_id,),
                ).fetchone()
                con.close()
                if row and row[0]:
                    return str(row[0])
            except Exception:
                con.close()
    except Exception:
        pass
    return ""