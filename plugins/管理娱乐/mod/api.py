"""API模块 — 天气、热搜、战力、壁纸、早报、摸鱼、点歌。"""

import asyncio
import urllib.parse
from collections import OrderedDict
from core.network.http_compat import AsyncHttpClient

_client = None
_cache = OrderedDict()
_CACHE_CAP = 100
_STRIP_TBL = str.maketrans("", "", "\"'<>&*_~`[](){}\\/:")
_BASE = "https://gulangsc.cn/API"


async def _http():
    global _client
    if _client is None or _client.is_closed:
        _client = AsyncHttpClient(timeout=15.0)
    return _client


async def _reopen():
    """连接异常时重建 HTTP 客户端 (清除失效的 keep-alive 连接)"""
    global _client
    try:
        if _client is not None and not _client.is_closed:
            await _client.aclose()
    except Exception:
        pass
    _client = AsyncHttpClient(timeout=15.0)
    return _client


async def _get(url):
    """GET + 重试 (TLS EOF / 瞬时网络错误自动重试, 连接异常时重建客户端)"""
    last_exc = None
    for attempt in range(3):
        try:
            c = await _http()
            resp = await c.get(url)
            if resp.status_code == 200:
                return resp.json()
            last_exc = Exception(f"HTTP {resp.status_code}")
        except Exception as e:
            last_exc = e
            # TLS/连接错误 → 重建客户端
            try:
                await _reopen()
            except Exception:
                pass
        await asyncio.sleep(0.8 * (attempt + 1))
    raise last_exc if last_exc else Exception("GET 失败")


# ========== 天气 ==========
async def weather(city: str = "北京") -> str:
    try:
        d = await _get(f"{_BASE}/tianqi/tianqi.php?city={urllib.parse.quote(city)}")
        return (
            f"🌤 {d.get('city', city)} {d.get('weather', '')} {d.get('temperature', '')}℃\n"
            f"💨 {d.get('wind_direction', '')} {d.get('wind_power', '')}\n"
            f"💧 湿度 {d.get('humidity', '')}%\n"
            f"📡 {d.get('report_time', '')}"
        )
    except Exception:
        return "天气查询失败"


# ========== 热搜 ==========
async def hot() -> str:
    try:
        d = await _get(f"{_BASE}/hot/hot.php?type=weibo")
        items = d.get("data", [])[:10]
        lines = ["🔥 微博热搜:"]
        for i, item in enumerate(items):
            lines.append(f"  {i+1}. {item.get('title', '')}")
        return "\n".join(lines)
    except Exception:
        return "热搜查询失败"


# ========== 王者战力 ==========
async def wzry(hero: str) -> str:
    try:
        d = await _get(f"{_BASE}/wzry_rank/wzry_rank.php?hero={urllib.parse.quote(hero)}&server=android_qq")
        if d.get("code") != 200:
            return f"查询失败: {d.get('msg', '')}"
        data = d["data"]
        r = data.get("rank_info", {})
        return (
            f"⚔️ {data.get('hero_name', hero)} {data.get('server_name', '')}\n"
            f"🏆 国标: {r.get('national', {}).get('min_power', '?')}分\n"
            f"🥇 省标: {r.get('province', {}).get('area', '')} {r.get('province', {}).get('min_power', '?')}分\n"
            f"🥈 市标: {r.get('city', {}).get('area', '')} {r.get('city', {}).get('min_power', '?')}分\n"
            f"🥉 县标: {r.get('county', {}).get('area', '')} {r.get('county', {}).get('min_power', '?')}分"
        )
    except Exception:
        return "战力查询失败"


# ========== 接口文档与密钥 ==========
# 接口文档: https://gulangsc.cn/doc  (天迹云开放平台, 登录后获取自己的 apikey)
# 密钥配置: Web面板「接口密钥」页 或 data/config.json 的 api_keys 字段
#   api_keys.gulangsc = 你的天迹云 apikey (用于 装高手/单身狗/马内/小姐姐 等作图接口)
_DOC_URL = "https://gulangsc.cn/doc"


def _api_key(name: str) -> str:
    """从配置取接口密钥; 未配置返回空串"""
    try:
        from . import config as _cfg
        keys = (_cfg.get_config() or {}).get("api_keys") or {}
        return str(keys.get(name, "") or "")
    except Exception:
        return ""


def _keyed_url(base: str) -> str:
    """给 URL 附加 apikey 参数 (密钥来自配置 api_keys.gulangsc, 未配置则省略)"""
    key = _api_key("gulangsc")
    sep = "&" if "?" in base else "?"
    if key:
        return f"{base}{sep}apikey={urllib.parse.quote(key)}"
    return base


# ========== 壁纸 ==========
async def wallpaper(event) -> bool:
    for attempt in range(3):
        try:
            c = await _http()
            resp = await c.get(f"{_BASE}/img/img.php")
            img_data = resp.content
            if resp.status_code == 200 and img_data:
                sender = event.sender
                await sender.reply_image(event, img_data)
                return True
        except Exception:
            try:
                await _reopen()
            except Exception:
                pass
        await asyncio.sleep(0.8 * (attempt + 1))
    return False


async def _gen_image(event, path: str, param: str, value: str) -> bool:
    """通用作图 API（天迹云 zt 系列）+ 重试 (TLS EOF/瞬时网络错误)"""
    url = _keyed_url(f"{_BASE}/{path}?{param}={urllib.parse.quote(value)}")
    for attempt in range(3):
        try:
            c = await _http()
            resp = await c.get(url)
            img_data = resp.content
            if resp.status_code == 200 and img_data and len(img_data) >= 1000:
                if img_data[:4].lower().startswith((b"\x89png", b"\xff\xd8", b"gif8")):
                    sender = event.sender
                    await sender.reply_image(event, img_data)
                    return True
        except Exception:
            try:
                await _reopen()
            except Exception:
                pass
        await asyncio.sleep(0.8 * (attempt + 1))
    return False


async def image_danshengou(event, qq: str) -> bool:
    return await _gen_image(event, "zt/dsg.php", "qq", qq)


async def image_manei(event, qq: str) -> bool:
    return await _gen_image(event, "zt/yao.php", "qq", qq)


async def image_gaoshou(event, qq: str) -> bool:
    return await _gen_image(event, "zt/z.php", "qq", qq)


async def video_xiaojiejie(event) -> bool:
    """小姐姐短视频"""
    for attempt in range(3):
        try:
            c = await _http()
            resp = await c.get(_keyed_url(f"{_BASE}/ksvideo/ksvideo.php"))
            video_data = resp.content
            if resp.status_code == 200 and video_data and len(video_data) >= 10000:
                sender = event.sender
                await sender.reply_video(event, video_data)
                return True
        except Exception:
            try:
                await _reopen()
            except Exception:
                pass
        await asyncio.sleep(0.8 * (attempt + 1))
    return False


# ========== 早报 ==========
async def news(event) -> bool:
    for attempt in range(3):
        try:
            c = await _http()
            resp = await c.get("https://uapis.cn/api/v1/daily/news-image")
            img_data = resp.content
            if resp.status_code == 200 and img_data:
                sender = event.sender
                await sender.reply_image(event, img_data)
                return True
        except Exception:
            try:
                await _reopen()
            except Exception:
                pass
        await asyncio.sleep(0.8 * (attempt + 1))
    return False


# ========== 摸鱼 ==========
_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
_MOYU_QUOTES = [
    "今天也是摸鱼的一天~",
    "上班不摸鱼，人生没意义",
    "摸鱼一时爽，一直摸鱼一直爽",
    "老板：今天辛苦一下。我：好的（然后开始摸鱼）",
    "工作可以慢慢做，鱼不能不摸",
    "今天的工作：假装很忙",
    "摸鱼使我快乐，快乐使我摸鱼",
    "薪水是老板给的，时间是自己的",
]

async def moyu() -> str:
    try:
        import datetime
        now = datetime.datetime.now()
        wd = _WEEKDAYS[now.weekday()]
        # 距周末天数
        days_to_weekend = 5 - now.weekday() if now.weekday() < 5 else 0
        # 计算距周五距离（最期待）
        if now.weekday() < 5:
            target = datetime.datetime(now.year, now.month, now.day) + datetime.timedelta(days=5 - now.weekday())
            diff = target - now
            hours = int(diff.total_seconds() // 3600)
            mins = int(diff.total_seconds() % 3600 // 60)
            weekend_info = f"距周五下班约 {hours}小时{mins}分"
        else:
            weekend_info = "今天是周末！好好休息~"

        import random
        quote = random.choice(_MOYU_QUOTES)
        return (
            f"🐟 摸鱼办日报\n"
            f"📅 {now.year}年{now.month}月{now.day}日 {wd}\n"
            f"⏰ {weekend_info}\n"
            f"💬 {quote}"
        )
    except Exception:
        return "摸鱼查询失败"


# ========== 点歌 ==========

_MUSIC_API = "https://a.aa.cab/qq.music"
_MUSIC_COVER_SIZE = 48
_MUSIC_STRIP_TBL = str.maketrans("", "", "\"'<>&*_~`[](){}\\/:")


def _music_cover(song: dict) -> str:
    cover = song.get("cover", "") or ""
    if cover:
        return f"![img #{_MUSIC_COVER_SIZE}px #{_MUSIC_COVER_SIZE}px]({cover})"
    return f"![img #{_MUSIC_COVER_SIZE}px #{_MUSIC_COVER_SIZE}px](https://y.gtimg.cn/music/photo_new/T002R500x500M000004JsGFf1t3eY.jpg)"


async def _music_api(params: str):
    """请求 a.aa.cab 音乐接口，返回 data 字段 (带重试: TLS EOF 等瞬时错误)"""
    last_exc = None
    for attempt in range(3):
        try:
            c = await _http()
            resp = await c.get(f"{_MUSIC_API}?{params}")
            if resp.status_code != 200:
                last_exc = Exception(f"HTTP {resp.status_code}")
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
            body = resp.json()
            return (body or {}).get("data")
        except Exception as e:
            last_exc = e
            try:
                await _reopen()
            except Exception:
                pass
            await asyncio.sleep(0.8 * (attempt + 1))
    raise last_exc if last_exc else Exception("音乐接口失败")


async def music_search(keyword: str, uid: str, cache: dict) -> str:
    """搜索歌曲，返回带封面缩略图的列表"""
    cache[uid] = {"keyword": keyword, "count": 0}
    try:
        songs = await _music_api(f"msg={urllib.parse.quote(keyword)}")
    except Exception as e:
        return f"点歌失败: {e}"

    if not isinstance(songs, list) or not songs:
        return "未找到歌曲"

    count = min(len(songs), 10)
    cache[uid]["count"] = count

    lines = ["🎵 搜索结果:", ""]
    for i, song in enumerate(songs[:count]):
        name = song.get("song", "未知").translate(_MUSIC_STRIP_TBL).strip()[:50]
        singer = song.get("singer", "").translate(_MUSIC_STRIP_TBL).strip()[:30]
        lines.append(f"{_music_cover(song)} {i+1}. {name} — {singer}")

    lines.append("")
    lines.append("回复 听序号 播放歌曲+歌词")
    return "\n".join(lines)


async def music_search_buttons(keyword: str, uid: str, cache: dict):
    """搜索歌曲，返回 (md文本, t1按钮行)。按钮 data = mg:{uid}:{idx}

    点击歌曲按钮 → INTERACTION_CREATE 回调 → on_music_button 播放
    """
    cache[uid] = {"keyword": keyword, "count": 0}
    try:
        songs = await _music_api(f"msg={urllib.parse.quote(keyword)}")
    except Exception as e:
        return f"点歌失败: {e}", None

    if not isinstance(songs, list) or not songs:
        return "未找到歌曲", None

    count = min(len(songs), 10)
    cache[uid]["count"] = count

    lines = ["🎵 点歌结果:", ""]
    for i, song in enumerate(songs[:count]):
        name = song.get("song", "未知").translate(_MUSIC_STRIP_TBL).strip()[:30]
        singer = song.get("singer", "").translate(_MUSIC_STRIP_TBL).strip()[:20]
        lines.append(f"  {i+1}. {name} — {singer}")

    lines.append("")
    lines.append("**点击下方歌曲按钮直接播放**")

    # t1 回调按钮: 每行2个, 最多10首 (5行)
    button_rows = []
    for i in range(0, count, 2):
        row = []
        for j in range(i, min(i + 2, count)):
            song = songs[j]
            name = (song.get("song", "未知").translate(_MUSIC_STRIP_TBL).strip()[:14] or f"歌曲{j+1}")
            row.append({
                "text": f"{j+1}. {name}",
                "action": {"type": 1, "data": f"mg:{uid}:{j+1}",
                           "permission": {"type": 2}},
                "limit": 1,
            })
        button_rows.append(row)

    return "\n".join(lines), button_rows


async def music_play(event, cache_data: dict, idx: int) -> tuple:
    """播放歌曲并返回歌词文本，返回 (语音URL, 歌词消息)"""
    info = cache_data or {}
    keyword = info.get("keyword", "")
    count = info.get("count", 0)
    if not keyword or idx < 1 or idx > count:
        return None, "序号无效，请先点歌"

    try:
        data = await _music_api(f"msg={urllib.parse.quote(keyword)}&n={idx}")
    except Exception:
        return None, "网络请求超时"

    music_url = (data or {}).get("music")
    if not music_url:
        return None, "未获取到歌曲链接，换一首试试"

    song_name = (data or {}).get("song", "")
    singer = (data or {}).get("singer", "")

    # 发送语音
    try:
        sender = event.sender
        await sender.reply_voice(event, music_url)
    except Exception:
        pass

    # 获取歌词（用歌名+歌手在 gulangsc 取）
    lyric_msg = await _fetch_lyric(song_name, singer)
    return music_url, lyric_msg


async def _fetch_lyric(song_name: str, singer: str) -> str:
    """获取歌词文本"""
    if not song_name:
        return ""
    try:
        query = f"{song_name} {singer}".strip()
        c = await _http()
        resp = await c.get(
            f"{_BASE}/music/qq_music.php?msg={urllib.parse.quote(query)}"
        )
        data = resp.json()
        if isinstance(data, list):
            song = data[0] if data else {}
        elif isinstance(data, dict) and data.get("name"):
            song = data
        else:
            song = {}
        lyric = (song.get("lyric") or {}).get("text", "")
        if not lyric:
            return f"📝 {song_name} — {singer}\n\n(暂无歌词)"
        import re
        lines = []
        skip_prefixes = ("[ti:", "[ar:", "[al:", "[by:", "[offset:",
                         "词：", "曲：", "编曲", "制作人", "合声", "吉他",
                         "贝斯", "鼓：", "录音", "混音", "母带", "OP：", "SP：",
                         "钢琴", "弦乐", "和声", "监制", "出品")
        title_skip = False
        for l in lyric.split("\n"):
            clean = re.sub(r"\[\d+:\d+(?:\.\d+)?\]", "", l).strip()
            if not clean:
                continue
            lower = clean.lower()
            if clean.startswith(skip_prefixes) or lower.startswith(skip_prefixes):
                continue
            # 跳过歌曲标题行（如 "晴天 - 周杰伦 (Jay Chou)"）
            if not title_skip and "-" in clean and singer and singer in clean and len(clean) < 40:
                title_skip = True
                continue
            lines.append(clean)
        text = "\n".join(lines[:20])
        if not text:
            text = "(暂无歌词)"
        return f"📝 {song_name} — {singer}\n\n{text}"
    except Exception:
        return f"📝 {song_name} — {singer}\n\n(歌词获取失败)"