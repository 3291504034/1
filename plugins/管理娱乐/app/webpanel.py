"""Web 管理面板 API。"""

import asyncio
import json
from pathlib import Path
from aiohttp import web
from core.base.logger import get_logger, PLUGIN
from core.plugin.web_pages import register_route

from ..mod import db
from ..mod import config as cfg

log = get_logger(PLUGIN, "管理娱乐面板")
PREFIX = "/api/ext/superadmin"
_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
_ASSETS = {
    "panel.css": "text/css; charset=utf-8",
    "panel.js": "text/javascript; charset=utf-8",
}
_registered = []


def register_routes():
    routes = [
        ("GET", "users", _api_users, True),
        ("POST", "points", _api_points, True),
        ("GET", "stats", _api_stats, True),
        ("GET", "rank", _api_rank, True),
        ("GET", "groups", _api_groups, True),
        ("GET", "config", _api_config, True),
        ("POST", "config", _api_save_config, True),
        ("POST", "toggle", _api_toggle, True),
        ("GET", "logs", _api_logs, True),
        ("GET", "banned_words", _api_banned_words, True),
        ("POST", "banned_words", _api_save_banned_words, True),
        ("GET", "welcome", _api_welcome, True),
        ("POST", "welcome", _api_save_welcome, True),
        ("POST", "join_verify", _api_save_join_verify, True),
        ("GET", "join_verify", _api_join_verify, True),
        ("GET", "blacklist", _api_blacklist, True),
        ("POST", "blacklist", _api_save_blacklist, True),
        ("GET", "replies", _api_replies, True),
        ("POST", "replies", _api_save_replies, True),
        ("GET", "apikeys", _api_apikeys, True),
        ("POST", "apikeys", _api_save_apikeys, True),
    ]
    for method, path, handler, auth in routes:
        register_route(method, f"{PREFIX}/{path}", handler, auth=auth)
        _registered.append(f"{method} {PREFIX}/{path}")
    for name in _ASSETS:
        register_route("GET", f"{PREFIX}/assets/{name}", _asset, auth=False)
        _registered.append(f"GET {PREFIX}/assets/{name}")
    log.info("管理娱乐 Web 路由已注册: /api/ext/superadmin/*")


def unregister_routes():
    for r in _registered:
        log.info(f"  已注销路由: {r}")
    _registered.clear()


async def _asset(request):
    filename = request.path.rsplit("/", 1)[-1]
    content_type = _ASSETS.get(filename)
    if not content_type:
        raise web.HTTPNotFound()
    path = _WEB_DIR / filename
    if not await asyncio.to_thread(path.is_file):
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "no-cache", "Content-Type": content_type})


def _json(data, **kw):
    return web.json_response(data, **kw)


# ========== 统计 ==========

def _pts_for(u, gid):
    """按群取积分: 群级键 pts:{gid} 优先, 回退全局 points"""
    if gid:
        v = u.get(f"pts:{gid}")
        if v is not None:
            return v
    return u.get("points", 0)


def _resolve_gid(request):
    return request.query.get("gid", "") or ""


def _appid():
    d = db.get_config() or {}
    return str(d.get("appid", "100000000"))


async def _api_groups(request):
    """群列表: 优先框架 groups_users 表(带真实群名), 回退消息日志去重"""
    try:
        import glob, sqlite3
        fw_data = Path(__file__).resolve().parent.parent.parent.parent / "data"
        seen = {}  # gid -> name
        # 1. 优先: 框架 groups_users 表 (有真实群名)
        for db in glob.glob(str(fw_data / "log" / "*" / "data.db")):
            try:
                con = sqlite3.connect(db)
                for gid, gname in con.execute(
                    "SELECT group_id, group_name FROM groups_users WHERE group_id IS NOT NULL AND group_id!=''"
                ):
                    if gid and gid not in seen:
                        seen[gid] = gname or ""
                con.close()
            except Exception:
                continue
        # 2. 回退: 消息日志里出现的群
        if not seen:
            for db in reversed(sorted(glob.glob(str(fw_data / "log" / "*" / "*" / "message.db")))):
                try:
                    con = sqlite3.connect(db)
                    for gid, in con.execute("SELECT DISTINCT group_id FROM log WHERE group_id!='' AND group_id IS NOT NULL"):
                        if gid and gid not in seen:
                            seen[gid] = ""
                    con.close()
                except Exception:
                    continue
        groups = [{"gid": g, "name": n or "", "label": (n or g)[:20]} for g, n in seen.items()]
        return _json({"success": True, "groups": groups})
    except Exception:
        return _json({"success": True, "groups": []})


async def _api_stats(request):
    gid = _resolve_gid(request)
    users = db.get_users()
    total_points = sum(_pts_for(u, gid) for u in users.values())
    total_armor = sum(1 for u in users.values() if u.get("armor_until", "0") != "0")
    bl = db.get_blacklist(gid or "0")
    if not bl:
        bl = {}
    return _json({
        "success": True,
        "users": len(users),
        "points": total_points,
        "armor": total_armor,
        "blacklist": len(bl),
        "logs": len(db.get_logs(999)),
        "appid": _appid(),
    })


async def _api_rank(request):
    gid = _resolve_gid(request)
    users = db.get_users()
    items = [(uid, _pts_for(u, gid), u.get("nickname", uid), u.get("qq", uid))
             for uid, u in users.items() if uid != "_meta"]
    items.sort(key=lambda x: -x[1])
    rank = [{"uid": uid, "qq": qq, "nickname": nick, "points": pts,
             "avatar": f"https://q.qlogo.cn/qqapp/{_appid()}/{uid}/100"}
            for uid, pts, nick, qq in items[:20]]
    return _json({"success": True, "rank": rank})


# ========== 用户管理 ==========

async def _api_users(request):
    gid = _resolve_gid(request)
    users = db.get_users()
    items = []
    import time as _time
    for uid, u in users.items():
        if uid == "_meta":
            continue
        armor = (u.get("armor_until", "0") or "0")
        has_armor = False
        try:
            has_armor = armor != "0" and float(armor) > _time.time()
        except (TypeError, ValueError):
            pass
        items.append({
            "uid": uid,
            "qq": u.get("qq", uid),
            "nickname": u.get("nickname", uid),
            "points": _pts_for(u, gid),
            "armor": has_armor,
            "sign_streak": u.get("sign_streak", 0) or u.get(f"streak:{gid}", 0),
            "banned": u.get("banned", False),
            "avatar": f"https://q.qlogo.cn/qqapp/{_appid()}/{uid}/100",
        })
    items.sort(key=lambda x: -x["points"])
    return _json({"success": True, "users": items})


async def _api_points(request):
    data = await request.json()
    uid = data.get("uid")
    pts = int(data.get("points", 0))
    gid = data.get("gid", "")
    if not uid:
        return _json({"success": False, "error": "缺少uid"})
    u = db.get_user(uid)
    if not u:
        return _json({"success": False, "error": "用户不存在"})
    if gid:
        key = f"pts:{gid}"
        u[key] = max(0, u.get(key, 0) + pts)
    else:
        u["points"] = max(0, u.get("points", 0) + pts)
    db.set_user(uid, u)
    db.add_log(f"管理员修改积分 {uid} {pts:+d}" + (f" (群{gid[:8]})" if gid else ""))
    return _json({"success": True, "points": u.get(f"pts:{gid}", u["points"])})


async def _api_delete_user(request):
    data = await request.json()
    uid = data.get("uid")
    if not uid:
        return _json({"success": False, "error": "缺少uid"})
    users = db.get_users()
    if uid in users:
        del users[uid]
        db.set_user(uid, {})
    return _json({"success": True})


# ========== 功能开关 ==========

async def _api_toggle(request):
    data = await request.json()
    feature = data.get("feature")
    enabled = bool(data.get("enabled"))
    if feature and feature in cfg.FEATURES:
        cfg.FEATURES[feature] = enabled
        d = db.get_config() or {}
        d["features"] = cfg.FEATURES
        db.set_config(d)
        return _json({"success": True})
    return _json({"success": False, "error": "未知功能"})


# ========== 配置 ==========

async def _api_config(request):
    d = db.get_config()
    return _json({"success": True, "config": d})


async def _api_save_config(request):
    data = await request.json()
    cfg.save_config(data)
    return _json({"success": True})


# ========== 接口密钥 ==========

# 各密钥的填写位置说明 (doc_url 为接口文档地址)
_API_KEY_FIELDS = [
    {
        "key": "gulangsc",
        "name": "天迹云 apikey",
        "doc_url": "https://gulangsc.cn/doc",
        "usage": "装高手 / 单身狗 / 马内 / 小姐姐视频",
        "where": "登录 https://gulangsc.cn → 个人中心 → 复制 apikey，填入右侧输入框",
    },
]


async def _api_apikeys(request):
    keys = (db.get_config() or {}).get("api_keys") or {}
    return _json({"success": True, "keys": keys, "fields": _API_KEY_FIELDS})


async def _api_save_apikeys(request):
    data = await request.json() or {}
    keys = data.get("keys") or {}
    d = db.get_config() or {}
    d["api_keys"] = {str(k).strip(): str(v).strip() for k, v in keys.items() if str(v).strip()}
    db.set_config(d)
    cfg.load_config()
    return _json({"success": True})


# ========== 日志 ==========

async def _api_logs(request):
    logs = db.get_logs(100)
    return _json({"success": True, "logs": logs})


# ========== 违禁词 ==========

async def _api_banned_words(request):
    words = db.get_banned_words()
    return _json({"success": True, "words": words})


async def _api_save_banned_words(request):
    data = await request.json()
    words = data.get("words", [])
    db.set_banned_words(words)
    return _json({"success": True})


# ========== 欢迎语 ==========

async def _api_welcome(request):
    msg = db.get_welcome_msg()
    return _json({"success": True, "welcome": msg})


async def _api_save_welcome(request):
    data = await request.json()
    msg = data.get("welcome", "")
    db.set_welcome_msg(msg)
    return _json({"success": True})


# ========== 入群验证 ==========

async def _api_join_verify(request):
    v = db.get_join_verify()
    return _json({"success": True, "verify": v})


async def _api_save_join_verify(request):
    data = await request.json()
    db.set_join_verify(data)
    return _json({"success": True})


# ========== 黑名单 ==========

async def _api_blacklist(request):
    gid = request.query.get("gid", "0")
    bl = db.get_blacklist(gid)
    return _json({"success": True, "blacklist": bl})


async def _api_save_blacklist(request):
    data = await request.json()
    gid = data.get("gid", "0")
    bl = data.get("blacklist", {})
    db.set_blacklist(gid, bl)
    return _json({"success": True})


# ========== 回复文案 ==========

async def _api_replies(request):
    return _json({"success": True, "replies": cfg.REPLIES})


async def _api_save_replies(request):
    data = await request.json()
    replies = data.get("replies", {})
    cfg.REPLIES.update(replies)
    d = db.get_config() or {}
    d["replies"] = cfg.REPLIES
    db.set_config(d)
    return _json({"success": True})