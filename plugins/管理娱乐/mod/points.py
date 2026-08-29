"""积分系统 — 增减积分、签到、反甲 (按群隔离, 兼容旧数据)。"""

import random
import time

from .db import get_user, set_user, get_users
from . import config

# 当前群上下文 (命令入口设置, 按群隔离积分)
_current_gid = ""


def set_group(gid):
    """命令入口设置群上下文 (积分/配置按群隔离)"""
    global _current_gid
    _current_gid = str(gid or "")
    config.set_group_gid(gid or "")


def _g():
    return _current_gid


def _today():
    return time.strftime("%Y%m%d")


def _uid(event):
    return str(event.user_id)


def _nick(event):
    return getattr(event, "user_name", "") or str(event.user_id)


def _points_key(gid=None):
    gid = gid or _g()
    return f"pts:{gid}" if gid else "points"


def _sign_key(gid=None):
    gid = gid or _g()
    return f"sign:{gid}" if gid else "sign_day"


def _streak_key(gid=None):
    gid = gid or _g()
    return f"streak:{gid}" if gid else "sign_streak"


def ensure_user(event) -> dict:
    """确保用户数据存在，返回用户数据"""
    uid = _uid(event)
    u = get_user(uid)
    if not u:
        u = {"points": 0, "armor_until": "0", "sign_day": "", "sign_streak": 0,
             "nickname": _nick(event), "qq": uid, "banned": False}
        set_user(uid, u)
    # 更新昵称
    u["nickname"] = _nick(event)
    return u


def add_points(uid, pts: int, event=None, gid=None):
    u = get_user(uid)
    if not u and event:
        u = ensure_user(event)
    if not u:
        return
    key = _points_key(gid)
    u[key] = max(0, u.get(key, 0) + pts)
    # 兼容旧字段: 保持 points 为全局合计
    set_user(uid, u)


def get_points(uid, gid=None):
    u = get_user(uid)
    key = _points_key(gid)
    v = u.get(key, None)
    if v is not None:
        return v
    # 回退: 无群则读全局; 有群且无群级数据则从全局初始化
    return u.get("points", 0)


def sign(event) -> tuple:
    """签到，返回 (成功, 新积分, 连续天数, 消息)"""
    from . import config as c
    if not c.get_feature("sign"):
        return False, 0, 0, "签到功能已关闭"

    uid = _uid(event)
    u = ensure_user(event)
    today = _today()
    s_key = _sign_key()
    if u.get(s_key) == today:
        return False, 0, 0, c.REPLIES.get("sign_fail", "今天已签到")

    points = random.randint(c.get_param("sign_lo"), c.get_param("sign_hi"))
    st_key = _streak_key()
    streak = u.get(st_key, 0)
    if u.get(s_key) == _yesterday():
        streak += 1
    else:
        streak = 1

    u[s_key] = today
    u[st_key] = streak
    p_key = _points_key()
    u[p_key] = u.get(p_key, 0) + points
    set_user(uid, u)

    msg = c.REPLIES.get("sign_ok", "签到成功+{points}").format(points=points, streak=streak)
    return True, u[p_key], streak, msg


def _yesterday():
    return time.strftime("%Y%m%d", time.localtime(time.time() - 86400))


def lottery(event) -> tuple:
    """抽奖，返回 (成功, 中奖积分, 消息)"""
    from . import config as c
    if not c.get_feature("lottery"):
        return False, 0, "抽奖功能已关闭"

    uid = _uid(event)
    u = ensure_user(event)
    p_key = _points_key()
    if u.get(p_key, 0) < c.get_param("lottery_cost"):
        cost = c.get_param("lottery_cost")
        return False, 0, f"积分不足，需要{cost}积分"

    u[p_key] -= c.get_param("lottery_cost")

    if random.random() < c.get_param("lottery_win_rate"):
        win = random.randint(c.get_param("lottery_lo"), c.get_param("lottery_hi"))
        u[p_key] += win
        set_user(uid, u)
        return True, win, c.REPLIES.get("lottery_win", "中奖+{points}").format(points=win)

    set_user(uid, u)
    return False, 0, c.REPLIES.get("lottery_lose", "未中奖")


def rob(event, target_uid, target_nick) -> tuple:
    """抢劫，返回 (成功, 积分, 消息)"""
    from . import config as c
    if not c.get_feature("rob"):
        return False, 0, "抢劫功能已关闭"

    uid = _uid(event)
    u = ensure_user(event)
    tu = get_user(target_uid)
    if not tu:
        return False, 0, "目标用户不存在"

    # 检查反甲
    armor = tu.get("armor_until", "0")
    now = time.time()
    if armor != "0":
        try:
            if float(armor) > now:
                penalty = random.randint(c.get_param("robbery_lo"), c.get_param("robbery_hi"))
                p_key = _points_key()
                u[p_key] = max(0, u.get(p_key, 0) - penalty)
                set_user(uid, u)
                return False, -penalty, c.REPLIES.get("rob_armor", "被反甲反弹").format(nickname=target_nick, points=penalty)
        except ValueError:
            pass

    if random.random() < c.get_param("robbery_rate"):
        pts = random.randint(c.get_param("robbery_lo"), c.get_param("robbery_hi"))
        tp_key = _points_key()
        pts = min(pts, tu.get(tp_key, 0))
        tu[tp_key] = max(0, tu.get(tp_key, 0) - pts)
        p_key = _points_key()
        u[p_key] = u.get(p_key, 0) + pts
        set_user(uid, u)
        set_user(target_uid, tu)
        return True, pts, c.REPLIES.get("rob_ok", "抢劫成功").format(nickname=target_nick, points=pts)

    return False, 0, c.REPLIES.get("rob_fail", "抢劫失败").format(nickname=target_nick)


def buy_armor(event) -> tuple:
    """购买反甲，返回 (成功, 消息)"""
    from . import config as c
    if not c.get_feature("armor"):
        return False, "反甲功能已关闭"

    uid = _uid(event)
    u = ensure_user(event)
    p_key = _points_key()
    armor_cost = c.get_param("armor_cost")
    armor_days = c.get_param("armor_days")
    if u.get(p_key, 0) < armor_cost:
        return False, f"积分不足，需要{armor_cost}积分"

    u[p_key] -= armor_cost
    u["armor_until"] = str(time.time() + armor_days * 86400)
    set_user(uid, u)
    return True, f"🛡 反甲已购买！有效期{armor_days}天，抢劫你的人会被反弹"


def get_rank(event) -> list:
    """获取积分排行 (当前群)"""
    users = get_users()
    p_key = _points_key()
    items = []
    for uid, u in users.items():
        if uid == "_meta":
            continue
        v = u.get(p_key, None)
        if v is None:
            v = u.get("points", 0)
        items.append((uid, v, u.get("nickname", uid)))
    items.sort(key=lambda x: -x[1])
    return items[:20]


def get_my_info(event) -> str:
    """我的信息"""
    uid = _uid(event)
    u = ensure_user(event)
    users = get_users()
    p_key = _points_key()
    items = []
    for other_uid, ou in users.items():
        if other_uid == "_meta":
            continue
        v = ou.get(p_key, None)
        if v is None:
            v = ou.get("points", 0)
        items.append((other_uid, v))
    items.sort(key=lambda x: -x[1])
    rank = next((i+1 for i, (u2, _) in enumerate(items) if u2 == uid), 0)
    total_users = len(items)

    armor = u.get("armor_until", "0")
    armor_str = "🛡 有" if armor != "0" and float(armor) > time.time() else "❌ 无"

    # 今日剩余抽奖次数 (限次守卫)
    try:
        from . import config
        from .db import get_user as _gu
        meta = _gu("_meta") or {}
        gid = str(getattr(event, "group_id", "0") or "0")
        dk = f"d:{gid}:{uid}:lottery:{time.strftime('%Y%m%d')}"
        used = int(meta.get(dk, 0) or 0)
        remain = max(0, 5 - used)
    except Exception:
        remain = "?"

    return (
        f"👤 昵称: {u.get('nickname', uid)}\n"
        f"💰 积分: {u.get(p_key, 0)}\n"
        f"🏆 排名: 第{rank}/{total_users}名\n"
        f"🛡 反甲: {armor_str}\n"
        f"🔥 连续签到: {u.get(_streak_key(), 0)}天\n"
        f"🎰 今日剩余抽奖: {remain}次"
    )