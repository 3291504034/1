"""红包系统。"""

import random
import time
import uuid

from .db import get_redpacks, set_redpacks, set_user
from .points import ensure_user, _uid, add_points, get_points, _points_key
from . import config


def _gid(event):
    return str(getattr(event, "group_id", "0"))


def create_redpack(event, total: int, count: int, code: str = "") -> str:
    """创建红包，返回红包ID"""
    gid = _gid(event)
    uid = _uid(event)
    u = ensure_user(event)

    if total < config.get_param("redpack_min"):
        return ""
    if count > config.get_param("redpack_max_count"):
        count = config.get_param("redpack_max_count")
    if get_points(uid) < total:
        return ""

    p_key = _points_key()
    u[p_key] = max(0, u.get(p_key, 0) - total)
    set_user(uid, u)

    rp_id = uuid.uuid4().hex[:8]
    amounts = _split(total, count)

    rp = get_redpacks(gid)
    rp[rp_id] = {
        "sender": uid,
        "total": total,
        "count": count,
        "code": code,
        "amounts": amounts,
        "claimed": {},
        "created": time.time(),
    }
    set_redpacks(gid, rp)
    return rp_id


def _split(total: int, count: int) -> list:
    """拼手气红包拆分"""
    if count <= 1:
        return [total]
    parts = []
    remain = total
    for i in range(count - 1):
        avg = remain // (count - i) * 2
        p = random.randint(1, max(1, avg))
        parts.append(p)
        remain -= p
    parts.append(remain)
    random.shuffle(parts)
    return parts


def claim_redpack(event, code: str = "") -> tuple:
    """抢红包，返回 (成功, 金额, 消息)"""
    gid = _gid(event)
    uid = _uid(event)
    rp = get_redpacks(gid)

    # 找可抢的红包
    available = []
    for rp_id, info in rp.items():
        if uid in info.get("claimed", {}) or info.get("code", "") not in (code, ""):
            continue
        if len(info.get("claimed", {})) >= info.get("count", 0):
            continue
        available.append((rp_id, info))

    if not available:
        return False, 0, "没有可抢的红包"

    rp_id, info = available[0]
    idx = len(info.get("claimed", {}))
    amount = info["amounts"][idx]
    info["claimed"][uid] = amount
    set_redpacks(gid, rp)

    add_points(uid, amount)
    return True, amount, f"🧧 抢到 {amount} 积分！"


def list_redpacks(event) -> str:
    """红包列表"""
    gid = _gid(event)
    rp = get_redpacks(gid)
    available = []
    for rp_id, info in rp.items():
        if len(info.get("claimed", {})) >= info.get("count", 0):
            continue
        available.append(info)

    if not available:
        return "暂无红包"

    lines = ["🧧 可抢红包:"]
    for info in available[:5]:
        left = info["count"] - len(info.get("claimed", {}))
        code = info.get("code", "")
        code_str = f" 口令:{code}" if code else ""
        lines.append(f"  {info['total']}积分 {left}/{info['count']}份{code_str}")
    return "\n".join(lines)