"""管理娱乐插件 — 群管 + 娱乐 + Web后台。"""

__plugin_meta__ = {
    "name": "管理娱乐",
    "author": "AI",
    "description": "群管(禁言/黑名单/违禁词/入群验证) + 娱乐(签到/抽奖/红包/抢劫/塔罗牌/点歌/天气等) + Web后台",
    "version": "1.0.0",
}

import os
from core.base.logger import PLUGIN, get_logger
from core.plugin.decorators import on_load, on_unload
from core.plugin.web_pages import register_page, unregister_page

from .app import commands, webpanel, monitor
from .mod.config import load_config, save_config
from .mod.db import init_db

log = get_logger(PLUGIN, "管理娱乐")
_PANEL_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "panel.html")
_PAGE_KEY = "superadmin"
_ICON = (
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 '
    '0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>'
)


@on_load
async def _init():
    init_db()
    load_config()
    register_page(key=_PAGE_KEY, label="管理娱乐", source="plugin",
                  source_name="superadmin", icon=_ICON, html_file=_PANEL_HTML)
    webpanel.register_routes()
    await monitor.start()
    log.info("管理娱乐插件已加载")


@on_unload
async def _unload():
    await monitor.stop()
    unregister_page(_PAGE_KEY)
    webpanel.unregister_routes()
    log.info("管理娱乐插件已卸载")