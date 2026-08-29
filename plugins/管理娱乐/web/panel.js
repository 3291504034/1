/* 管理娱乐 · 管理面板 JS */
const API = "/api/ext/superadmin";
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let toastT;
function toast(m, t) { const el = $("#toast"); if (el) { el.textContent = m; el.hidden = false; el.className = "toast show " + (t || ""); clearTimeout(toastT); toastT = setTimeout(() => el.classList.remove("show"), 2400); } }
function errToast(e) { toast(e && e.message || "请求失败", "error"); }
async function api(method, path, body) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body) opt.body = JSON.stringify(body);
  const res = await fetch(API + "/" + path, opt);
  const d = await res.json().catch(() => ({}));
  if (!res.ok || d.success !== true) throw new Error((d.error && d.error.message) || d.error || "请求失败");
  return d;
}
function shortId(id) { const s = String(id || ""); return s.length > 12 ? s.slice(0, 6) + "…" + s.slice(-4) : s; }

// ============ 群选择器 ============
let CUR_GID = "";
async function loadGroups() {
  const sel = $("#gid-select"); if (!sel) return;
  try {
    const d = await api("GET", "groups");
    const groups = d.groups || [];
    sel.innerHTML = '<option value="">🌐 全部群</option>' + groups.map(g =>
      '<option value="' + esc(g.gid) + '">' + esc(g.name || shortId(g.gid)) + (g.name ? ' · ' + shortId(g.gid) : '') + '</option>'
    ).join('');
    if (groups.length === 1) { CUR_GID = groups[0].gid; sel.value = CUR_GID; }
  } catch (e) { /* 群列表失败不阻塞 */ }
}
function curGid() { return CUR_GID || ""; }
function gidQuery() { const g = curGid(); return g ? "?gid=" + encodeURIComponent(g) : ""; }

const TITLES = { overview: "数据总览", users: "用户管理", config: "参数配置", features: "功能开关", group: "群管设置", replies: "回复文案", apikeys: "接口密钥", logs: "操作日志" };
function switchPage(name) {
  $$(".nav button").forEach(b => b.classList.toggle("active", b.dataset.page === name));
  $$(".page").forEach(p => p.classList.toggle("active", p.id === "page-" + name));
  const t = $("#page-title"); if (t) t.textContent = TITLES[name] || "";
  window.scrollTo(0, 0);
}
function bindNav() {
  $$(".nav button[data-page]").forEach(b => { b.onclick = () => switchPage(b.dataset.page); });
}

// ============ 总览 ============
let ALL_USERS = [], CONFIG = {};
async function loadOverview() {
  try {
    const d = await api("GET", "stats" + gidQuery());
    $("#m-users").textContent = d.users || 0;
    $("#m-points").textContent = d.points || 0;
    $("#m-armor").textContent = d.armor || 0;
    $("#m-blacklist").textContent = d.blacklist || 0;
    $("#m-logs").textContent = d.logs || 0;
  } catch (e) { errToast(e); }
}
async function loadTop() {
  const el = $("#top-list"); if (!el) return;
  try {
    const d = await api("GET", "rank" + gidQuery());
    const top = d.rank || [];
    if (!top.length) { el.innerHTML = '<div class="empty">暂无数据</div>'; return; }
    el.innerHTML = top.map((u, i) =>
      '<div class="compact-item"><span class="rank">' + (i + 1) + '</span>' +
      (u.avatar ? '<img class="avatar-sm" src="' + esc(u.avatar) + '" alt="" loading="lazy">' : '') +
      '<span class="uname">' + esc(u.nickname || shortId(u.qq)) + '</span><span class="pts">' + u.points + '</span></div>'
    ).join('');
  } catch (e) { errToast(e); }
}
const CMD_SHORT = [
  ["签到", "每日随机积分"], ["抽奖", "积分抽奖"], ["抢劫 @人", "抢积分"],
  ["发红包 100 5", "拼手气红包"], ["塔罗牌", "抽卡解读"], ["运势", "每日运势"],
  ["今日人品", "人品值"], ["投票 标题/选项", "群投票"], ["禁言 @人", "群管禁言"],
  ["拉黑 @人", "永久禁言+拉黑"], ["天气 北京", "实时天气"], ["热搜", "微博热榜"],
  ["战力 李白", "王者战力"], ["点歌 晴天", "搜歌播放"], ["壁纸", "随机壁纸"], ["早报", "每日新闻"],
];
function renderCmdSummary() {
  const el = $("#cmd-summary"); if (!el) return;
  el.innerHTML = '<div class="compact-list">' + CMD_SHORT.map(c =>
    '<div class="compact-item"><span class="uname">' + esc(c[0]) + '</span><span class="muted">' + esc(c[1]) + '</span></div>'
  ).join('') + '</div>';
}

// ============ 用户管理 ============
async function loadUsers() {
  try { ALL_USERS = (await api("GET", "users" + gidQuery())).users || []; renderUsers(); } catch (e) { errToast(e); }
}
function renderUsers() {
  const t = $("#users-tbody"); if (!t) return;
  const k = ($("#user-search").value || "").trim().toLowerCase();
  const list = ALL_USERS.filter(u => !k || (u.nickname || "").toLowerCase().includes(k) || String(u.qq || u.uid).includes(k));
  if (!list.length) { t.innerHTML = '<tr><td colspan="6" class="empty">暂无数据</td></tr>'; return; }
  t.innerHTML = list.map((u, i) =>
    '<tr><td>' + (i + 1) + '</td><td>' +
    (u.avatar ? '<img class="avatar-sm" src="' + esc(u.avatar) + '" alt="" loading="lazy"> ' : '') +
    '<span class="uname">' + esc(u.nickname || shortId(u.uid)) + '</span></td>' +
    '<td>' + u.points + '</td><td>' + (u.armor ? "🛡" : "—") + '</td><td>' + (u.sign_streak || 0) + '天</td>' +
    '<td class="nowrap">' +
    '<button class="btn-sm" onclick="adjustPoints(\'' + esc(u.uid) + '\',50)">+50</button>' +
    '<button class="btn-sm" onclick="adjustPoints(\'' + esc(u.uid) + '\',-50)">-50</button>' +
    '<button class="btn-sm" onclick="adjustPoints(\'' + esc(u.uid) + '\',-99999)">清0</button>' +
    '</td></tr>'
  ).join('');
}
async function adjustPoints(uid, delta) {
  try {
    await api("POST", "points", { uid, points: delta, gid: curGid() });
    toast("积分已调整", "ok"); loadUsers(); loadOverview(); loadTop();
  } catch (e) { errToast(e); }
}

// ============ 参数配置 ============
const CONFIG_FIELDS = [
  ["sign_lo", "签到最低", 1, 0], ["sign_hi", "签到最高", 150, 0],
  ["lottery_cost", "抽奖费用", 20, 0], ["lottery_lo", "抽奖最低", 1, 0], ["lottery_hi", "抽奖最高", 100, 0],
  ["lottery_win_rate", "中奖率 %", 60, 1], ["robbery_lo", "抢劫最低", 10, 0], ["robbery_hi", "抢劫最高", 80, 0],
  ["robbery_rate", "抢劫成功率 %", 40, 1], ["armor_cost", "反甲价格", 200, 0], ["armor_days", "反甲天数", 3, 0],
  ["redpack_min", "红包最低", 10, 0], ["redpack_max_count", "红包最大份数", 20, 0],
  ["step1_mute", "二次违规禁言(分钟)", 10, 0], ["step2_mute", "三次违规禁言(分钟)", 60, 0],
  ["violation_reset", "违规冷却(小时)", 24, 0], ["spam_interval", "刷屏间隔(秒)", 5, 0], ["spam_count", "刷屏条数", 5, 0],
];
async function loadConfigForm() {
  const el = $("#config-grid"); if (!el) return;
  try { CONFIG = (await api("GET", "config" + gidQuery())).config || {}; } catch (e) { errToast(e); }
  el.innerHTML = CONFIG_FIELDS.map(([k, label, def, isPct]) => {
    let v = CONFIG[k] ?? def;
    if (isPct) v = Math.round(v * 100);
    return '<label>' + esc(label) + '<input id="cfg-' + k + '" class="inp" type="number" value="' + v + '" min="0" ' + (isPct ? 'max="100"' : '') + '></label>';
  }).join('');
}
async function saveConfig() {
  const cfg = {};
  CONFIG_FIELDS.forEach(([k, , , isPct]) => {
    const e = $("#cfg-" + k); if (!e) return;
    let v = parseFloat(e.value);
    if (isPct) v = (v || 0) / 100;
    cfg[k] = isFinite(v) ? v : 0;
  });
  const btn = $("#save-config"); if (btn) btn.disabled = true;
  if (curGid()) cfg.gid = curGid();
  try { const m = curGid() ? "群配置已保存" : "全局配置已保存"; await api("POST", "config", cfg); toast(m, "ok"); } catch (e) { errToast(e); }
  finally { if (btn) btn.disabled = false; }
}

// ============ 功能开关 ============
const FEATURES = [
  ["mute", "禁言"], ["sign", "签到"], ["lottery", "抽奖"], ["redpack", "红包"],
  ["rob", "抢劫"], ["armor", "反甲"], ["tarot", "塔罗牌"], ["fortune", "运势"],
  ["vote", "投票"], ["jrrp", "今日人品"], ["weather", "天气"], ["hot", "热搜"],
  ["wzry", "战力"], ["wallpaper", "壁纸"], ["news", "早报"], ["moyu", "摸鱼"],
  ["music", "点歌"],
];
async function loadFeatures() {
  const el = $("#feature-grid"); if (!el) return;
  try { CONFIG = (await api("GET", "config" + gidQuery())).config || {}; } catch (e) { errToast(e); }
  const f = CONFIG.features || {};
  el.innerHTML = FEATURES.map(([k, label]) =>
    '<div class="feature-item ' + (f[k] !== false ? 'on' : '') + '" data-f="' + k + '" onclick="toggleFeature(\'' + k + '\')">' +
    '<b>' + label + '</b><div class="switch"></div></div>'
  ).join('');
}
async function toggleFeature(k) {
  const el = document.querySelector('.feature-item[data-f="' + k + '"]');
  const on = !el.classList.contains("on");
  try {
    await api("POST", "toggle", { feature: k, enabled: on, gid: curGid() });
    el.classList.toggle("on", on);
    toast((on ? "开启" : "关闭") + "成功", "ok");
  } catch (e) { errToast(e); }
}

// ============ 群管设置 ============
async function loadGroupSettings() {
  try {
    const q = gidQuery();
    const words = (await api("GET", "banned_words" + q)).words || [];
    $("#banned-words").value = words.join("\n");
    $("#welcome-msg").value = (await api("GET", "welcome" + q)).welcome || "";
    const v = (await api("GET", "join_verify" + q)).verify || {};
    $("#verify-enabled").checked = !!v.enabled;
    const vm = $("#verify-mode"); if (vm) vm.value = v.mode || "digits";
    $("#verify-digits").value = v.digits || 4;
    $("#verify-tries").value = v.tries || 3;
    $("#verify-timeout").value = v.timeout || 300;
    loadBlacklist();
  } catch (e) { errToast(e); }
}
async function saveBanned() {
  const words = $("#banned-words").value.split("\n").map(w => w.trim()).filter(Boolean);
  try { await api("POST", "banned_words", { words, gid: curGid() }); toast("违禁词已保存", "ok"); } catch (e) { errToast(e); }
}
async function saveWelcome() {
  try {
    await api("POST", "welcome", { welcome: $("#welcome-msg").value, gid: curGid() });
    await api("POST", "join_verify", {
      enabled: $("#verify-enabled").checked,
      mode: ($("#verify-mode") && $("#verify-mode").value) || "digits",
      digits: parseInt($("#verify-digits").value) || 4,
      tries: parseInt($("#verify-tries").value) || 3,
      timeout: parseInt($("#verify-timeout").value) || 300,
      gid: curGid(),
    });
    toast("设置已保存", "ok");
  } catch (e) { errToast(e); }
}
async function loadBlacklist() {
  const el = $("#blacklist-list"); if (!el) return;
  try {
    const q = curGid() ? "?gid=" + encodeURIComponent(curGid()) : "";
    const bl = (await api("GET", "blacklist" + q)).blacklist || {};
    const keys = Object.keys(bl);
    if (!keys.length) { el.innerHTML = '<div class="empty">黑名单为空</div>'; return; }
    el.innerHTML = '<table><thead><tr><th>QQ</th><th>原因</th><th>拉黑时间</th><th>操作</th></tr></thead><tbody>' +
      keys.map(uid => '<tr><td>' + esc(uid) + '</td><td>' + esc(bl[uid].reason || "") + '</td><td>' + esc(bl[uid].time || "") + '</td>' +
        '<td><button class="btn-sm" onclick="blacklistRemove(\'' + esc(uid) + '\')">解除</button></td></tr>').join('') +
      '</tbody></table>';
  } catch (e) { errToast(e); }
}
async function blacklistAdd() {
  const uid = $("#blacklist-uid").value.trim();
  const reason = $("#blacklist-reason").value.trim();
  if (!uid) return toast("请输入QQ号", "error");
  try {
    const gid = curGid();
    const q = gid ? "?gid=" + encodeURIComponent(gid) : "";
    const bl = (await api("GET", "blacklist" + q)).blacklist || {};
    bl[uid] = { reason, time: new Date().toISOString().slice(0, 16).replace("T", " "), expire: 0 };
    await api("POST", "blacklist", { gid, blacklist: bl });
    $("#blacklist-uid").value = ""; $("#blacklist-reason").value = "";
    toast("已添加黑名单", "ok"); loadBlacklist();
  } catch (e) { errToast(e); }
}
async function blacklistRemove(uid) {
  try {
    const gid = curGid();
    const q = gid ? "?gid=" + encodeURIComponent(gid) : "";
    const bl = (await api("GET", "blacklist" + q)).blacklist || {};
    delete bl[uid];
    await api("POST", "blacklist", { gid, blacklist: bl });
    toast("已解除拉黑", "ok"); loadBlacklist();
  } catch (e) { errToast(e); }
}

// ============ 回复文案 ============
const REPLY_KEYS = [
  ["sign_ok", "签到成功"], ["sign_fail", "签到失败"], ["lottery_win", "抽奖中奖"],
  ["lottery_lose", "抽奖未中"], ["rob_ok", "抢劫成功"], ["rob_fail", "抢劫失败"],
  ["rob_armor", "反甲反弹"], ["tarot", "塔罗牌"], ["fortune", "运势"], ["jrrp", "今日人品"],
  ["vote_result", "投票结果"], ["welcome", "入群欢迎"],
];
async function loadReplies() {
  const el = $("#replies-grid"); if (!el) return;
  try { CONFIG = (await api("GET", "config" + gidQuery())).config || {}; } catch (e) { errToast(e); }
  const replies = CONFIG.replies || {};
  el.innerHTML = REPLY_KEYS.map(([k, label]) =>
    '<label>' + esc(label) + '<input id="rpl-' + k + '" class="inp" type="text" value="' + esc(replies[k] || "") + '" style="width:100%"></label>'
  ).join('');
}
async function saveReplies() {
  const replies = {};
  REPLY_KEYS.forEach(([k]) => { const e = $("#rpl-" + k); if (e) replies[k] = e.value; });
  const btn = $("#save-replies"); if (btn) btn.disabled = true;
  try { if (curGid()) replies.gid = curGid(); await api("POST", "replies", { replies }); toast("文案已保存", "ok"); } catch (e) { errToast(e); }
  finally { if (btn) btn.disabled = false; }
}

// ============ 接口密钥 ============
async function loadApiKeys() {
  const el = $("#apikeys-list"); if (!el) return;
  try {
    const d = await api("GET", "apikeys");
    const keys = d.keys || {};
    const fields = d.fields || [];
    if (!fields.length) { el.innerHTML = '<div class="empty">暂无接口密钥配置</div>'; return; }
    el.innerHTML = fields.map(f =>
      '<div class="key-item">' +
      '<div class="key-info"><b>' + esc(f.name) + '</b>' +
      '<p class="muted">' + esc(f.usage) + '</p>' +
      '<p class="hint">' + esc(f.where) + '</p>' +
      '<a href="' + esc(f.doc_url) + '" target="_blank" rel="noopener" class="hint">📖 接口文档: ' + esc(f.doc_url) + '</a></div>' +
      '<label>密钥 <input id="key-' + esc(f.key) + '" class="inp" type="password" value="' + esc(keys[f.key] || "") + '" placeholder="粘贴你的 ' + esc(f.name) + '" autocomplete="off" style="width:100%"></label>' +
      '</div>'
    ).join('');
  } catch (e) { errToast(e); }
}
async function saveApiKeys() {
  try {
    const d = await api("GET", "apikeys");
    const fields = d.fields || [];
    const keys = {};
    fields.forEach(f => { const e = $("#key-" + f.key); if (e && e.value.trim()) keys[f.key] = e.value.trim(); });
    const btn = $("#save-apikeys"); if (btn) btn.disabled = true;
    try { await api("POST", "apikeys", { keys }); toast("密钥已保存", "ok"); } catch (e) { errToast(e); }
    finally { if (btn) btn.disabled = false; }
  } catch (e) { errToast(e); }
}

// ============ 操作日志 ============
async function loadLogs() {
  const el = $("#logs-list"); if (!el) return;
  try {
    const d = await api("GET", "logs");
    const logs = d.logs || [];
    if (!logs.length) { el.innerHTML = '<div class="empty">暂无记录</div>'; return; }
    el.innerHTML = '<div class="compact-list">' + logs.map(l =>
      '<div class="compact-item"><span class="nowrap" style="color:var(--muted)">' + esc(l.time) + '</span><span>' + esc(l.text) + '</span></div>'
    ).join('') + '</div>';
  } catch (e) { errToast(e); }
}

// ============ 初始化 ============
function init() {
  bindNav();
  const st = $("#sidebar-toggle"); if (st) st.onclick = () => $("#app").classList.toggle("sidebar-open");
  const sc = $("#sidebar-scrim"); if (sc) sc.onclick = () => $("#app").classList.remove("sidebar-open");
  const us = $("#user-search"); if (us) us.addEventListener("input", renderUsers);
  const scfg = $("#save-config"); if (scfg) scfg.onclick = saveConfig;
  const sb = $("#save-banned"); if (sb) sb.onclick = saveBanned;
  const sw = $("#save-welcome"); if (sw) sw.onclick = saveWelcome;
  const sr = $("#save-replies"); if (sr) sr.onclick = saveReplies;
  const sak = $("#save-apikeys"); if (sak) sak.onclick = saveApiKeys;
  const ba = $("#blacklist-add"); if (ba) ba.onclick = blacklistAdd;
  const gsel = $("#gid-select"); if (gsel) gsel.onchange = () => { CUR_GID = gsel.value; loadOverview(); loadTop(); loadUsers(); loadConfigForm(); loadFeatures(); loadGroupSettings(); loadReplies(); };
  const rb = $("#refresh-btn"); if (rb) rb.onclick = () => { loadOverview(); loadTop(); loadUsers(); loadLogs(); toast("已刷新", "ok"); };
  const rl = $("#refresh-logs"); if (rl) rl.onclick = loadLogs;
  switchPage("overview");
  loadGroups();
  loadOverview(); loadTop(); renderCmdSummary();
  loadUsers(); loadConfigForm(); loadFeatures();
  loadGroupSettings(); loadReplies(); loadApiKeys(); loadLogs();
}
document.addEventListener("DOMContentLoaded", init);