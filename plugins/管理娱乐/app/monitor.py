"""监控模块 — 违禁词过滤、刷屏检测、入群欢迎、黑名单拦截、入群验证。"""

import random
import re
import time
from collections import defaultdict

from core.plugin.decorators import interceptor, handler

from ..mod.db import (
    get_banned_words, get_welcome_msg, get_join_verify,
    get_blacklist, add_log,
)
from ..mod import mute as mute_mod
from ..mod import config as cfg
from ..mod.reply import prefix_at

_spam_records = defaultdict(list)  # {gid: [(uid, timestamp), ...]}
_join_verify_pending = {}          # {uid: {code, ts, tries}}
_verify_wait_secs = 300


# ========== 违禁词过滤 + 刷屏检测 ==========

@interceptor(priority=5)
async def filter_violation(event):
    """拦截违禁词和刷屏消息，执行阶梯惩罚"""
    et = getattr(event, 'event_type', '')
    if et != 'GROUP_MESSAGE_CREATE':
        return False

    gid = str(getattr(event, 'group_id', ''))
    uid = str(getattr(event, 'user_id', ''))
    if not gid or not uid:
        return False

    text = getattr(event, 'content', '') or getattr(event, 'message', '') or ''

    # 违禁词检测
    for w in get_banned_words():
        if w and w in text:
            await _handle_violation(event, gid, uid, f"违禁词: {w}")
            return True

    # 刷屏检测
    now = time.time()
    _spam_records[gid] = [(u, t) for u, t in _spam_records.get(gid, []) if now - t < cfg.SPAM_INTERVAL]
    _spam_records[gid].append((uid, now))
    same_user = [t for u, t in _spam_records[gid] if u == uid]
    if len(same_user) >= cfg.SPAM_COUNT:
        await _handle_violation(event, gid, uid, "刷屏")
        return True

    return False


@interceptor(priority=6)
async def filter_join_verify(event):
    """拦截未通过验证的新成员消息"""
    et = getattr(event, 'event_type', '')
    if et != 'GROUP_MESSAGE_CREATE':
        return False
    uid = str(getattr(event, 'user_id', ''))

    # 清理过期待验证用户
    now = time.time()
    v = get_join_verify()
    timeout = int(v.get('timeout', 300)) if v else 300
    for pending_uid, info in list(_join_verify_pending.items()):
        if now - info['ts'] > timeout:
            _join_verify_pending.pop(pending_uid, None)
            # 超时未验证 → 永久禁言(QQ官方无踢出)
            if v and v.get('enabled'):
                try:
                    await mute_mod.mute(event, pending_uid, 43200, "入群验证超时")
                    add_log(f"入群验证超时已禁言 {pending_uid}")
                except Exception:
                    pass

    if uid in _join_verify_pending:
        # 正在等待验证
        text = (getattr(event, 'content', '') or '').strip()
        info = _join_verify_pending[uid]
        # 按钮回传消息: jv:{uid}:{answer} → 直接验证 (旧方案兼容)
        if text.startswith('jv:'):
            try:
                parts = text.split(':')
                ans = parts[2] if len(parts) > 2 else ''
                ok = (ans == info['code'])
            except Exception:
                ok = False
            if ok:
                _join_verify_pending.pop(uid, None)
                # 撤回按钮回传的 jv 消息, 保持整洁
                try:
                    await mute_mod.recall(event)
                except Exception:
                    pass
                # 通过提示 + 欢迎语 融合为一条 (md)
                welcome = get_welcome_msg()
                nickname = getattr(event, 'user_name', '') or '新成员'
                group_name = getattr(event, 'group_name', '') or ''
                w_text = welcome.format(nickname=nickname, group_name=group_name) if welcome else ""
                if w_text:
                    merged = f"{prefix_at(event)}✅ **验证通过，欢迎入群！**\n{w_text}"
                else:
                    merged = f"{prefix_at(event)}✅ **验证通过，欢迎入群！**"
                try:
                    await event.reply(merged)
                except Exception:
                    pass
                return True
            # 按钮答错 → 扣次数并提示(不重发, 原按钮已点过)
            info['tries'] -= 1
            if info['tries'] <= 0:
                _join_verify_pending.pop(uid, None)
                try:
                    await mute_mod.mute(event, uid, 43200, "入群验证失败")
                    add_log(f"入群验证失败已禁言 {uid}")
                    await event.reply(f"{prefix_at(event)}❌ **验证失败次数过多，已禁言**")
                except Exception:
                    pass
            else:
                await event.reply(f"{prefix_at(event)}❌ **答案不对哦，还剩 {info['tries']} 次机会**")
            return True
        # 按模式校验: digits=数字验证码, math=数学计算结果
        expected = info['code']
        if info.get('mode') == 'math':
            # 数学题: 允许带空格/等号前缀
            t = re.sub(r'\s+', '', text).lstrip('=')
            ok = t == expected
        else:
            ok = text == expected
        if ok:
            # 验证通过
            _join_verify_pending.pop(uid, None)
            # 撤回验证消息(按钮自动发送的数字/验证码), 保持群整洁
            try:
                await mute_mod.recall(event)
            except Exception:
                pass
            # 通过提示 + 欢迎语 融合为一条 (md)
            welcome = get_welcome_msg()
            nickname = getattr(event, 'user_name', '') or '新成员'
            group_name = getattr(event, 'group_name', '') or ''
            w_text = welcome.format(nickname=nickname, group_name=group_name) if welcome else ""
            if w_text:
                merged = f"{prefix_at(event)}✅ **验证通过，欢迎入群！**\n{w_text}"
            else:
                merged = f"{prefix_at(event)}✅ **验证通过，欢迎入群！**"
            try:
                await event.reply(merged)
            except Exception:
                pass
            return False
        # 答错
        info['tries'] -= 1
        if info['tries'] <= 0:
            _join_verify_pending.pop(uid, None)
            try:
                await mute_mod.mute(event, uid, 43200, "入群验证失败")
                add_log(f"入群验证失败已禁言 {uid}")
                await event.reply(f"{prefix_at(event)}❌ **验证失败次数过多，已禁言**")
            except Exception:
                pass
        else:
            prompt = f"请回复验证码: **{info['code']}**" if info.get('mode') != 'math' else f"请回复算式结果（数字）"
            await event.reply(f"🔒 **验证不正确，还剩 {info['tries']} 次机会**\n{prompt}")
        return True
    return False


# ========== 入群事件 ==========

@handler(r"^jv:[^:]+:\d+$", name="验证按钮", desc="入群验证按钮回调",
         priority=5, block=True, event_types=('INTERACTION_CREATE',))
async def on_verify_button(event, match):
    """用户点击入群验证按钮: data 格式 jv:{uid}:{answer}"""
    uid = str(getattr(event, 'user_id', ''))
    add_log(f"验证按钮回调 content={getattr(event, 'content', '')!r} uid={uid}")
    try:
        jv_uid, answer = str(match.group(0)).split(':')[1], str(match.group(0)).split(':')[2]
    except Exception:
        return
    # 确认是给自己发的验证按钮
    if jv_uid != uid:
        return
    if uid not in _join_verify_pending:
        return
    info = _join_verify_pending[uid]
    if info.get('mode') != 'math':
        return

    if answer == info['code']:
        _join_verify_pending.pop(uid, None)
        # 撤回验证消息(带按钮的那条)
        try:
            i_data = getattr(event, 'interaction_data', None) or {}
            resolved = (i_data.get('data', {}) or {}).get('resolved', {}) or {}
            vmsg_id = resolved.get('message_id', '') or ''
            if vmsg_id:
                await mute_mod.recall(event, message_id=vmsg_id)
        except Exception:
            pass
        # 通过提示 + 欢迎语 融合为一条 (md) + @新成员识别
        welcome = get_welcome_msg() or ""
        try:
            gid = str(getattr(event, 'group_id', ''))
            nickname = getattr(event, 'user_name', '') or '新成员'
            group_name = getattr(event, 'group_name', '') or ''
            w_text = welcome.format(nickname=nickname, group_name=group_name) if welcome else ""
            if w_text:
                merged = f"{prefix_at(event)}✅ **验证通过，欢迎入群！**\n{w_text}"
            else:
                merged = f"{prefix_at(event)}✅ **验证通过，欢迎入群！**"
            await _send_group_msg(event, gid, merged)
        except Exception:
            pass
    else:
        info['tries'] -= 1
        if info['tries'] <= 0:
            _join_verify_pending.pop(uid, None)
            try:
                await mute_mod.mute(event, uid, 43200, "入群验证失败")
                add_log(f"入群验证失败已禁言 {uid}")
                await event.reply(f"{prefix_at(event)}❌ **验证失败次数过多，已禁言**")
            except Exception:
                pass
        else:
            try:
                await event.reply(f"{prefix_at(event)}❌ **答案不对哦，还剩 {info['tries']} 次机会**")
            except Exception:
                pass
            # 重新出题发新按钮 (保证有正确选项可点)
            try:
                gid = str(getattr(event, 'group_id', ''))
                a2 = random.randint(10, 99)
                b2 = random.randint(1, 9)
                op2 = random.choice(['+', '-'])
                if op2 == '-':
                    if a2 < b2:
                        a2, b2 = b2, a2
                    expr2 = f"{a2} - {b2}"
                    ans2 = a2 - b2
                else:
                    expr2 = f"{a2} + {b2}"
                    ans2 = a2 + b2
                wrongs2 = set()
                while len(wrongs2) < 3:
                    cand = ans2 + random.choice([-3, -2, -1, 1, 2, 3])
                    if cand != ans2 and cand >= 0 and cand not in wrongs2:
                        wrongs2.add(cand)
                opts2 = [ans2] + list(wrongs2)
                random.shuffle(opts2)
                rows2 = []
                for i in range(0, 4, 2):
                    row2 = []
                    for opt in opts2[i:i+2]:
                        row2.append({"text": f"{expr2} = {opt}",
                                     "action": {"type": 1, "data": f"jv:{uid}:{opt}",
                                                "permission": {"type": 2}},
                                     "limit": 1})
                    rows2.append(row2)
                info['code'] = str(ans2)
                info['expr'] = expr2
                content2 = f"🔢 重新出题：请点击正确的计算结果 **{expr2} = ?**"
                await event.reply(content2, buttons=rows2)
            except Exception:
                pass


async def _send_group_msg(event, gid, text):
    """向群主动推送消息（事件上下文 reply 不可靠时兜底）"""
    try:
        sender = event.sender
        return await sender.send_to_group(gid, text)
    except Exception:
        try:
            return await event.reply(text)
        except Exception:
            return None


@handler(r".*", name="入群处理", desc="入群欢迎/黑名单拦截", priority=10,
         event_types=('GROUP_MEMBER_ADD',), block=True)
async def on_member_add(event, match):
    gid = str(getattr(event, 'group_id', ''))
    uid = str(getattr(event, 'user_id', ''))
    if not gid or not uid:
        return
    add_log(f"新成员入群 {uid} -> {gid}")

    # 黑名单拦截 (QQ官方无踢出接口 → 永久禁言)
    bl = get_blacklist(gid)
    info = bl.get(uid)
    if info:
        expire = info.get('expire', 0)
        if expire == 0 or expire > time.time():
            try:
                await mute_mod.mute(event, uid, 43200, "黑名单成员")
                add_log(f"黑名单成员入群已禁言 {uid}")
            except Exception:
                pass
            return

    # 入群验证
    v = get_join_verify()
    if v and v.get('enabled'):
        mode = v.get('mode', 'digits')
        uid_now = uid
        if mode == 'math':
            # 数学计算验证(按钮): 随机两位内加减 + 4个答案按钮(1个正确3个干扰)
            a = random.randint(10, 99)
            b = random.randint(1, 9)
            op = random.choice(['+', '-'])
            if op == '-':
                if a < b:
                    a, b = b, a
                expr = f"{a} - {b}"
                answer = a - b
            else:
                expr = f"{a} + {b}"
                answer = a + b
            # 生成3个干扰答案(与正确答案不重复, 无负数)
            wrongs = set()
            while len(wrongs) < 3:
                cand = answer + random.choice([-3, -2, -1, 1, 2, 3])
                if cand != answer and cand >= 0 and cand not in wrongs:
                    wrongs.add(cand)
            options = [answer] + list(wrongs)
            random.shuffle(options)
            # 按钮: type=1 纯回调按钮 (点击只触发 INTERACTION_CREATE 回调, 不填输入框不发消息)
            # data 携带 验证标记+uid+答案 → on_verify_button 收到回调后直接验证
            button_rows = []
            for i in range(0, 4, 2):
                row_btns = []
                for opt in options[i:i+2]:
                    row_btns.append({
                        "text": f"{expr} = {opt}",
                        "action": {"type": 1, "data": f"jv:{uid_now}:{opt}",
                                   "permission": {"type": 2}},
                        "limit": 1,
                    })
                button_rows.append(row_btns)
            pending = {"code": str(answer), "ts": time.time(),
                       "tries": max(1, int(v.get('tries', 3) or 3)), "mode": "math",
                       "expr": expr}
            _join_verify_pending[uid] = pending
            try:
                content = f"🔢 入群验证：请点击下方正确的计算结果 **{expr} = ?**\n（{_verify_wait_secs}秒内有效）"
                await event.reply(content, buttons=button_rows)
            except Exception:
                # 按钮发送失败回退文字输入
                await _send_group_msg(event, gid, f"🔢 入群验证：请计算 **{expr} = ?** 并回复数字结果\n（{_verify_wait_secs}秒内有效）")
            add_log(f"入群验证(math-按钮)已发送 {uid}")
            return
        else:
            digits = max(3, min(8, int(v.get('digits', 4) or 4)))
            code = ''.join(random.choices('0123456789', k=digits))
            prompt = f"🔒 入群验证：请回复数字验证码 **{code}**\n（{_verify_wait_secs}秒内有效）"
            pending = {"code": code, "ts": time.time(),
                       "tries": max(1, int(v.get('tries', 3) or 3)), "mode": "digits"}
        _join_verify_pending[uid] = pending
        await _send_group_msg(event, gid, prompt)
        add_log(f"入群验证({mode})已发送 {uid}")
        return

    # 欢迎语
    welcome = get_welcome_msg()
    if welcome:
        nickname = getattr(event, 'user_name', '') or '新成员'
        group_name = getattr(event, 'group_name', '')
        await _send_group_msg(event, gid, welcome.format(nickname=nickname, group_name=group_name))


@handler(r".*", name="入群审批", desc="入群申请处理", priority=10,
         event_types=('GROUP_JOIN_REQUEST',), block=True)
async def on_join_request(event, match):
    """入群申请：黑名单用户拒绝，其余通过"""
    gid = str(getattr(event, 'group_id', ''))
    uid = str(getattr(event, 'user_id', ''))
    req_id = getattr(event, 'join_request_id', '')
    if not gid or not uid:
        return

    join_verify = get_join_verify()
    if not join_verify.get('enabled'):
        return  # 未启用审批，交给管理员

    # 黑名单拒绝
    bl = get_blacklist(gid)
    if uid in bl:
        try:
            sender = event.sender
            await sender.review_group_join_request(
                gid, uid, "decline",
                join_request_id=req_id,
                reject_reason="黑名单用户",
            )
            add_log(f"拒绝入群申请 {uid} (黑名单)")
        except Exception:
            pass
        return

    try:
        sender = event.sender
        await sender.review_group_join_request(
            gid, uid, "approve", join_request_id=req_id,
        )
        add_log(f"通过入群申请 {uid}")
    except Exception as e:
        add_log(f"入群审批失败 {uid}: {e}")


# ========== 违规处理 ==========

async def _handle_violation(event, gid, uid, reason):
    level, penalty = mute_mod.add_violation(gid, uid)

    if level == 'warn':
        recall_msg = await mute_mod.recall(event)
        try:
            await event.reply(f"⚠️ **{reason}** - 警告！请遵守群规（{recall_msg}）")
        except Exception:
            pass
    elif level == 'mute':
        recall_msg = await mute_mod.recall(event)
        mute_msg = await mute_mod.mute(event, uid, penalty, reason)
        try:
            await event.reply(f"🔇 **{reason}** - {mute_msg}")
        except Exception:
            pass
    elif level == 'kick':
        # QQ官方无踢出接口: 永久禁言30天 + 记黑名单
        recall_msg = await mute_mod.recall(event)
        mute_msg = await mute_mod.mute(event, uid, 43200, reason)
        bl_msg = await mute_mod.blacklist_add(event, uid, reason)
        try:
            await event.reply(f"🚫 **{reason}** - {mute_msg} | {bl_msg}")
        except Exception:
            pass

    add_log(f"违规 {reason} {uid} 等级:{level}")


async def start():
    """生命周期占位（事件已由装饰器注册）"""
    pass


async def stop():
    _spam_records.clear()
    _join_verify_pending.clear()