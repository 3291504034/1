"""塔罗牌 + 运势 + 今日人品 + 投票。"""

import random
import time
import uuid

from .db import get_votes, set_votes, get_user, set_user
from . import config

_TAROT_CARDS = [
    ("愚者", "冒险、自由、新的开始"),
    ("魔术师", "创造力、技能、自信"),
    ("女祭司", "直觉、神秘、内在智慧"),
    ("皇后", "丰饶、母性、自然"),
    ("皇帝", "权威、结构、控制"),
    ("教皇", "传统、信仰、指导"),
    ("恋人", "爱情、和谐、选择"),
    ("战车", "意志力、胜利、决心"),
    ("力量", "勇气、耐心、内在力量"),
    ("隐者", "内省、孤独、寻求真理"),
    ("命运之轮", "命运、转折点、周期"),
    ("正义", "公平、真理、因果"),
    ("倒吊人", "牺牲、放手、新视角"),
    ("死神", "结束、转变、重生"),
    ("节制", "平衡、适度、和谐"),
    ("恶魔", "欲望、束缚、物质主义"),
    ("高塔", "突变、崩塌、觉醒"),
    ("星星", "希望、灵感、宁静"),
    ("月亮", "恐惧、幻觉、潜意识"),
    ("太阳", "快乐、成功、活力"),
    ("审判", "觉醒、重生、召唤"),
    ("世界", "完成、圆满、旅行"),
]

_FORTUNE_COMMENTS = [
    "大吉！今天适合摸鱼",
    "吉！财源滚滚",
    "中吉，今天会有好事发生",
    "小吉，平淡是福",
    "末吉，低调行事",
    "凶，今天不宜出门",
    "大凶！建议请假",
]

_JRRP_COMMENTS = [
    "人品爆表！", "快去买彩票！", "今天你最大",
    "不错不错", "还行", "一般般",
    "有点低啊", "今天小心点", "建议别出门",
    "人品欠费了", "你今天完了",
]

# 每群当前活跃投票 {gid: vid}
_active_votes = {}


def tarot(event) -> str:
    """抽塔罗牌"""
    card, meaning = random.choice(_TAROT_CARDS)
    return config.REPLIES.get("tarot", "🃏 {card}\n{meaning}").format(
        nickname=getattr(event, "user_name", ""), card=card, meaning=meaning
    )


def fortune(event) -> str:
    """每日运势"""
    score = random.randint(1, 100)
    idx = min(score // 15, len(_FORTUNE_COMMENTS) - 1)
    luck = _FORTUNE_COMMENTS[idx]
    return config.REPLIES.get("fortune", "🔮 {score}分 {luck}").format(
        nickname=getattr(event, "user_name", ""), score=score, luck=luck
    )


def jrrp(event) -> str:
    """今日人品"""
    score = random.randint(0, 100)
    idx = min(score // 10, len(_JRRP_COMMENTS) - 1)
    comment = _JRRP_COMMENTS[idx]
    return config.REPLIES.get("jrrp", "🍀 {score}分 {comment}").format(
        nickname=getattr(event, "user_name", ""), score=score, comment=comment
    )


def create_vote(event, title: str, options: list) -> str:
    """创建投票（每群同时一个活跃投票）"""
    gid = str(getattr(event, "group_id", "0"))
    vid = uuid.uuid4().hex[:6]
    votes = get_votes(gid)
    votes[vid] = {
        "title": title,
        "options": options,
        "votes": {opt: [] for opt in options},
        "deadline": time.time() + 300,
        "creator": str(event.user_id),
    }
    set_votes(gid, votes)
    _active_votes[gid] = vid

    opts = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])
    return f"📊 投票: {title}\n{opts}\n回复数字投票，每人一票，5分钟后截止"


def create_vote_buttons(event, title: str, options: list):
    """创建投票并返回 (md文本, t1按钮行)。按钮 data = vt:{vid}:{idx}

    点击选项按钮 → INTERACTION_CREATE 回调 → on_vote_button 投票
    """
    gid = str(getattr(event, "group_id", "0"))
    vid = uuid.uuid4().hex[:6]
    votes = get_votes(gid)
    votes[vid] = {
        "title": title,
        "options": options,
        "votes": {opt: [] for opt in options},
        "deadline": time.time() + 300,
        "creator": str(event.user_id),
    }
    set_votes(gid, votes)
    _active_votes[gid] = vid

    lines = [f"📊 **投票: {title}**", ""]
    for i, opt in enumerate(options):
        lines.append(f"  {i+1}. {opt}")
    lines.append("")
    lines.append("**点击下方选项按钮投票，每人一票，5分钟后截止**")

    button_rows = []
    for i in range(0, len(options), 2):
        row = []
        for j in range(i, min(i + 2, len(options))):
            opt = options[j]
            label = str(opt)[:16]
            row.append({
                "text": f"{j+1}. {label}",
                "action": {"type": 1, "data": f"vt:{vid}:{j+1}",
                           "permission": {"type": 2}},
                "limit": 1,
            })
        button_rows.append(row)

    return "\n".join(lines), button_rows


def cast_vote(event, vid, choice: int) -> str:
    """投票；vid 为空时投本群活跃投票"""
    gid = str(getattr(event, "group_id", "0"))
    uid = str(event.user_id)
    votes = get_votes(gid)

    if not vid:
        vid = _active_votes.get(gid)
    if not vid:
        return ""
    v = votes.get(vid)
    if not v:
        return "投票不存在或已结束"
    if time.time() > v["deadline"]:
        return "投票已截止"

    # 每人固定一票: 已投过不再允许 (无论是否改投)
    for opt, users in v["votes"].items():
        if uid in users:
            set_votes(gid, votes)
            return f"⛔ 你已经投过票了（{opt}）"

    if 1 <= choice <= len(v["options"]):
        opt = v["options"][choice - 1]
        v["votes"][opt].append(uid)
        set_votes(gid, votes)
        return f"✅ 已投票: {opt}"
    return ""


def vote_result(event, vid: str = None) -> str:
    """投票结果"""
    gid = str(getattr(event, "group_id", "0"))
    if not vid:
        vid = _active_votes.get(gid)
    if not vid:
        return "当前群没有进行中的投票"
    votes = get_votes(gid)
    v = votes.get(vid)
    if not v:
        return "投票不存在"

    results = []
    total = sum(len(u) for u in v["votes"].values())
    for opt, users in v["votes"].items():
        cnt = len(users)
        bar = "█" * min(cnt, 10) if total > 0 else ""
        results.append(f"{opt}: {bar} {cnt}票")

    winner = max(v["votes"].items(), key=lambda x: len(x[1]))[0]
    return config.REPLIES.get("vote_result", "📊 {title}\n{results}\n🏆 {winner}").format(
        title=v["title"], results="\n".join(results), winner=winner
    )