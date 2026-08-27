"""命令处理 — 所有 handler 注册。

命令格式说明:
- event.content 已剔除 @ 标签, 命令词匹配 content (锚定 ^)
- @目标从 event.mentions 提取 (排除机器人/全体/自己)
- 支持双向: "@机器人 禁言 @用户" 与 "禁言 @用户" 的 content 都是 "禁言"
"""

import re
import functools
import time
from core.plugin.decorators import handler
from ..mod import points, mute, redpack, tarot, api, config as cfg
from ..mod.db import add_log
from ..mod.reply import (
    reply_md, reply_card, reply_text_md, avatar_url, prefix_at, markdown_block,
    check_and_record_limit, limit_mute, nick_of,
)


# ========== 工具函数 ==========

def get_mentions(event):
    """提取消息中的 @目标 (排除机器人/全体/自己), 返回 [(id, role)]"""
    out = []
    for m in getattr(event, "mentions", None) or []:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "")
        if not mid:
            continue
        if m.get("is_you") or m.get("bot") or m.get("scope") == "all":
            continue
        out.append((mid, str(m.get("member_role") or "")))
    return out


def _first_target(event):
    """第一个 @目标 id"""
    items = get_mentions(event)
    return items[0][0] if items else None


def _nums(text):
    return re.findall(r"\d+", text or "")


def _amount(text, default=0):
    nums = _nums(text)
    return int(nums[0]) if nums else default


def _nickname(event):
    return getattr(event, "user_name", "") or str(event.user_id)


def _gid(event):
    return str(getattr(event, "group_id", "0"))


def _text(event):
    return getattr(event, "content", "") or ""


def _gid_handler(fn):
    """命令装饰器: 入口设置群上下文 (积分/限次按群隔离)"""
    @functools.wraps(fn)
    async def wrapper(event, match):
        gid = str(getattr(event, "group_id", "") or "")
        points.set_group(gid)
        return await fn(event, match)
    return wrapper

@handler(r"^(用户信息|查用户|信息)\s*$", name="用户信息", desc="查看 @用户 信息", priority=60, block=True)
async def cmd_user_info(event, match):
    """查询用户信息: 头像缩略图 + 昵称 + 角色 + 触发信息"""
    gid = str(getattr(event, "group_id", ""))
    appid = str(getattr(event, "appid", "") or "")
    target = _first_target(event)
    if not target:
        target = str(getattr(event, "user_id", "") or "")
    if not target:
        return await reply_text_md(event, "用法: @机器人 用户信息 @用户")

    # 昵称/角色: 优先事件上下文, 其次消息记录/框架用户表
    username = getattr(event, "user_name", "") or ""
    role = ""
    for m in getattr(event, "mentions", None) or []:
        if isinstance(m, dict) and str(m.get("id", "")) == target:
            role = str(m.get("member_role", "") or "")
            if not username:
                username = str(m.get("username", "") or "")
            break
    if not username or not role:
        try:
            from ..mod.db import get_user_info
            rec = get_user_info(target)
            if not username:
                username = rec.get("username", "") or ""
            if not role:
                role = rec.get("role", "") or ""
        except Exception:
            pass

    role_map = {"owner": "群主", "admin": "管理员", "member": "普通成员"}
    role_cn = role_map.get(role, "普通成员")

    # 触发信息 = 当前命令内容
    trigger = _text(event) or "用户信息"
    lines = [
        f"👤 {username or '未知用户'}",
        f"🎖 身份: {role_cn}",
        f"🆔 {target[:16]}",
        f"📋 触发: {trigger}",
    ]
    text = "\n".join(lines)

    # 头像: 框架消息记录同款 openid 头像接口 (q.qlogo.cn/qqapp/{appid}/{openid}/40)
    if appid:
        avatar_url = f"https://q.qlogo.cn/qqapp/{appid}/{target}/40"
        try:
            c = await api._http()
            resp = await c.get(avatar_url, headers={"Referer": f"https://{appid}.framework/"})
            img = resp.content
            if resp.status_code == 200 and img and len(img) > 500:
                if img[:4].lower().startswith((b"\x89png", b"\xff\xd8", b"gif8")):
                    sender = event.sender
                    await sender.reply_image(event, img, content=text)
                    return
        except Exception:
            pass
    await reply_text_md(event, text)


@handler(r"^禁言(?:\s+\d+)?\s*$", name="禁言", desc="禁言 @用户 [分钟]", priority=60, block=True)
async def cmd_mute(event, match):
    if not cfg.get_feature("mute"):
        return await reply_text_md(event, "禁言功能已关闭")
    target = _first_target(event)
    if not target:
        return await reply_text_md(event, "用法: @机器人 禁言 @用户 [分钟]")
    mins = _amount(_text(event), 5)
    msg = await mute.mute(event, target, mins)
    await reply_text_md(event, msg)


@handler(r"^解禁\s*$", name="解禁", desc="解禁 @用户", priority=60, block=True)
async def cmd_unmute(event, match):
    target = _first_target(event)
    if not target:
        return await reply_text_md(event, "用法: @机器人 解禁 @用户")
    msg = await mute.unmute(event, target)
    await reply_text_md(event, msg)


@handler(r"^拉黑(?:\s+\d+)?(?:\s+.*)?$", name="拉黑", desc="拉黑 @用户 [原因]", priority=60, block=True)
async def cmd_blacklist(event, match):
    target = _first_target(event)
    if not target:
        return await reply_text_md(event, "用法: @机器人 拉黑 @用户 [天数] [原因]")
    text = _text(event)
    days = _amount(text, 0)
    # 原因 = 去掉命令词和数字后剩余文本
    reason = re.sub(r"^\s*拉黑\s*", "", text)
    reason = re.sub(r"^\s*\d+\s*", "", reason).strip() if days else reason.strip()
    msg = await mute.blacklist_add(event, target, reason, days)
    await reply_text_md(event, msg)


@handler(r"^解除拉黑(?:\s*.*)?$", name="解除拉黑", desc="解除拉黑 @用户", priority=60, block=True)
async def cmd_unblacklist(event, match):
    target = _first_target(event)
    if not target:
        return await reply_text_md(event, "用法: @机器人 解除拉黑 @用户")
    msg = await mute.blacklist_remove(event, target)
    await reply_text_md(event, msg)


@handler(r"^(黑名单|拉黑列表)\s*$", name="黑名单", desc="查看黑名单", priority=60, block=True)
async def cmd_blacklist_list(event, match):
    msg = mute.blacklist_list(event)
    await reply_text_md(event, msg)


@handler(r"^撤回\s*$", name="撤回", desc="撤回消息", priority=60, block=True)
async def cmd_recall(event, match):
    msg = await mute.recall(event)
    await reply_text_md(event, msg)


# ========== 积分命令 ==========

@handler(r"^签到\s*$", name="签到", desc="每日签到", priority=60, block=True)
@_gid_handler
async def cmd_sign(event, match):
    if not cfg.get_feature("sign"):
        return await reply_text_md(event, "签到功能已关闭")
    ok, pts, streak, msg = points.sign(event)
    if ok:
        add_log(f"{_nickname(event)} 签到 +{pts} 连续{streak}天")
        total = points.get_points(str(event.user_id))
        sign_progress = "明日继续" if streak < 7 else "本周已满"
        await reply_card(event, "✅ 签到成功", items=[
            f"💰 积分 +{pts}",
            f"🔥 连续签到 {streak} 天 · {sign_progress}",
            f"📊 当前积分 {total}",
            f"💡 发送「我的」查看详细",
        ])
    else:
        await reply_text_md(event, msg)


@handler(r"^抽奖\s*$", name="抽奖", desc="积分抽奖", priority=60, block=True)
@_gid_handler
async def cmd_lottery(event, match):
    if not cfg.get_feature("lottery"):
        return await reply_text_md(event, "抽奖功能已关闭")
    gid = _gid(event)
    uid = str(event.user_id)
    ok_lim, reason, extra, warned = check_and_record_limit(gid, uid, "lottery", daily=5, cooldown=30)
    if not ok_lim:
        if reason == "cooldown":
            if not warned:
                return await reply_md(event, f"⏳ 抽奖操作太频繁，请 {extra} 秒后再试")
            await reply_md(event, "⏳ 太频繁啦，已禁言 2 分钟")
            await limit_mute(event, uid)
            return
        return await reply_md(event, "📅 抽奖今日次数已用完（每日 5 次）")
    ok, win, msg = points.lottery(event)
    if ok:
        add_log(f"{_nickname(event)} 抽奖 中{win}积分")
        total = points.get_points(uid)
        # 计算今日剩余抽奖次数
        try:
            from ..mod.reply import check_and_record_limit as _lim
            from ..mod.db import get_user
            meta = get_user("_meta") or {}
            dk = f"d:{gid}:{uid}:lottery:{time.strftime('%Y%m%d')}"
            used = int(meta.get(dk, 0) or 0)
            remain = max(0, 5 - used)
        except Exception:
            remain = "?"
        await reply_card(event, "🎉 中奖啦", items=[
            f"🎰 花费 20 积分",
            f"💰 获得 +{win} 积分",
            f"📊 当前积分 {total}",
            f"💡 中奖率 60%，今日剩余 {remain} 次",
        ])
    else:
        await reply_text_md(event, msg)


@handler(r"^发红包\s+(\d+)\s+(\d+)", name="发红包", desc="发红包 金额 份数", priority=60, block=True)
@_gid_handler
async def cmd_send_redpack(event, match):
    if not cfg.get_feature("redpack"):
        return await reply_text_md(event, "红包功能已关闭")
    total = int(match.group(1))
    cnt = int(match.group(2))
    rp_id = redpack.create_redpack(event, total, cnt)
    if not rp_id:
        return await reply_text_md(event, "积分不足或金额太小")
    add_log(f"{_nickname(event)} 发红包 {total}积分/{cnt}份")
    await reply_card(event, "🧧 红包已发", items=[
        f"金额：{total} 积分",
        f"份数：{cnt} 份",
        "发送 抢红包 领取",
    ])


@handler(r"^抢红包\s*$", name="抢红包", desc="抢红包", priority=60, block=True)
@_gid_handler
async def cmd_claim_redpack(event, match):
    if not cfg.get_feature("redpack"):
        return await reply_text_md(event, "红包功能已关闭")
    ok, amount, msg = redpack.claim_redpack(event)
    if ok:
        add_log(f"{_nickname(event)} 抢红包 +{amount}积分")
        total = points.get_points(str(event.user_id))
        await reply_card(event, "🧧 抢到红包", items=[
            f"金额：+{amount} 积分",
            f"当前积分：{total}",
        ])
    else:
        await reply_text_md(event, msg)


@handler(r"^红包列表\s*$", name="红包列表", desc="查看红包", priority=60, block=True)
@_gid_handler
async def cmd_redpack_list(event, match):
    msg = redpack.list_redpacks(event)
    await reply_text_md(event, msg)


@handler(r"^抢劫\s*$", name="抢劫", desc="抢劫 @用户", priority=60, block=True)
@_gid_handler
async def cmd_rob(event, match):
    if not cfg.get_feature("rob"):
        return await reply_text_md(event, "抢劫功能已关闭")
    gid = _gid(event)
    uid = str(event.user_id)
    ok_lim, reason, extra, warned = check_and_record_limit(gid, uid, "rob", daily=5, cooldown=30)
    if not ok_lim:
        if reason == "cooldown":
            if not warned:
                return await reply_md(event, f"⏳ 抢劫操作太频繁，请 {extra} 秒后再试")
            await reply_md(event, "⏳ 太频繁啦，已禁言 2 分钟")
            await limit_mute(event, uid)
            return
        return await reply_md(event, "📅 抢劫今日次数已用完（每日 5 次）")
    target = _first_target(event)
    if not target:
        return await reply_text_md(event, "用法: 抢劫 @用户 或 @用户 抢劫")
    ok, pts, msg = points.rob(event, target, target)
    if ok:
        add_log(f"{_nickname(event)} 抢劫 {target} +{pts}")
    await reply_text_md(event, msg)


@handler(r"^买反甲\s*$", name="买反甲", desc="购买反甲护盾", priority=60, block=True)
@_gid_handler
async def cmd_armor(event, match):
    ok, msg = points.buy_armor(event)
    if ok:
        add_log(f"{_nickname(event)} 购买反甲")
        total = points.get_points(str(event.user_id))
        await reply_card(event, "🛡 反甲已生效", items=[
            f"💰 花费 200 积分",
            f"📊 当前积分 {total}",
            f"⏱ 有效期 3 天",
            f"💡 抢劫你的人会被反弹扣分",
        ])
    else:
        await reply_md(event, msg)


@handler(r"^我的\s*$", name="我的", desc="查看积分信息", priority=60, block=True)
@_gid_handler
async def cmd_me(event, match):
    info = points.get_my_info(event)
    lines = [l for l in str(info).split("\n") if l]
    await reply_card(event, "📊 我的信息", items=lines)


@handler(r"^(积分排行|排行)\s*$", name="积分排行", desc="积分排行榜", priority=60, block=True)
@_gid_handler
async def cmd_rank(event, match):
    items = points.get_rank(event)
    if not items:
        return await reply_text_md(event, "暂无数据")
    lines = ["🏆 积分排行:"]
    for i, (uid, pts, nick) in enumerate(items[:15]):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
        lines.append(f"  {medal} {nick}: {pts}分")
    await reply_card(event, "🏆 积分排行", items=[
        f"{'🥇' if i==0 else '🥈' if i==1 else '🥉' if i==2 else str(i+1)+'.'} {nick_of(uid)}: {pts}分"
        for i, (uid, pts, nick) in enumerate(items[:15])
    ])


# ========== 互动命令 ==========

@handler(r"^塔罗牌\s*$", name="塔罗牌", desc="抽塔罗牌", priority=60, block=True)
async def cmd_tarot(event, match):
    if not cfg.get_feature("tarot"):
        return await reply_text_md(event, "塔罗牌功能已关闭")
    await reply_text_md(event, tarot.tarot(event))


@handler(r"^运势\s*$", name="运势", desc="每日运势", priority=60, block=True)
async def cmd_fortune(event, match):
    if not cfg.get_feature("fortune"):
        return await reply_text_md(event, "运势功能已关闭")
    await reply_text_md(event, tarot.fortune(event))


@handler(r"^今日人品\s*$", name="今日人品", desc="今日人品值", priority=60, block=True)
async def cmd_jrrp(event, match):
    if not cfg.get_feature("jrrp"):
        return await reply_text_md(event, "今日人品功能已关闭")
    await reply_text_md(event, tarot.jrrp(event))


@handler(r"^投票\s+(.+)$", name="投票", desc="投票 标题/选项1/选项2", priority=60, block=True)
async def cmd_vote(event, match):
    if not cfg.get_feature("vote"):
        return await reply_text_md(event, "投票功能已关闭")
    text = match.group(1).strip()
    parts = [p.strip() for p in text.split("/")]
    if len(parts) < 3:
        return await reply_text_md(event, "用法: 投票 标题/选项1/选项2/选项3")
    msg, rows = tarot.create_vote_buttons(event, parts[0], parts[1:])
    if rows:
        await event.reply(msg, buttons=rows)
    else:
        await reply_text_md(event, msg)


@handler(r"^vt:[A-Za-z0-9]+:\d+$", name="投票按钮", desc="投票选项回调",
         priority=5, block=True, event_types=('INTERACTION_CREATE',))
async def on_vote_button(event, match):
    """用户点击投票选项按钮: data 格式 vt:{vid}:{idx} → 直接投票"""
    uid = str(getattr(event, 'user_id', ''))
    try:
        vid, idx_s = str(match.group(0)).split(':')[1], str(match.group(0)).split(':')[2]
        idx = int(idx_s)
    except Exception:
        return
    msg = tarot.cast_vote(event, vid, idx)
    if msg:
        await event.reply(f"{prefix_at(event)}**{msg}**")
    else:
        await event.reply(f"{prefix_at(event)}❌ **投票失败**")


@handler(r"^投票结果(?:\s*([A-Za-z0-9]+))?$", name="投票结果", desc="查看投票结果", priority=60, block=True)
async def cmd_vote_result(event, match):
    vid = match.group(1) or None
    msg = tarot.vote_result(event, vid)
    await reply_text_md(event, msg)


# 投票数字选择: 单数字消息且本群有活跃投票时参与投票
@handler(r"^[1-9]$", name="参与投票", desc="数字参与投票", priority=40)
async def cmd_vote_cast(event, match):
    if not cfg.get_feature("vote"):
        return False
    choice = int(match.group(0))
    msg = tarot.cast_vote(event, None, choice)
    if msg:
        await reply_text_md(event, msg)
        return True
    return False


# ========== API命令 ==========

@handler(r"^天气\s*(.*)$", name="天气", desc="天气 城市", priority=60, block=True)
async def cmd_weather(event, match):
    if not cfg.get_feature("weather"):
        return await reply_text_md(event, "天气功能已关闭")
    city = match.group(1).strip() or "北京"
    msg = await api.weather(city)
    await reply_text_md(event, msg)


@handler(r"^热搜\s*$", name="热搜", desc="微博热搜", priority=60, block=True)
async def cmd_hot(event, match):
    if not cfg.get_feature("hot"):
        return await reply_text_md(event, "热搜功能已关闭")
    msg = await api.hot()
    await reply_text_md(event, msg)


@handler(r"^战力\s+(.+)$", name="战力", desc="战力 英雄名", priority=60, block=True)
async def cmd_wzry(event, match):
    if not cfg.get_feature("wzry"):
        return await reply_text_md(event, "战力功能已关闭")
    hero = match.group(1).strip()
    msg = await api.wzry(hero)
    await reply_text_md(event, msg)


@handler(r"^壁纸\s*$", name="壁纸", desc="随机壁纸", priority=60, block=True)
async def cmd_wallpaper(event, match):
    if not cfg.get_feature("wallpaper"):
        return await reply_text_md(event, "壁纸功能已关闭")
    ok = await api.wallpaper(event)
    if not ok:
        await reply_text_md(event, "壁纸获取失败")


@handler(r"^早报\s*$", name="早报", desc="每日新闻", priority=60, block=True)
async def cmd_news(event, match):
    if not cfg.get_feature("news"):
        return await reply_text_md(event, "早报功能已关闭")
    ok = await api.news(event)
    if not ok:
        await reply_text_md(event, "早报获取失败")


@handler(r"^摸鱼\s*$", name="摸鱼", desc="摸鱼日历", priority=60, block=True)
async def cmd_moyu(event, match):
    if not cfg.get_feature("moyu"):
        return await reply_text_md(event, "摸鱼功能已关闭")
    msg = await api.moyu()
    await reply_text_md(event, msg)


# ========== 作图娱乐（天迹云） ==========

def _img_target(event):
    """作图目标: 优先 @用户(s), 否则取命令后的QQ号, 否则用发送者"""
    items = get_mentions(event)
    if items:
        return items[0][0]
    text = _text(event)
    m = re.search(r"\d{5,}", text)
    return m.group(0) if m else str(event.user_id)


@handler(r"^单身狗(?:\s+.*)?$", name="单身狗", desc="单身狗 @用户/QQ", priority=60, block=True)
async def cmd_danshengou(event, match):
    target = _img_target(event)
    ok = await api.image_danshengou(event, target)
    if not ok:
        await reply_text_md(event, "配图生成失败")


@handler(r"^(?:马内|我想要马内)(?:\s+.*)?$", name="马内", desc="马内 @用户/QQ", priority=60, block=True)
async def cmd_manei(event, match):
    target = _img_target(event)
    ok = await api.image_manei(event, target)
    if not ok:
        await reply_text_md(event, "配图生成失败")


@handler(r"^装高手(?:\s+.*)?$", name="装高手", desc="装高手 @用户/QQ", priority=60, block=True)
async def cmd_gaoshou(event, match):
    target = _img_target(event)
    ok = await api.image_gaoshou(event, target)
    if not ok:
        await reply_text_md(event, "配图生成失败")


@handler(r"^小姐姐(?:\s*$)", name="小姐姐", desc="随机小姐姐视频", priority=60, block=True)
async def cmd_xiaojiejie(event, match):
    ok = await api.video_xiaojiejie(event)
    if not ok:
        await reply_text_md(event, "视频获取失败")


# ========== 点歌 ==========

_music_cache = {}

@handler(r"^点歌\s+(.+)$", name="点歌", desc="点歌 歌名", priority=60, block=True)
async def cmd_music(event, match):
    if not cfg.get_feature("music"):
        return await reply_text_md(event, "点歌功能已关闭")
    keyword = match.group(1).strip()
    uid = str(event.user_id)
    msg, rows = await api.music_search_buttons(keyword, uid, _music_cache)
    if rows:
        head = ""
        _u = uid
        if _u:
            head = prefix_at(event)
        await event.reply(head + msg, buttons=rows)
    else:
        await reply_text_md(event, msg)


@handler(r"^mg:[^:]+:\d+$", name="点歌按钮", desc="点歌歌曲选择回调",
         priority=5, block=True, event_types=('INTERACTION_CREATE',))
async def on_music_button(event, match):
    """用户点击点歌歌曲按钮: data 格式 mg:{uid}:{idx} → 直接播放"""
    uid = str(getattr(event, 'user_id', ''))
    try:
        mg_uid, idx_s = str(match.group(0)).split(':')[1], str(match.group(0)).split(':')[2]
        idx = int(idx_s)
    except Exception:
        return
    if mg_uid != uid:
        return
    info = _music_cache.get(uid, {})
    if not info.get('keyword'):
        return
    url, lyric = await api.music_play(event, info, idx)
    if lyric:
        await event.reply(f"{prefix_at(event)}{lyric}")
    # 歌曲名可展示 via lyric; 语音由 music_play 内部发送


@handler(r"^听(\d+)\s*$", name="听歌", desc="播放歌曲", priority=60, block=True)
async def cmd_music_play(event, match):
    idx = int(match.group(1))
    uid = str(event.user_id)
    info = _music_cache.get(uid, {})
    url, lyric = await api.music_play(event, info, idx)
    if lyric:
        await reply_text_md(event, lyric)


# ========== 豆包 AI 聊天（已按用户要求移除） ==========
# 保留占位说明: AI 模式已关闭，@机器人 不再触发豆包聊天