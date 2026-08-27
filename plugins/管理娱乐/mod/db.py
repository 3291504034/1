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


def get_banned_words():
    return _load("banned_words")


def set_banned_words(data):
    _save("banned_words", data)


def get_welcome_msg():
    return _load("welcome_msg")


def set_welcome_msg(data):
    _save("welcome_msg", data)


def get_join_verify():
    return _load("join_verify")


def set_join_verify(data):
    _save("join_verify", data)


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