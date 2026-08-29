"""全局配置 — 默认值 + 加载/保存 + 按群覆盖。"""

from .db import get_config as _db_get, set_config as _db_set

# 积分参数
SIGN_LO = 1
SIGN_HI = 150
LOTTERY_COST = 20
LOTTERY_LO = 1
LOTTERY_HI = 100
LOTTERY_WIN_RATE = 0.6
ROBBERY_LO = 10
ROBBERY_HI = 80
ROBBERY_SUCCESS_RATE = 0.4
ARMOR_COST = 200
ARMOR_DAYS = 3
MUTE_COST = 100
REVOKE_COST = 50
REDPACK_MIN = 10
REDPACK_MAX_COUNT = 20

# 阶梯惩罚
STEP1_MUTE = 10      # 第2次违规: 禁言N分钟
STEP2_MUTE = 60      # 第3次违规: 禁言N分钟
VIOLATION_RESET = 24  # 冷却小时

# 刷屏检测
SPAM_INTERVAL = 5     # N秒内
SPAM_COUNT = 5        # M条消息

# 功能开关（默认全开）
FEATURES = {
    "mute": True, "sign": True, "lottery": True, "redpack": True,
    "rob": True, "armor": True, "tarot": True,
    "fortune": True, "vote": True, "jrrp": True,
    "weather": True, "hot": True, "wzry": True,
    "wallpaper": True, "news": True, "moyu": True,
    "music": True, "doubao": False,
}

# 回复文案
REPLIES = {
    "sign_ok": "🎉 签到成功！+{points}积分，连续{streak}天",
    "sign_fail": "你今天已经签到过了，明天再来~",
    "lottery_win": "🎰 恭喜中奖！+{points}积分",
    "lottery_lose": "😢 谢谢参与，再接再厉",
    "rob_ok": "🔫 抢劫成功！从{nickname}抢到{points}积分",
    "rob_fail": "😅 抢劫失败，反被{nickname}追着打",
    "rob_armor": "🛡 {nickname}有反甲！你被反弹{points}积分",
    "sign_format": "签到",
    "welcome": "👋 欢迎 {nickname} 加入 {group_name}！\n发送 签到 开始赚积分吧~",
    "tarot": "🃏 {nickname} 抽到了「{card}」\n{meaning}",
    "fortune": "🔮 {nickname} 今日运势: {score}分\n{luck}",
    "jrrp": "🍀 {nickname} 今日人品: {score}分\n{comment}",
    "vote_result": "📊 投票: {title}\n{results}\n🏆 {winner} 胜出！",
}

# 可被群覆盖的数值参数名 (与默认值映射)
_PARAM_NAMES = {
    "sign_lo": SIGN_LO, "sign_hi": SIGN_HI,
    "lottery_cost": LOTTERY_COST, "lottery_lo": LOTTERY_LO, "lottery_hi": LOTTERY_HI,
    "lottery_win_rate": LOTTERY_WIN_RATE,
    "robbery_lo": ROBBERY_LO, "robbery_hi": ROBBERY_HI, "robbery_rate": ROBBERY_SUCCESS_RATE,
    "armor_cost": ARMOR_COST, "armor_days": ARMOR_DAYS,
    "mute_cost": MUTE_COST, "revoke_cost": REVOKE_COST,
    "redpack_min": REDPACK_MIN, "redpack_max_count": REDPACK_MAX_COUNT,
    "step1_mute": STEP1_MUTE, "step2_mute": STEP2_MUTE,
    "violation_reset": VIOLATION_RESET,
    "spam_interval": SPAM_INTERVAL, "spam_count": SPAM_COUNT,
}


def _cfg():
    return _db_get() or {}


def _sync(d: dict):
    """将全局配置同步到模块变量 (仅全局默认值)"""
    global SIGN_LO, SIGN_HI, LOTTERY_COST, LOTTERY_LO, LOTTERY_HI
    global LOTTERY_WIN_RATE, ROBBERY_LO, ROBBERY_HI, ROBBERY_SUCCESS_RATE
    global ARMOR_COST, ARMOR_DAYS, MUTE_COST, REVOKE_COST
    global REDPACK_MIN, REDPACK_MAX_COUNT, STEP1_MUTE, STEP2_MUTE
    global VIOLATION_RESET, SPAM_INTERVAL, SPAM_COUNT, FEATURES, REPLIES

    SIGN_LO = int(d.get("sign_lo", SIGN_LO))
    SIGN_HI = int(d.get("sign_hi", SIGN_HI))
    LOTTERY_COST = int(d.get("lottery_cost", LOTTERY_COST))
    LOTTERY_LO = int(d.get("lottery_lo", LOTTERY_LO))
    LOTTERY_HI = int(d.get("lottery_hi", LOTTERY_HI))
    LOTTERY_WIN_RATE = float(d.get("lottery_win_rate", LOTTERY_WIN_RATE))
    ROBBERY_LO = int(d.get("robbery_lo", ROBBERY_LO))
    ROBBERY_HI = int(d.get("robbery_hi", ROBBERY_HI))
    ROBBERY_SUCCESS_RATE = float(d.get("robbery_rate", ROBBERY_SUCCESS_RATE))
    ARMOR_COST = int(d.get("armor_cost", ARMOR_COST))
    ARMOR_DAYS = int(d.get("armor_days", ARMOR_DAYS))
    MUTE_COST = int(d.get("mute_cost", MUTE_COST))
    REVOKE_COST = int(d.get("revoke_cost", REVOKE_COST))
    REDPACK_MIN = int(d.get("redpack_min", REDPACK_MIN))
    REDPACK_MAX_COUNT = int(d.get("redpack_max_count", REDPACK_MAX_COUNT))
    STEP1_MUTE = int(d.get("step1_mute", STEP1_MUTE))
    STEP2_MUTE = int(d.get("step2_mute", STEP2_MUTE))
    VIOLATION_RESET = int(d.get("violation_reset", VIOLATION_RESET))
    SPAM_INTERVAL = int(d.get("spam_interval", SPAM_INTERVAL))
    SPAM_COUNT = int(d.get("spam_count", SPAM_COUNT))
    FEATURES = d.get("features", FEATURES)
    REPLIES = d.get("replies", REPLIES)


def load_config():
    d = _cfg()
    _init_defaults()  # 幂等: 仅填充空数据文件(违禁词/欢迎语/入群验证)
    if not d:
        # 首次启动: 写入默认配置
        d = _defaults_dict()
        _db_set(d)
        _sync(d)
    else:
        _sync(d)


def _defaults_dict():
    return {
        "sign_lo": SIGN_LO, "sign_hi": SIGN_HI,
        "lottery_cost": LOTTERY_COST, "lottery_lo": LOTTERY_LO, "lottery_hi": LOTTERY_HI,
        "lottery_win_rate": LOTTERY_WIN_RATE,
        "robbery_lo": ROBBERY_LO, "robbery_hi": ROBBERY_HI, "robbery_rate": ROBBERY_SUCCESS_RATE,
        "armor_cost": ARMOR_COST, "armor_days": ARMOR_DAYS,
        "mute_cost": MUTE_COST, "revoke_cost": REVOKE_COST,
        "redpack_min": REDPACK_MIN, "redpack_max_count": REDPACK_MAX_COUNT,
        "step1_mute": STEP1_MUTE, "step2_mute": STEP2_MUTE,
        "violation_reset": VIOLATION_RESET,
        "spam_interval": SPAM_INTERVAL, "spam_count": SPAM_COUNT,
        "features": dict(FEATURES),
        "replies": dict(REPLIES),
    }


def _init_defaults():
    """初始化其他数据文件默认值 (in 可隔离的数据文件中)"""
    from .db import (
        get_banned_words, set_banned_words,
        get_welcome_msg, set_welcome_msg,
        get_join_verify, set_join_verify,
    )
    if not get_banned_words():
        set_banned_words(["傻逼", "傻b", "sb", "妈的", "卧槽尼玛", "去死", "废物", "垃圾"])
    if not get_welcome_msg():
        set_welcome_msg("👋 欢迎 {nickname} 加入 {group_name}！\n发送「签到」开始赚积分吧~")
    v = get_join_verify()
    if not v:
        # 入群验证默认开启: 数字验证码, 3次机会, 5分钟超时
        set_join_verify({"enabled": True, "mode": "digits", "digits": 4, "tries": 3, "timeout": 300})


def save_config(d: dict):
    """保存配置（与现有配置合并，不覆盖 features/replies）"""
    old = _db_get() or {}
    merged = dict(old)
    merged.update(d)
    _db_set(merged)
    _sync(merged)


def get_config() -> dict:
    """读取原始配置 dict (含 api_keys)"""
    return _db_get() or {}


# ================= 按群配置 =================

# 当前事件群上下文 (命令/拦截入口设置)
_current_gid = ""


def set_group_gid(gid):
    """设置当前处理的群ID (由 points.set_group / monitor 调用)"""
    global _current_gid
    _current_gid = str(gid or "")


def _gid(gid=None):
    """获取当前事件的群ID; 无则回退上下文, 再回退全局默认"""
    if gid is not None:
        return str(gid)
    return _current_gid


def _group_overrides(gid=None):
    """返回该群的覆盖配置 dict (无则空)"""
    g = _gid(gid)
    if not g:
        return {}
    d = _cfg()
    groups = d.get("groups") or {}
    return groups.get(g) or {}


def get_param(name, gid=None, default=None):
    """按群读取数值参数: 群覆盖 > 全局配置 > 默认值"""
    ov = _group_overrides(gid)
    if name in ov and ov[name] is not None:
        return ov[name]
    d = _cfg()
    if name in d and d[name] is not None:
        return d[name]
    return default if default is not None else _PARAM_NAMES.get(name)


def get_feature(name: str, gid=None) -> bool:
    """按群读取功能开关: 群覆盖 > 全局"""
    ov = _group_overrides(gid)
    if name in ov.get("features", {}):
        return bool(ov["features"][name])
    return FEATURES.get(name, True)


def get_reply(name: str, gid=None) -> str:
    """按群读取回复文案"""
    ov = _group_overrides(gid)
    if name in ov.get("replies", {}):
        return str(ov["replies"][name])
    return REPLIES.get(name, "")


def save_group_config(gid, data: dict):
    """保存某个群的覆盖配置 (合并, 不影响其他群)"""
    g = str(gid)
    if not g:
        return
    d = _cfg() or {}
    groups = d.get("groups") or {}
    cur = groups.get(g) or {}
    # 合并覆盖字段
    for k, v in data.items():
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = v
    groups[g] = cur
    d["groups"] = groups
    _db_set(d)
    _sync(d)


def get_group_config(gid) -> dict:
    """返回该群完整有效配置 (全局默认 + 群覆盖, 供 Web 面板展示)"""
    d = _cfg() or {}
    merged = dict(d)
    groups = d.get("groups") or {}
    ov = groups.get(str(gid)) or {}
    for k, v in ov.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    return merged