/* 每日 AI 新闻助手 · 前端公共逻辑（原生 JS，无构建步骤）
 * 页面分发：body[data-page] = settings | briefs
 */
'use strict';

const TOPICS = ['大模型', 'AI 芯片', '自动驾驶', 'AI 政策', 'AI 应用'];

/* ---------- API 封装（统一错误 → Error(code: message)） ---------- */
const API = {
  async request(method, url, body) {
    const options = { method, headers: {} };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    const resp = await fetch(url, options);
    let data = null;
    try { data = await resp.json(); } catch (err) { /* 无 JSON 响应体 */ }
    if (!resp.ok) {
      const err = (data && data.error) || {};
      throw new Error((err.code || resp.status) + ': ' + (err.message || resp.statusText));
    }
    return data;
  },
  getProfile() { return this.request('GET', '/api/profile'); },
  saveProfile(payload) { return this.request('PUT', '/api/profile', payload); },
  listBriefs(page, size) { return this.request('GET', '/api/briefs?page=' + page + '&size=' + size); },
  getBrief(id) { return this.request('GET', '/api/briefs/' + id); },
  generate() { return this.request('POST', '/api/briefs/generate'); },
  getRun(id) { return this.request('GET', '/api/runs/' + id); }, // 仅用于生成后的状态轮询
};

/* ---------- 工具函数 ---------- */
function $(id) { return document.getElementById(id); }

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function fmtTime(iso) { return iso ? iso.replace('T', ' ').slice(0, 19) : '—'; }
function pad2(n) { return String(n).padStart(2, '0'); }

function toast(message, type) {
  const box = $('toast');
  if (!box) return;
  const item = document.createElement('div');
  item.className = 'toast-item ' + (type || 'info');
  item.textContent = message;
  box.appendChild(item);
  setTimeout(function () { item.remove(); }, 4000);
}

function renderMarkdown(text) {
  if (window.marked) return window.marked.parse(text || '');
  return '<pre>' + escapeHtml(text || '') + '</pre>'; /* 离线兜底：纯文本展示 */
}

/* ---------- 页面：订阅设置（settings.html） ---------- */
/* 渠道元数据：按场景分组渲染；url=true 的渠道展开后可填各自推送地址（可多选） */
const CHANNEL_GROUPS = [
  {
    title: '推送到手机（微信）',
    channels: [
      { id: 'serverchan', label: 'Server 酱（推荐 · 扫码即用，无需实名）', url: true,
        urlLabel: '推送地址（Server 酱 API URL）',
        hint: '免费推送到你的微信，扫码即用：登录 sct.ftqq.com 微信扫码 → 复制 SendKey → 此框填写 https://sctapi.ftqq.com/{SendKey}.send' },
      { id: 'pushplus', label: 'PushPlus（需先完成实名认证）', url: true,
        urlLabel: '推送地址（PushPlus API URL）',
        hint: '推送到你的微信（需先实名）：登录 pushplus.plus 微信扫码并完成实名 → 复制 token → 此框填写 https://www.pushplus.plus/send/{token}' },
    ],
  },
  {
    title: '推送到团队群（需先建群并添加机器人）',
    channels: [
      { id: 'wecom', label: '企业微信群机器人', url: true, urlLabel: '机器人地址（Webhook URL）',
        hint: '企业微信：群设置 → 群机器人 → 添加机器人 → 复制 Webhook 地址' },
      { id: 'feishu', label: '飞书群机器人', url: true, urlLabel: '机器人地址（Webhook URL）',
        hint: '飞书：群设置 → 群机器人 → 添加自定义机器人 → 复制 Webhook 地址' },
      { id: 'dingtalk', label: '钉钉群机器人', url: true, urlLabel: '机器人地址（Webhook URL）',
        hint: '钉钉：群设置 → 智能群助手 → 添加自定义机器人 → 复制 Webhook 地址（安全设置选"自定义关键词"时请包含"简报"）' },
    ],
  },
  {
    title: '其他方式',
    channels: [
      { id: 'email', label: '邮件（发送到上方的邮箱）', url: false,
        hint: '邮件渠道需要在服务器 .env 配置 SMTP_HOST / SMTP_USER / SMTP_PASS / SMTP_FROM（参考 .env.example）' },
      { id: 'webhook', label: '自定义 Webhook（通用 JSON）', url: true, urlLabel: '接收地址（Webhook URL）',
        hint: '通用契约：接收方将收到 POST JSON {"title": "...", "content": "...（Markdown 文本）"}' },
    ],
  },
];

function findChannelMeta(channelId) {
  for (const group of CHANNEL_GROUPS) {
    for (const ch of group.channels) {
      if (ch.id === channelId) return ch;
    }
  }
  return null;
}

function renderChannelBox() {
  const box = $('channelBox');
  box.innerHTML = CHANNEL_GROUPS.map(function (group) {
    return '<div class="channel-group"><div class="group-title">' + escapeHtml(group.title) + '</div>' +
      group.channels.map(function (ch) {
        const body = ch.url
          ? '<div class="channel-body"><div class="url-label">' + escapeHtml(ch.urlLabel) + '</div>' +
            '<input type="url" class="channel-url" data-channel="' + ch.id + '" placeholder="https://...">' +
            '<div class="hint">' + escapeHtml(ch.hint) + '</div></div>'
          : '<div class="channel-body"><div class="hint">' + escapeHtml(ch.hint) + '</div></div>';
        return '<div class="channel-item" data-channel="' + ch.id + '">' +
          '<label class="channel-head"><input type="checkbox" value="' + ch.id + '"> ' +
          escapeHtml(ch.label) + '</label>' + body + '</div>';
      }).join('') + '</div>';
  }).join('');
  box.addEventListener('change', function (event) {
    if (event.target && event.target.type === 'checkbox') toggleChannelBody(event.target);
  });
}

function toggleChannelBody(checkbox) {
  const body = checkbox.closest('.channel-item').querySelector('.channel-body');
  if (body) body.style.display = checkbox.checked ? 'block' : 'none';
}

/* 收集勾选的渠道与各自地址（email 无地址输入） */
function collectChannelPayload() {
  const channels = [];
  const urls = {};
  document.querySelectorAll('#channelBox input[type="checkbox"]:checked').forEach(function (cb) {
    channels.push(cb.value);
    const input = document.querySelector('#channelBox .channel-url[data-channel="' + cb.value + '"]');
    if (input) urls[cb.value] = input.value.trim();
  });
  return { channels: channels, urls: urls };
}

async function initSettingsPage() {
  const profile = await API.getProfile();
  const prefs = profile.preferences;

  $('name').value = profile.user.name || '';
  $('email').value = profile.user.email || '';

  const selected = new Set(prefs.topics || []);
  $('topics').innerHTML = TOPICS.map(function (topic) {
    return '<label><input type="checkbox" value="' + escapeHtml(topic) + '"' +
      (selected.has(topic) ? ' checked' : '') + '> ' + escapeHtml(topic) + '</label>';
  }).join('');

  $('keywords').value = prefs.keywords || '';
  $('exclude_keywords').value = prefs.exclude_keywords || '';
  $('push_time').value = prefs.push_time || '08:00';

  renderChannelBox();
  (prefs.push_channels || []).forEach(function (ch) {
    const cb = document.querySelector('#channelBox input[value="' + ch + '"]');
    if (cb) { cb.checked = true; toggleChannelBody(cb); }
  });
  Object.keys(prefs.channel_urls || {}).forEach(function (ch) {
    const input = document.querySelector('#channelBox .channel-url[data-channel="' + ch + '"]');
    if (input) input.value = prefs.channel_urls[ch];
  });

  const next = new Date(Date.now() + 60000);
  $('hint').textContent = '演示定时任务可设为当前时间 + 1 分钟（如 ' +
    pad2(next.getHours()) + ':' + pad2(next.getMinutes()) + '）';

  $('saveBtn').addEventListener('click', saveSettings);
}

async function saveSettings() {
  const name = $('name').value.trim();
  if (!name) { toast('姓名不能为空', 'error'); return; }
  const email = $('email').value.trim();
  if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { toast('邮箱格式不正确', 'error'); return; }
  const pushTime = $('push_time').value;
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(pushTime)) { toast('推送时间格式不正确（HH:MM）', 'error'); return; }

  const picked = collectChannelPayload();
  for (const channel of picked.channels) {
    const meta = findChannelMeta(channel);
    const url = picked.urls[channel];
    if (meta && meta.url && !url) { toast('请填写「' + meta.label + '」的推送地址', 'error'); return; }
    if (url && !/^https?:\/\//.test(url)) { toast('推送地址需以 http:// 或 https:// 开头', 'error'); return; }
  }
  if (picked.channels.indexOf('email') !== -1 && !email) {
    toast('勾选邮件渠道时必须填写邮箱', 'error'); return;
  }

  const payload = {
    name: name,
    email: email || null,
    topics: Array.from(document.querySelectorAll('#topics input:checked')).map(function (el) { return el.value; }),
    keywords: $('keywords').value,
    exclude_keywords: $('exclude_keywords').value,
    push_time: pushTime,
    push_channels: picked.channels,
    channel_urls: picked.urls,
  };

  $('saveBtn').disabled = true;
  try {
    await API.saveProfile(payload);
    toast('已保存，调度已更新', 'success');
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    $('saveBtn').disabled = false;
  }
}

/* ---------- 页面：简报（index.html） ---------- */
let briefPage = 1;
let pollTimer = null;
let latestBrief = null;     // 第一页第一条（全局最新简报），用于「今日是否已生成」判断
let pushTimeText = '每日定时';

function todayStr() {
  const now = new Date();
  return now.getFullYear() + '-' + pad2(now.getMonth() + 1) + '-' + pad2(now.getDate());
}

async function initBriefsPage() {
  window.addEventListener('beforeunload', stopPolling);
  try {
    const profile = await API.getProfile();
    if (profile && profile.preferences && profile.preferences.push_time) {
      pushTimeText = profile.preferences.push_time + ' 定时';
    }
  } catch (err) { /* 拿不到偏好就用通用文案 */ }
  await loadBriefs();
}

async function loadBriefs(openId) {
  const data = await API.listBriefs(briefPage, 20);
  if (briefPage === 1) {
    latestBrief = data.items.length ? data.items[0] : null;
  }
  const list = $('briefList');
  if (data.items.length) {
    list.innerHTML = data.items.map(function (item) {
      const isToday = item.brief_date === todayStr();
      return '<li data-id="' + item.id + '"><div class="item-title">' + escapeHtml(item.title) + '</div>' +
        '<div class="item-date">' + (item.brief_date || '') + (isToday ? ' · 今天' : '') +
        ' · 生成于 ' + fmtTime(item.created_at) + '</div></li>';
    }).join('');
    list.querySelectorAll('li[data-id]').forEach(function (li) {
      li.addEventListener('click', function () { openBrief(Number(li.dataset.id)); });
    });
  } else {
    list.innerHTML = '<li class="placeholder" style="cursor:default">暂无简报</li>';
  }
  const pages = Math.max(1, Math.ceil(data.total / data.size));
  $('prevBtn').disabled = briefPage <= 1;
  $('nextBtn').disabled = briefPage >= pages;
  $('pageInfo').textContent = briefPage + ' / ' + pages;

  renderTodayBar();
  if (!data.items.length) {
    $('briefDetail').innerHTML = '<p class="placeholder">还没有简报。点上方按钮生成第一份，或等待每日定时自动推送。</p>';
  } else if (openId) {
    await openBrief(openId);
  } else if (briefPage === 1) {
    await openBrief(data.items[0].id); // 打开页面默认展示最新一份
  }
}

/* 「今日」工具条：今天未生成时给出显著生成入口；已生成则弱化为「重新生成」 */
function renderTodayBar() {
  const bar = $('todayBar');
  bar.classList.remove('hidden', 'attention', 'quiet');
  let html;
  if (!latestBrief) {
    bar.classList.add('attention');
    html = '<span>还没有任何简报</span><button id="generateBtn">生成第一份</button>';
  } else if (latestBrief.brief_date !== todayStr()) {
    bar.classList.add('attention');
    html = '<span>今天的简报还没有生成 —— ' + escapeHtml(pushTimeText) +
      '自动推送到手机，也可以现在来一份</span><button id="generateBtn">生成今日简报</button>';
  } else {
    bar.classList.add('quiet');
    html = '<span>今天的简报已生成 ✓</span><button id="generateBtn" class="secondary">重新生成</button>';
  }
  bar.innerHTML = html;
  const btn = $('generateBtn');
  btn.addEventListener('click', generateBrief);
  btn.disabled = !!pollTimer; // 生成进行中保持禁用
}

async function openBrief(id) {
  const brief = await API.getBrief(id);
  $('briefDetail').innerHTML = renderMarkdown(brief.content_md);
  document.querySelectorAll('.brief-list li').forEach(function (li) {
    li.classList.toggle('active', Number(li.dataset.id) === id);
  });
}

function setGenerateEnabled(enabled) {
  const btn = $('generateBtn');
  if (btn) btn.disabled = !enabled;
}

async function generateBrief() {
  setGenerateEnabled(false);
  setStatus('running', '运行中：Agent 正在搜集与整理新闻…');
  try {
    const result = await API.generate();
    startPolling(result.run_id);
  } catch (err) {
    setGenerateEnabled(true);
    setStatus('failed', '生成失败：' + err.message);
  }
}

function setStatus(kind, text) {
  const bar = $('statusBar');
  bar.className = 'status-bar ' + kind;
  bar.textContent = text;
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function startPolling(runId) {
  stopPolling();
  let ticks = 0;
  pollTimer = setInterval(async function () {
    ticks += 1;
    if (ticks > 150) { /* 5 分钟上限 */
      stopPolling();
      setGenerateEnabled(true);
      setStatus('failed', '轮询超时（5 分钟），请刷新页面查看结果');
      return;
    }
    let run;
    try {
      run = await API.getRun(runId);
    } catch (err) {
      stopPolling();
      setGenerateEnabled(true);
      setStatus('failed', '生成失败：' + err.message);
      return;
    }
    if (run.status === 'running') {
      const seconds = Math.max(0, Math.round((Date.now() - new Date(run.started_at).getTime()) / 1000));
      setStatus('running', '运行中：Agent 已运行 ' + seconds + ' 秒（LLM 自主决策中）…');
      return;
    }
    stopPolling();
    setGenerateEnabled(true);
    if (run.status === 'success') {
      setStatus('success', '生成成功（' + run.steps_used + ' 步），新简报已打开');
      briefPage = 1;
      await loadBriefs(run.brief_id);
      toast('简报已生成', 'success');
    } else {
      setStatus('failed', '生成失败：' + (run.error || '未知错误'));
    }
  }, 2000);
}

/* ---------- 入口分发 ---------- */
document.addEventListener('DOMContentLoaded', function () {
  const initializers = {
    settings: initSettingsPage,
    briefs: initBriefsPage,
  };
  const init = initializers[document.body.dataset.page];
  if (init) {
    init().catch(function (err) { toast(err.message, 'error'); });
  }
});
