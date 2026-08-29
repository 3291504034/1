"""数据持久化 — JSON文件读写。"""

import json
import os
import time
from pathlib import Path
from threading import Lock

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_lock = Lock()

_DB = {
    "users": {},       # {uid: {points, armor_until, sign_day, violations, banned, ...}}
    "config": {},      # 全局配置
    "logs": [],        # 操作日志
    "redpacks": {},    # 红包 {gid: {id: {amount, count, code, ...}}}
    "blacklist": {},   # 黑名单 {gid: {uid: {reason, time, expire}}}
    "votes": {},       # 投票 {gid: {id: {title, options, votes, deadline}}}
    "mutes": {},       # 禁言记录 {gid: {uid: {until, reason}}}
    "violations": {},  # 违规记录 {gid: {uid: [count, reset_time]}}
    "banned_words": [],# 违禁词列表
    "welcome_msg": "", # 入群欢迎语
    "join_verify": {}, # 入群验证 {enabled: bool, question: str, answer: str}
    "doubao_cookie": "",# 豆包Cookie
}


def init_db():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in _DB:
        path = _DATA_DIR / f"{name}.json"
        if not path.exists():
            _save(name, _DB[name])


def _load(name):
    path = _DATA_DIR / f"{name}.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return _DB.get(name, {})


def _save(name, data):
    path = _DATA_DIR / f"{name}.json"
    tmp = path.with_suffix(".tmp")
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def get_users():
    return _load("users")


def set_user(uid, data):
    users = _load("users")
    users[str(uid)] = data
    _save("users", users)


def get_user(uid):
    return _load("users").get(str(uid), {})


def get_group_name(gid) -> str:
    """查群名: 优先框架 groups_users 表 (真实群名)"""
    import sqlite3, glob
    gid = str(gid)
    try:
        for db in glob.glob(str(_DATA_DIR.parent.parent.parent / "data" / "log" / "*" / "data.db")):
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT group_name FROM groups_users WHERE group_id=? LIMIT 1",
                    (gid,),
                ).fetchone()
                con.close()
                if row and row[0]:
                    return str(row[0])
            except Exception:
                con.close()
    except Exception:
        pass
    return ""


def get_user_name(uid):
    """查用户昵称: 优先消息记录的 author.username, 其次框架 users 表"""
    info = get_user_info(uid)
    return info.get("username", "")


def get_user_info(uid):
    """查用户信息 (昵称/角色): 解析最近消息记录 + 框架 users 表"""
    import sqlite3, glob, json
    uid = str(uid)
    out = {"username": "", "role": ""}
    # 1. 最近消息记录的 author (同时带 username + member_role)
    try:
        for db in sorted(glob.glob(str(_DATA_DIR.parent.parent.parent / "data" / "log" / "*" / "2026-*" / "message.db")), reverse=True):
            try:
                con = sqlite3.connect(db)
                row = con.execute(
                    "SELECT raw_message FROM log WHERE direction='receive' AND user_id=? "
                    "AND raw_message LIKE '%username%' ORDER BY id DESC LIMIT 1",
                    (uid,),
                ).fetchone()
                con.close()
                if row and row[0]:
                    d = json.loads(row[0])
                    author = (d.get("d") or {}).get("author") or {}
                    if author.get("username"):
                        out["username"] = str(author["username"])
                        out["role"] = str(author.get("member_role", "") or "")
                        return out
            except Exception:
                continue
    except Exception:
        pass
    # 2. 框架 users 表
    try:
        for db in glob.glob(str(_DATA_DIR.parent.parent.parent / "data" / "log" / "*" / "data.db")):
            con = sqlite3.connect(db)
            try:
                row = con.execute("SELECT name FROM users WHERE user_id=?", (uid,)).fetchone()
                con.close()
                if row and row[0]:
                    out["username"] = str(row[0])
                    return out
            except Exception:
                con.close()
    except Exception:
        pass
    return out


def get_config():
    return _load("config")


def set_config(data):
    _save("config", data)


def get_logs(limit=50):
    logs = _load("logs")
    return logs[-limit:]


def add_log(text):
    logs = _load("logs")
    logs.append({"time": time.strftime("%m-%d %H:%M"), "text": text})
    if len(logs) > 500:
        logs = logs[-500:]
    _save("logs", logs)


def get_redpacks(gid):
    return _load("redpacks").get(str(gid), {})


def set_redpacks(gid, data):
    all_rp = _load("redpacks")
    all_rp[str(gid)] = data
    _save("redpacks", all_rp)


def get_blacklist(gid):
    return _load("blacklist").get(str(gid), {})


def set_blacklist(gid, data):
    all_bl = _load("blacklist")
    all_bl[str(gid)] = data
    _save("blacklist", all_bl)


def get_votes(gid):
    return _load("votes").get(str(gid), {})


def set_votes(gid, data):
    all_v = _load("votes")
    all_v[str(gid)] = data
    _save("votes", all_v)


def get_violations(gid):
    return _load("violations").get(str(gid), {})


def set_violations(gid, data):
    all_v = _load("violations")
    all_v[str(gid)] = data
    _save("violations", all_v)


def get_banned_words(gid=None):
    """违禁词: 按群 {gid: [...]} 存储, 无群时读全局列表"""
    d = _load("banned_words")
    if gid is not None:
        if isinstance(d, dict):
            return d.get(str(gid))
        return None  # 旧格式是全局列表, 群级未定义
    if isinstance(d, dict):
        return d.get("_global", [])
    return d


def set_banned_words(data, gid=None):
    """保存违禁词: gid 为空保存全局, 否则保存该群"""
    if gid is None:
        # 全局: 若已是 dict 格式保留群条目, 更新 _global
        d = _load("banned_words")
        if isinstance(d, dict):
            d["_global"] = data
            _save("banned_words", d)
        else:
            _save("banned_words", data)
        return
    d = _load("banned_words")
    if not isinstance(d, dict):
        d = {"_global": d if isinstance(d, list) else []}
    d[str(gid)] = data
    _save("banned_words", d)


def get_welcome_msg(gid=None):
    """欢迎语: 按群 {gid: str} 存储, 无群时读全局"""
    d = _load("welcome_msg")
    if gid is not None:
        if isinstance(d, dict):
            return d.get(str(gid))
        return None
    if isinstance(d, dict):
        return d.get("_global", "")
    return d


def set_welcome_msg(data, gid=None):
    """保存欢迎语: gid 为空保存全局"""
    if gid is None:
        d = _load("welcome_msg")
        if isinstance(d, dict):
            d["_global"] = data
            _save("welcome_msg", d)
        else:
            _save("welcome_msg", data)
        return
    d = _load("welcome_msg")
    if not isinstance(d, dict):
        d = {"_global": d if isinstance(d, str) else ""}
    d[str(gid)] = data
    _save("welcome_msg", d)


def get_join_verify(gid=None):
    """入群验证: 按群 {gid: {...}} 存储, 无群时读全局"""
    d = _load("join_verify")
    if gid is not None:
        if isinstance(d, dict):
            return d.get(str(gid))
        return None
    if isinstance(d, dict):
        return d.get("_global")
    return d


def set_join_verify(data, gid=None):
    """保存入群验证: gid 为空保存全局"""
    if gid is None:
        d = _load("join_verify")
        if isinstance(d, dict):
            d["_global"] = data
            _save("join_verify", d)
        else:
            _save("join_verify", data)
        return
    d = _load("join_verify")
    if not isinstance(d, dict):
        d = {"_global": d if isinstance(d, dict) else {}}
    d[str(gid)] = data
    _save("join_verify", d)


def get_doubao_cookie():
    """返回 cookie 列表 ([] 表示未登录)"""
    d = _load("doubao_cookie")
    if isinstance(d, list):
        return d
    if isinstance(d, str) and d.strip():
        try:
            v = json.loads(d)
            return v if isinstance(v, list) else []
        except json.JSONDecodeError:
            return []
    return []


def set_doubao_cookie(cookies):
    """保存 cookie 列表"""
    _save("doubao_cookie", cookies if isinstance(cookies, list) else [])