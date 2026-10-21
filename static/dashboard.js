"use strict";
const $ = id => document.getElementById(id);
const node = (tag, className, text) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
};
const channelDefinitions = {
  webhook: {name: "飞书", description: "需要重新扫码时提醒；同一次失效只通知一次。", timing: "保存后对后续登录事件生效。机器人开启关键词校验时，请添加“微信读书”。", fields: [
    ["webhook_url", "群机器人 Webhook 地址", "password", "从飞书群的自定义机器人设置中复制。"],
    ["webhook_secret", "签名密钥", "password", "仅在机器人启用签名校验时填写。"],
    ["panel_url", "管理面板地址", "url", "可选，填写手机能够访问的地址，方便从提醒中打开。"]]},
  bark: {name: "Bark", description: "推送到 Bark，接收登录与阅读任务通知。", timing: "保存后，从下一次阅读任务起使用新配置。", fields: [
    ["bark_key", "设备推送密钥", "password", "从手机 Bark 应用中复制设备密钥。"],
    ["bark_url", "推送服务器", "url", "默认使用官方服务器，也可以填写自建服务器地址。"]]},
  email: {name: "邮件", description: "接收扫码登录链接，以及任务完成或异常报告。", timing: "保存后，从下一次阅读任务起使用新配置。常用端口为 465（SSL）或 587（STARTTLS）。", fields: [
    ["email_smtp", "SMTP 服务器", "text", "邮箱提供商的 SMTP 地址，例如 smtp.qq.com。"],
    ["email_port", "SMTP 端口", "number", "使用邮箱提供商要求的端口。"],
    ["email_user", "发件邮箱账号", "text", "用于登录 SMTP 服务器的邮箱账号。"],
    ["email_pass", "邮箱授权码", "password", "通常填写 SMTP 授权码，而不是邮箱登录密码。"],
    ["email_to", "收件人邮箱", "text", "多个地址可用英文逗号分隔。"],
    ["email_from", "发件人地址", "text", "可选，留空时使用发件邮箱账号。"]]}
};
let notificationConfig = null;
let lockedFields = [];
let selectedChannel = "webhook";
let refreshTimer;
let refreshInterval = 30000;
let logSequence = 0;
let logSearchTimer;
let refreshPending = false;
let actionPending = false;

async function api(path, options = {}) {
  const response = await fetch(path, {cache: "no-store", headers: {Accept: "application/json"}, ...options});
  if (response.status === 401) { location.href = "/login"; throw new Error("请重新登录管理面板"); }
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.reason || "请求失败，请稍后重试");
  return data;
}
function age(seconds) {
  if (seconds == null) return "未知时间";
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}
function dateTime(value) {
  if (!value) return "尚无记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "未知时间" : date.toLocaleString("zh-CN", {hour12: false});
}
function setBadge(id, text, level) { $(id).textContent = text; $(id).className = `badge ${level}`; }
function renderReading(reading) {
  const last = reading.last_run || {};
  const phase = reading.phase || "idle";
  const phases = {running: ["正在阅读", "info"], waiting_login: ["等待扫码", "warning"], failed: ["上次异常", "error"], idle: ["等待下次任务", "neutral"]};
  setBadge("phase", ...(phases[phase] || phases.idle));
  const remaining = reading.eta_seconds;
  $("eta").textContent = phase === "running" && remaining != null ? `${Math.floor(remaining / 60).toString().padStart(2, "0")}:${Math.floor(remaining % 60).toString().padStart(2, "0")}` : "—";
  $("run-hint").textContent = phase === "waiting_login" ? "请扫描右侧二维码完成登录。" : phase === "running" ? "预计剩余时间包含启动耗时，以实际阅读日志为准。" : phase === "failed" ? "查看下方异常日志了解原因。" : "自动调度已开启，也可以手动启动。";
  $("started-at").textContent = dateTime(last.started_at);
  $("ended-at").textContent = dateTime(last.ended_at);
  const results = {completed: "阅读完成", failed: "运行失败", stopped: "已停止", running: "进行中"};
  $("last-result").textContent = (results[last.status] || "尚无记录") + (last.exit_code && last.exit_code !== 0 ? `（退出码 ${last.exit_code}）` : "");
  $("start-btn").disabled = actionPending || Boolean(reading.pid);
  const qr = reading.login_qr || {};
  const cookies = reading.cookies || {};
  const block = $("qr-block");
  if (qr.active) {
    let img = block.querySelector("img");
    if (!img) { img = node("img", "qr-image"); img.alt = "微信读书登录二维码"; block.replaceChildren(img); }
    img.src = `/login.png?t=${Date.now()}`;
    setBadge("login-badge", "请扫码", "warning");
    $("cookie-detail").textContent = `二维码生成于${age(qr.age_seconds)}，请使用微信读书扫码。`;
  } else {
    const saved = cookies.status !== "missing";
    const empty = node("div", "empty-state");
    empty.append(node("div", "empty-icon", saved ? "✓" : "↗"), node("strong", "", saved ? "已保存登录信息" : "尚未登录微信读书"), node("p", "", saved ? "需要重新登录时，这里会显示新的二维码。" : "点击“开始阅读”生成登录二维码。"));
    block.replaceChildren(empty);
    setBadge("login-badge", saved ? "已有登录信息" : "待登录", saved ? "success" : "neutral");
    $("cookie-detail").textContent = saved ? `登录信息${age((cookies.age_days || 0) * 86400)}更新，有效性以实际阅读结果为准。` : "已过期的旧二维码不会继续展示。";
  }
}
function renderSettings(settings) {
  $("settings-primary").replaceChildren(...(settings.primary || []).map(item => {
    const box = node("div", "setting");
    box.append(node("div", "setting-label", item.label), node("div", "setting-value", item.value), node("p", "setting-description", item.description));
    return box;
  }));
  $("settings-advanced").replaceChildren(...(settings.advanced || []).map(item => {
    const row = node("div", "advanced-row");
    const label = node("div", "", item.label);
    label.append(node("code", "env-name", item.key), node("p", "hint", item.description));
    row.append(label, node("div", "advanced-value", item.value));
    return row;
  }));
}
function renderNotificationSummary(channels) {
  const configured = channels.filter(channel => channel.has_settings || channel.enabled);
  $("notification-summary").replaceChildren(...(configured.length ? configured.map(channel => {
    const item = node("div", "notification-item");
    const label = node("div");
    label.append(node("strong", "", channel.label), node("p", "", channel.configured ? "配置已保存" : "配置尚未补全"));
    item.append(label, node("span", `badge ${channel.active ? "success" : channel.enabled ? "warning" : "neutral"}`, channel.active ? "已开启" : channel.enabled ? "待补全" : "已停用"));
    return item;
  }) : [node("p", "muted", "尚未配置通知。点击“管理通知”添加飞书、Bark 或邮件。") ]));
}
async function refresh() {
  if (refreshPending) return;
  refreshPending = true;
  try {
    const data = await api("/status");
    renderReading(data.reading || {});
    renderSettings(data.settings || {});
    renderNotificationSummary((data.notifications || {}).channels || []);
    $("connection").textContent = "服务已连接"; $("connection").className = "connection";
    $("updated-at").textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN", {hour12: false})}`;
    const interval = data.reading?.phase === "waiting_login" ? 5000 : 30000;
    if (refreshInterval !== interval) {
      clearInterval(refreshTimer); refreshInterval = interval;
      refreshTimer = setInterval(() => { refresh(); loadLogs(); }, interval);
      $("refresh-label").textContent = `每 ${interval / 1000} 秒刷新`;
    }
  } catch (error) {
    $("connection").textContent = "连接中断"; $("connection").className = "connection error";
    $("updated-at").textContent = error.message;
  } finally { refreshPending = false; }
}
function collectFields() {
  if (!notificationConfig) return;
  const cfg = notificationConfig[selectedChannel];
  cfg.enabled = $("channel-enabled").checked;
  channelDefinitions[selectedChannel].fields.forEach(([key]) => { if (!$(key).disabled) cfg[key] = $(key).value; });
}
function renderChannel() {
  const definition = channelDefinitions[selectedChannel];
  const cfg = notificationConfig[selectedChannel];
  document.querySelectorAll("[data-channel]").forEach(button => button.setAttribute("aria-selected", String(button.dataset.channel === selectedChannel)));
  $("channel-panel").setAttribute("aria-labelledby", `tab-${selectedChannel}`);
  $("channel-description").textContent = definition.description;
  $("channel-timing").textContent = definition.timing;
  $("channel-enabled").checked = cfg.enabled;
  $("notification-fields").replaceChildren(...definition.fields.map(([key, label, type, description]) => {
    const field = node("div", "field");
    const title = node("label", "", label); title.htmlFor = key;
    const input = node("input"); input.id = key; input.type = type; input.value = cfg[key] || ""; input.autocomplete = "off";
    input.disabled = lockedFields.includes(key);
    const help = node("p", "hint", input.disabled ? "由容器环境变量提供；启用开关仍可在这里调整。" : description);
    help.id = `${key}-help`; input.setAttribute("aria-describedby", help.id);
    if (type === "number") { input.min = "1"; input.max = "65535"; }
    field.append(title, input, help); return field;
  }));
}
async function loadNotifications() {
  const data = await api("/api/notification");
  notificationConfig = data.config; lockedFields = data.locked_fields || [];
  renderNotificationSummary(data.channels || []); renderChannel();
  $("notification-save").disabled = false; $("notification-test").disabled = false;
}
$("manage-notifications").addEventListener("click", async () => {
  const manager = $("notification-manager");
  manager.hidden = !manager.hidden;
  $("manage-notifications").setAttribute("aria-expanded", String(!manager.hidden));
  $("manage-notifications").textContent = manager.hidden ? "管理通知" : "收起设置";
  if (!manager.hidden && !notificationConfig) {
    try { await loadNotifications(); } catch (error) { $("notification-result").textContent = error.message; }
  }
});
document.querySelectorAll("[data-channel]").forEach(button => button.addEventListener("click", () => {
  if (!notificationConfig) return;
  collectFields(); selectedChannel = button.dataset.channel; renderChannel();
  $("notification-result").textContent = "";
}));
$("notification-form").addEventListener("submit", async event => {
  event.preventDefault(); collectFields();
  $("notification-save").disabled = true; $("notification-test").disabled = true;
  try {
    const supported = Object.fromEntries(Object.keys(channelDefinitions).map(key => [key, notificationConfig[key]]));
    await api("/api/notification", {method: "POST", headers: {"Content-Type": "application/json", Accept: "application/json"}, body: JSON.stringify(supported)});
    await loadNotifications();
    $("notification-result").textContent = "配置已保存。可发送测试通知确认送达。";
  } catch (error) { $("notification-result").textContent = error.message; }
  finally { $("notification-save").disabled = false; $("notification-test").disabled = false; }
});
$("notification-test").addEventListener("click", async () => {
  $("notification-test").disabled = true; $("notification-save").disabled = true;
  $("notification-result").textContent = "正在测试已保存的配置…";
  try {
    const result = await api("/api/notification/test", {method: "POST", headers: {"Content-Type": "application/json", Accept: "application/json"}, body: JSON.stringify({channel: selectedChannel})});
    $("notification-result").textContent = result.reason;
  } catch (error) { $("notification-result").textContent = error.message; }
  finally { $("notification-test").disabled = false; $("notification-save").disabled = false; }
});
async function loadLogs() {
  const sequence = ++logSequence;
  const params = new URLSearchParams({n: "80", level: $("log-level").value, q: $("log-search").value});
  try {
    const data = await api(`/logs/clean?${params}`);
    if (sequence !== logSequence) return;
    const list = $("logs"), scrollTop = list.scrollTop;
    const labels = {info: "进度", warning: "提醒", success: "成功", error: "异常"};
    list.replaceChildren(...(data.entries.length ? data.entries.map(entry => {
      const row = node("div", "log-entry");
      const stamp = entry.timestamp?.match(/\d{2}:\d{2}:\d{2}/)?.[0] || "—";
      const time = node("time", "log-time", stamp); time.title = entry.timestamp;
      const text = node("span", "log-text", entry.text);
      if (entry.count > 1) text.append(node("span", "log-repeat", `×${entry.count}`));
      row.append(time, node("span", `log-level ${entry.level}`, labels[entry.level] || "进度"), text); return row;
    }) : [node("p", "empty-state", "暂无符合条件的日志") ]));
    list.scrollTop = $("log-follow").checked ? list.scrollHeight : scrollTop;
    $("log-count").textContent = `显示最近 ${data.entries.length} 条事件`;
  } catch (error) { if (sequence === logSequence) $("log-count").textContent = error.message; }
}
$("log-level").addEventListener("change", loadLogs);
$("log-search").addEventListener("input", () => { clearTimeout(logSearchTimer); logSearchTimer = setTimeout(loadLogs, 250); });
$("log-follow").addEventListener("change", () => { if ($("log-follow").checked) $("logs").scrollTop = $("logs").scrollHeight; });
async function readerAction(path) {
  actionPending = true; $("start-btn").disabled = true; $("restart-btn").disabled = true;
  try {
    await api(path, {method: "POST"});
    $("action-result").textContent = path === "/start" ? "已提交阅读任务，请稍候。" : "正在重新生成二维码，请稍候。";
  } catch (error) { $("action-result").textContent = error.message; }
  finally { actionPending = false; $("restart-btn").disabled = false; await refresh(); loadLogs(); setTimeout(refresh, 3000); }
}
$("start-btn").addEventListener("click", () => readerAction("/start"));
$("restart-btn").addEventListener("click", () => {
  $("restart-dialog").returnValue = "";
  $("restart-dialog").showModal();
});
$("restart-dialog").addEventListener("close", () => { if ($("restart-dialog").returnValue === "confirm") readerAction("/restart"); });
refreshTimer = setInterval(() => { refresh(); loadLogs(); }, refreshInterval);
refresh(); loadLogs();
