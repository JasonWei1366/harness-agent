// Browser client. It renders CodingSession state and events; it does not define them.
const USER_ID = browserUserId();

function browserUserId() {
  const key = "tau.userId";
  try {
    const saved = localStorage.getItem(key);
    if (saved && /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(saved)) return saved;
  } catch {
    // This browser is keeping the id for the page only.
  }
  const created = (window.crypto && crypto.randomUUID ? crypto.randomUUID() : String(Date.now()))
    .replace(/-/g, "");
  try {
    localStorage.setItem(key, created);
  } catch {
    // This browser is keeping the id for the page only.
  }
  return created;
}

const params = new URLSearchParams(location.search);
const apiBase = (params.get("api") || "").replace(/\/$/, "");
const api = (path) => apiBase + path;
function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  return fetch(api(path), { ...options, headers });
}

function postApi(path, body, signal) {
  return apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, userId: USER_ID }),
    signal,
  });
}

const transcript = document.querySelector("#transcript");
const input = document.querySelector("#input");
const error = document.querySelector("#error");
const hint = document.querySelector("#hint");
const sendButton = document.querySelector("#send");
const stopButton = document.querySelector("#stop");
const activity = document.querySelector("#activity");
const activityLabel = document.querySelector("#activity-label");
const statusLabel = document.querySelector("#status-label");
const sessionName = document.querySelector("#session-name");
const sessionFacts = document.querySelector("#session-facts");
const connectionNote = document.querySelector("#connection-note");
const contextFill = document.querySelector("#context-fill");
const contextUsage = document.querySelector("#context-usage");
const tokenUsage = document.querySelector("#token-usage");
const activityUsage = document.querySelector("#activity-usage");
const performanceUsage = document.querySelector("#performance-usage");
const extensionHeading = document.querySelector("#extension-heading");
const extensionList = document.querySelector("#extensions");
const toolHeading = document.querySelector("#tool-heading");
const toolList = document.querySelector("#tools");
const skillHeading = document.querySelector("#skill-heading");
const skillList = document.querySelector("#skills");
const promptHeading = document.querySelector("#prompt-heading");
const promptList = document.querySelector("#prompts");
const contextHeading = document.querySelector("#context-heading");
const contextFiles = document.querySelector("#context-files");
const systemPromptHeading = document.querySelector("#system-prompt-heading");
const systemPromptFiles = document.querySelector("#system-prompt-files");
const sessionList = document.querySelector("#session-list");

const roles = {
  user: "你",
  assistant: "Tau",
  toolResult: "工具",
  custom: "消息",
  bashExecution: "终端",
  compactionSummary: "压缩",
  branchSummary: "分支",
  tool: "工具",
};
const pickerFlags = [
  "modelPickerRequested",
  "scopedModelsPickerRequested",
  "resumePickerRequested",
  "promptsPickerRequested",
  "treePickerRequested",
  "loginPickerRequested",
  "customProviderLoginRequested",
  "localRequested",
  "sidebarToggleRequested",
  "logoutPickerRequested",
  "toolsPickerRequested",
  "skillsPickerRequested",
  "themePickerRequested",
  "loginProvider",
  "logoutProvider",
  "theme",
];

let session = {
  sessionName: "",
  provider: "",
  model: "",
  cwd: "",
  thinkingLevel: "",
  isStreaming: false,
  pendingMessageCount: 0,
};
let messages = [];
let draft = null;
let activeTools = [];
let notes = [];
let connection = "connecting";
let phase = "idle";
let retry = null;
let turnStartedAt = null;
let clock = 0;
let sending = false;

function isBusy(value) {
  return value === "starting" || value === "streaming" || value === "tools" || value === "stopping";
}

function applyPhase(next) {
  const wasBusy = isBusy(phase);
  const nowBusy = isBusy(next);
  if (nowBusy && !wasBusy) turnStartedAt = Date.now();
  if (!nowBusy) {
    turnStartedAt = null;
    retry = null;
  }
  phase = next;
  session.isStreaming = nowBusy;
  if (nowBusy && !clock) clock = setInterval(renderStatus, 1000);
  if (!nowBusy && clock) {
    clearInterval(clock);
    clock = 0;
  }
}

function reconcilePhase() {
  if (phase === "stopping") return;
  if (phase === "starting" && !session.isStreaming && !draft) {
    session.isStreaming = true;
    return;
  }
  if (activeTools.length) applyPhase("tools");
  else if (session.isStreaming || draft) applyPhase("streaming");
  else applyPhase("idle");
}

function formatElapsed(started) {
  const total = Math.max(0, Math.floor((Date.now() - started) / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return minutes + ":" + seconds;
}

function shortPath(cwd) {
  const parts = String(cwd).split(/[/\\]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : cwd;
}

function queueSuffix() {
  return session.pendingMessageCount ? "，后面还有 " + session.pendingMessageCount + " 条" : "";
}

function activitySentence() {
  const elapsed = turnStartedAt ? "，已经 " + formatElapsed(turnStartedAt) : "";
  if (retry) return "上一次请求失败，正在重试 " + retry.attempt + "/" + retry.max + elapsed;
  if (phase === "starting") return "正在开始这一轮" + queueSuffix();
  if (phase === "stopping") return "正在停止这一轮";
  if (phase === "tools") {
    const name = activeTools.length === 1 ? activeTools[0].name : activeTools.length + " 个工具";
    return "正在调用 " + name + elapsed + queueSuffix();
  }
  if (phase === "streaming") return "正在生成回复" + elapsed + queueSuffix();
  return "";
}

function pillText() {
  if (connection === "connecting") return "正在连接";
  if (connection === "reconnecting") return "正在重新连接";
  if (connection === "offline") return "连接中断";
  if (retry) return "正在重试 " + retry.attempt + "/" + retry.max;
  if (phase === "starting") return "正在开始";
  if (phase === "stopping") return "正在停止";
  if (phase === "tools") return "正在调用工具";
  if (phase === "streaming") {
    return session.pendingMessageCount ? "正在生成 · 排队 " + session.pendingMessageCount : "正在生成";
  }
  return session.pendingMessageCount ? "空闲 · 排队 " + session.pendingMessageCount : "空闲";
}

function renderStatus() {
  const linked = connection === "live";
  document.body.dataset.connection = connection;
  document.body.dataset.phase = phase;
  document.body.dataset.busy = isBusy(phase) ? "true" : "false";
  statusLabel.textContent = pillText();
  activity.hidden = !isBusy(phase);
  activityLabel.textContent = activitySentence();
  stopButton.disabled = !isBusy(phase) || phase === "stopping";
  stopButton.textContent = phase === "stopping" ? "正在停止" : "停止";
  sendButton.disabled = !linked || sending;
  sendButton.textContent = isBusy(phase) ? "排队" : "发送";
  hint.hidden = !error.hidden;
  hint.textContent = isBusy(phase)
    ? "这一轮还在进行。再次发送会排到后面。"
    : "Enter 发送，Shift+Enter 换行。";
  sessionName.textContent = session.sessionName || "新会话";
  const sessionUser = document.querySelector("#session-user");
  if (sessionUser) {
    const shown = session.userId || USER_ID;
    sessionUser.textContent = shown;
    sessionUser.title = shown;
  }
  const facts = [];
  if (session.provider || session.model) {
    facts.push([session.provider, session.model].filter(Boolean).join(" / "));
  }
  if (session.cwd) facts.push(shortPath(session.cwd));
  sessionFacts.textContent = facts.join("  ·  ");
  sessionFacts.title = session.cwd || "";
  connectionNote.hidden = linked;
  connectionNote.textContent = connection === "offline"
    ? "连接已断开。请确认启动 tau web 的终端仍在运行。"
    : connection === "reconnecting"
      ? "与服务的连接中断了，正在重新连接。"
      : "正在连接服务。";
  document.title = (linked && !isBusy(phase) ? "Tau" : pillText() + " · Tau");
  renderInspector();
}

function renderInspector() {
  if (!Array.isArray(session.tools)) return;
  const used = Number(session.contextTokens) || 0;
  const limit = Number(session.contextWindow) || 0;
  const ratio = limit > 0 ? Math.min(1, used / limit) : 0;
  contextFill.style.width = (ratio * 100).toFixed(1) + "%";
  const usedLabel = session.usesProviderUsage ? formatTokens(used) : "约 " + formatTokens(used);
  contextUsage.textContent = usedLabel + " / " + (limit ? formatTokens(limit) : "—") + " 上下文";
  let tokens = formatTokens(session.inputTokens) + " 输入 · " + formatTokens(session.outputTokens) + " 输出";
  if (typeof session.estimatedCost === "number") tokens += " · " + formatCost(session.estimatedCost);
  if (typeof session.cacheHitRate === "number") {
    tokens += " · 缓存 " + Math.round(session.cacheHitRate * 100) + "%";
  }
  tokenUsage.textContent = tokens;
  const activityParts = [
    (Number(session.turnCount) || 0) + " 轮",
    (Number(session.toolCallCount) || 0) + " 次工具调用",
  ];
  if (session.thinkingLevel) activityParts.push("思考 " + session.thinkingLevel);
  activityParts.push(
    session.autoCompactTokens ? "压缩 " + formatTokens(session.autoCompactTokens) : "压缩关闭",
  );
  activityUsage.textContent = activityParts.join(" · ");
  const performance = [];
  if (typeof session.outputTokensPerSecond === "number") {
    performance.push("TPS " + session.outputTokensPerSecond.toFixed(1));
  }
  if (typeof session.averageTimeToFirstOutputMs === "number") {
    performance.push("TTFT " + Math.round(session.averageTimeToFirstOutputMs) + "ms");
  }
  performanceUsage.hidden = !performance.length;
  performanceUsage.textContent = performance.join(" · ");

  const extensions = Array.isArray(session.extensions) ? session.extensions : [];
  extensionHeading.textContent = "插件" + (extensions.length ? " " + extensions.length : "");
  fillChips(extensionList, extensions.map((name) => ({ text: name })), "没有加载插件");

  const tools = Array.isArray(session.tools) ? session.tools : [];
  toolHeading.textContent = "工具 " + tools.length;
  fillChips(
    toolList,
    tools.map((tool) => ({
      text: tool.label || tool.name,
      extension: Boolean(tool.extension),
      title: (tool.extension || "内置") + (tool.description ? "\n" + tool.description : ""),
    })),
    "没有可用工具",
  );

  const skills = Array.isArray(session.skills) ? session.skills : [];
  skillHeading.textContent = "技能" + (skills.length ? " " + skills.length : "");
  fillChips(
    skillList,
    skills.map((skill) => ({
      text: skill.name,
      title: skill.description || skill.name,
    })),
    "没有技能",
  );

  const prompts = Array.isArray(session.prompts) ? session.prompts : [];
  promptHeading.textContent = "提示词" + (prompts.length ? " " + prompts.length : "");
  fillChips(
    promptList,
    prompts.map((prompt) => ({
      text: prompt.name,
      title: prompt.description || prompt.name,
    })),
    "没有提示词",
  );

  const files = Array.isArray(session.contextFiles) ? session.contextFiles : [];
  contextHeading.textContent = "上下文" + (files.length ? " " + files.length : "");
  fillChips(contextFiles, files.map((name) => ({ text: name })), "没有项目说明");

  const promptFiles = Array.isArray(session.systemPromptFiles) ? session.systemPromptFiles : [];
  systemPromptHeading.textContent = "系统提示" + (promptFiles.length ? " " + promptFiles.length : "");
  fillChips(systemPromptFiles, promptFiles.map((name) => ({ text: name })), "没有系统提示文件");
  renderSessionChoices();
}

function fillChips(container, items, empty) {
  container.replaceChildren();
  if (!items.length) {
    const note = document.createElement("p");
    note.className = "quiet";
    note.textContent = empty;
    container.append(note);
    return;
  }
  for (const item of items) {
    const chip = document.createElement("span");
    chip.className = "chip" + (item.extension ? " extension" : "");
    chip.textContent = item.text;
    if (item.title) chip.title = item.title;
    container.append(chip);
  }
}

function formatTokens(value) {
  const count = Number(value) || 0;
  if (count < 1000) return String(count);
  if (count < 10000) return (count / 1000).toFixed(1).replace(/\.0$/, "") + "k";
  return Math.round(count / 1000) + "k";
}

function formatCost(value) {
  if (value > 0 && value < 0.01) return "$" + value.toFixed(3);
  return "$" + value.toFixed(2);
}

function render() {
  renderStatus();
  const nearBottom = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 80;
  transcript.replaceChildren();
  if (!messages.length && !draft && !activeTools.length && !notes.length) {
    transcript.append(renderEmpty());
  }
  for (const message of messages) transcript.append(renderMessage(toDisplay(message), false));
  if (draft) transcript.append(renderMessage(toDisplay(draft), true));
  for (const tool of activeTools) transcript.append(renderActiveTool(tool));
  for (const notice of notes) transcript.append(renderNotice(notice));
  if (nearBottom) transcript.scrollTop = transcript.scrollHeight;
}

function renderEmpty() {
  const row = document.createElement("div");
  row.className = "empty";
  const title = document.createElement("strong");
  title.textContent = "描述一件要做的事";
  const body = document.createElement("p");
  body.textContent = "Tau 会在这里回复。以 / 开头运行命令，以 ! 开头运行终端。";
  row.append(title, body);
  return row;
}

function renderMessage(message, streaming) {
  const row = document.createElement("article");
  row.className = "message " + (message.role || "assistant") + (streaming ? " live" : "");
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const who = document.createElement("div");
  who.className = "who";
  const name = roles[message.role] || message.role || "消息";
  who.textContent = name + (streaming ? " · 生成中" : "") + (message.toolName ? " · " + message.toolName : "");
  bubble.append(who);
  if (message.thinking) {
    const thinking = document.createElement("pre");
    thinking.className = "thinking";
    const label = document.createElement("span");
    label.textContent = "思考";
    thinking.append(label, "\n" + message.thinking);
    bubble.append(thinking);
  }
  const body = document.createElement("pre");
  body.className = "body";
  body.textContent = message.text || "";
  if (streaming) body.append(caret());
  if (message.text || streaming) bubble.append(body);
  if (message.errorMessage) {
    const failure = document.createElement("pre");
    failure.className = "failure";
    failure.textContent = message.errorMessage;
    bubble.append(failure);
  }
  for (const call of message.toolCalls || []) bubble.append(renderCall(call.name, call.arguments));
  row.append(bubble);
  return row;
}

function renderActiveTool(tool) {
  const row = document.createElement("article");
  row.className = "message tool live";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const who = document.createElement("div");
  who.className = "who";
  who.textContent = "正在运行";
  bubble.append(who, renderCall(tool.name, tool.arguments));
  row.append(bubble);
  return row;
}

function renderNotice(notice) {
  const row = document.createElement("article");
  row.className = "message notice";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const who = document.createElement("div");
  who.className = "who";
  who.textContent = "提示";
  const body = document.createElement("pre");
  body.className = "body";
  body.textContent = notice;
  bubble.append(who, body);
  row.append(bubble);
  return row;
}

function renderCall(name, args) {
  const line = document.createElement("pre");
  line.className = "call";
  const title = document.createElement("b");
  title.textContent = name || "工具";
  line.append(title);
  const detail = formatArgs(args);
  if (detail) line.append("\n" + detail);
  return line;
}

function caret() {
  const mark = document.createElement("span");
  mark.className = "caret";
  return mark;
}

function formatArgs(args) {
  if (!args || typeof args !== "object") return "";
  return Object.entries(args).map(([key, value]) => {
    const shown = typeof value === "string" ? value : JSON.stringify(value);
    const clipped = shown.length > 180 ? shown.slice(0, 180) + "…" : shown;
    return key + ": " + clipped;
  }).join("\n");
}

function toDisplay(message) {
  const content = message.content;
  let text = "";
  let thinking = "";
  const toolCalls = [];
  if (typeof content === "string") text = content;
  else if (Array.isArray(content)) {
    for (const block of content) {
      if (!block) continue;
      if (block.type === "thinking") thinking += block.thinking || "";
      else if (block.type === "toolCall") toolCalls.push({ name: block.name, arguments: block.arguments || {} });
      else if (block.text) text += block.text;
    }
  }
  if (!text) text = message.text || message.output || message.summary || "";
  return {
    role: message.role,
    text,
    thinking,
    toolCalls,
    errorMessage: message.errorMessage,
    toolName: message.toolName,
  };
}

function applyEvent(event) {
  let data;
  try {
    data = JSON.parse(event.data);
  } catch {
    return;
  }
  const type = data.type;
  if ((type === "message_start" || type === "message_update") && data.message?.role === "assistant") {
    draft = data.message;
    retry = null;
    applyPhase(activeTools.length ? "tools" : "streaming");
    render();
    return;
  }
  if (type === "message_end" && data.message) {
    messages = messages.concat([data.message]);
    if (data.message.role === "assistant") draft = null;
    render();
    refreshState();
    return;
  }
  if (type === "tool_execution_start") {
    activeTools = activeTools.concat([
      { id: data.toolCallId, name: data.toolName, arguments: data.args || {} },
    ]);
    applyPhase("tools");
    render();
    return;
  }
  if (type === "tool_execution_end") {
    activeTools = activeTools.filter((tool) => tool.id !== data.toolCallId);
    if (phase !== "stopping") applyPhase(activeTools.length ? "tools" : "streaming");
    render();
    return;
  }
  if (type === "agent_settled") {
    draft = null;
    activeTools = [];
    session.pendingMessageCount = 0;
    applyPhase("idle");
    stopEvents();
    render();
    refreshState();
    return;
  }
  if (type === "queue_update") {
    session.pendingMessageCount = (data.followUp || []).length + (data.steering || []).length;
    renderStatus();
    return;
  }
  if (type === "error") {
    notes = notes.concat([data.error || "请求失败"]);
    draft = null;
    activeTools = [];
    applyPhase("idle");
    stopEvents();
    render();
    return;
  }
  if (type === "session_info_changed") {
    if (data.name) session.sessionName = data.name;
    renderStatus();
    return;
  }
  if (type === "thinking_level_changed") {
    session.thinkingLevel = data.level || "";
    renderStatus();
    return;
  }
  if (type === "auto_retry_start") {
    retry = { attempt: data.attempt || 1, max: data.maxAttempts || data.attempt || 1 };
    if (!isBusy(phase)) applyPhase("streaming");
    render();
    return;
  }
  if (type === "auto_retry_end") {
    retry = null;
    renderStatus();
  }
}

async function reloadSession() {
  if (!session.sessionId) return;
  try {
    const [stateResponse, messageResponse] = await Promise.all([
      postApi("/api/session", { action: "state", sessionId: session.sessionId }),
      postApi("/api/session", { action: "messages", sessionId: session.sessionId }),
    ]);
    if (!stateResponse.ok || !messageResponse.ok) throw new Error("无法读取会话");
    session = await stateResponse.json();
    const payload = await messageResponse.json();
    messages = Array.isArray(payload.messages) ? payload.messages : [];
    if (connection === "connecting") connection = "live";
    reconcilePhase();
    render();
  } catch (err) {
    showFailure({ error: err.message || "无法读取会话" });
    renderStatus();
  }
}

async function refreshState() {
  if (!session.sessionId) return;
  try {
    const response = await postApi("/api/session", { action: "state", sessionId: session.sessionId });
    if (!response.ok) return;
    const next = await response.json();
    session = next;
    if (isBusy(phase)) session.isStreaming = true;
    renderStatus();
  } catch {
    // The event stream still reports whether the turn is running.
  }
}

function renderSessionChoices() {
  const sessions = Array.isArray(session.sessions) ? session.sessions : [];
  const items = sessions.filter((item) => item && item.id);
  if (session.sessionId && !items.some((item) => item.id === session.sessionId)) {
    items.unshift({
      id: session.sessionId,
      title: session.sessionName || "",
      preview: "",
      model: session.model,
      cwd: session.cwd,
      updatedAt: null,
    });
  }
  const signature = items
    .map((item) => [item.id, item.title, item.preview, item.updatedAt, item.cwd].join("\n"))
    .join("\n\n");
  if (sessionList.dataset.signature === signature) return;
  sessionList.dataset.signature = signature;
  sessionList.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "quiet";
    empty.textContent = "还没有历史会话";
    sessionList.append(empty);
    return;
  }
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.sessionId = item.id;
    button.setAttribute("role", "option");
    const current = item.id === session.sessionId;
    if (current) {
      button.className = "current";
      button.setAttribute("aria-selected", "true");
    }
    const title = document.createElement("strong");
    title.textContent = item.title || item.preview || "未命名会话";
    button.append(title);
    if (item.title && item.preview && item.preview !== item.title) {
      const quote = document.createElement("small");
      quote.textContent = item.preview;
      button.append(quote);
    }
    const meta = document.createElement("small");
    const bits = [formatUpdated(item.updatedAt)];
    if (item.model) bits.push(item.model);
    if (item.cwd && session.cwd && item.cwd !== session.cwd) bits.push(shortPath(item.cwd));
    meta.textContent = bits.join(" · ");
    button.append(meta);
    sessionList.append(button);
  }
}

function formatUpdated(value) {
  if (typeof value !== "number") return "刚刚";
  const delta = Date.now() / 1000 - value;
  if (delta < 60) return "刚刚";
  if (delta < 3600) return Math.floor(delta / 60) + " 分钟前";
  if (delta < 86400) return Math.floor(delta / 3600) + " 小时前";
  if (delta < 86400 * 7) return Math.floor(delta / 86400) + " 天前";
  const date = new Date(value * 1000);
  return date.getMonth() + 1 + "月" + date.getDate() + "日";
}

let eventRequest = null;
let followTurn = false;

function stopEvents() {
  followTurn = false;
  if (eventRequest) eventRequest.abort();
  eventRequest = null;
}

function connect() {
  if (eventRequest) eventRequest.abort();
  const controller = new AbortController();
  let resolveReady = () => {};
  const ready = new Promise((resolve) => {
    resolveReady = resolve;
  });
  controller.resolveReady = () => {
    resolveReady();
    controller.resolveReady = () => {};
  };
  eventRequest = controller;
  followTurn = true;
  if (!session.sessionId) {
    controller.resolveReady();
    return ready;
  }
  consumeEvents(session.sessionId, controller).catch(() => {
    if (controller.signal.aborted || !followTurn) return;
    connection = "offline";
    renderStatus();
  });
  return ready;
}

async function ensureEvents() {
  if (followTurn && eventRequest && !eventRequest.signal.aborted) return;
  await Promise.race([connect(), wait(2000)]);
}

async function consumeEvents(sessionId, controller) {
  if (controller.signal.aborted || !followTurn || session.sessionId !== sessionId) return;
  let response;
  try {
    response = await postApi("/api/events", { sessionId }, controller.signal);
  } catch (err) {
    if (controller.signal.aborted || err.name === "AbortError" || !followTurn) return;
    connection = "reconnecting";
    renderStatus();
    await wait(1000);
    if (!controller.signal.aborted && followTurn && session.sessionId === sessionId) {
      await consumeEvents(sessionId, controller);
    }
    return;
  }
  if (controller.signal.aborted || !followTurn || session.sessionId !== sessionId) return;
  if (!response.ok || !response.body) {
    controller.resolveReady();
    connection = response.status === 400 ? "offline" : "reconnecting";
    renderStatus();
    if (connection === "offline") return;
    await wait(1000);
    if (!controller.signal.aborted && followTurn && session.sessionId === sessionId) {
      await consumeEvents(sessionId, controller);
    }
    return;
  }
  connection = "live";
  controller.resolveReady();
  renderStatus();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      buffer = drainEvents(buffer);
    }
  } catch (err) {
    if (controller.signal.aborted || err.name === "AbortError" || !followTurn) return;
  }
  if (controller.signal.aborted || !followTurn || session.sessionId !== sessionId) return;
  connection = "reconnecting";
  renderStatus();
  await wait(1000);
  if (!controller.signal.aborted && followTurn && session.sessionId === sessionId) {
    await consumeEvents(sessionId, controller);
  }
}

function drainEvents(buffer) {
  let split = buffer.indexOf("\n\n");
  while (split !== -1) {
    const raw = buffer.slice(0, split);
    buffer = buffer.slice(split + 2);
    const data = raw
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (data) applyEvent({ data });
    split = buffer.indexOf("\n\n");
  }
  return buffer;
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function showFailure(body) {
  error.hidden = false;
  error.textContent = body.error || "发送失败";
  renderStatus();
}

function classify(text) {
  const trimmed = text.trim();
  if (trimmed.startsWith("!")) return "shell";
  if (trimmed.startsWith("/")) return "command";
  return "prompt";
}

document.querySelector("#composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (sending) return;
  const text = input.value;
  if (!text.trim()) return;
  error.hidden = true;
  const kind = classify(text);
  const wasBusy = isBusy(phase);
  input.value = "";
  if (kind === "prompt" && !wasBusy) applyPhase("starting");
  sending = true;
  render();
  try {
    if (kind === "prompt") await ensureEvents();
    const response = await send(text, kind === "prompt" && wasBusy);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (kind === "prompt" && !wasBusy) {
        applyPhase("idle");
        stopEvents();
      }
      input.value = text;
      showFailure(body);
      return;
    }
    if (kind === "command") showCommand(body);
    if (kind === "shell") {
      notes = notes.concat(["$ " + (body.command || "") + "\n" + (body.output || "")]);
      if (body.addedToContext) await reloadSession();
      else render();
    }
  } catch {
    if (kind === "prompt" && !wasBusy) {
      applyPhase("idle");
      stopEvents();
    }
    input.value = text;
    showFailure({ error: "无法发送，请检查连接。" });
  } finally {
    sending = false;
    renderStatus();
  }
});

async function send(text, queue) {
  const trimmed = text.trim();
  const sessionId = session.sessionId;
  if (trimmed.startsWith("!!")) {
    return postApi("/api/session", {
      action: "terminal",
      sessionId,
      command: trimmed.slice(2).trim(),
      addToContext: false,
    });
  }
  if (trimmed.startsWith("!")) {
    return postApi("/api/session", {
      action: "terminal",
      sessionId,
      command: trimmed.slice(1).trim(),
      addToContext: true,
    });
  }
  if (trimmed.startsWith("/")) {
    return postApi("/api/session", { action: "command", sessionId, text: trimmed });
  }
  const payload = { action: "prompt", sessionId, message: trimmed };
  if (queue) payload.streamingBehavior = "followUp";
  return postApi("/api/session", payload);
}

function showCommand(result) {
  const lines = [];
  if (result.message) lines.push(result.message);
  if (pickerFlags.some((name) => result[name])) lines.push("这个操作要在终端里完成。");
  if (result.exitRequested) lines.push("网页服务会继续运行。在启动它的终端里按 Ctrl+C 结束。");
  if (lines.length) notes = notes.concat([lines.join("\n")]);
  const nextId = result.sessionId;
  const moved = Boolean(nextId && nextId !== session.sessionId);
  if (nextId) session.sessionId = nextId;
  if (result.newSessionRequested || result.resumeSessionId || moved) {
    draft = null;
    activeTools = [];
    applyPhase("idle");
    stopEvents();
    reloadSession().then(() => {
      if (session.isStreaming) ensureEvents();
    });
    return;
  }
  render();
}

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    document.querySelector("#composer").requestSubmit();
  }
});

stopButton.addEventListener("click", async () => {
  if (!isBusy(phase) || phase === "stopping") return;
  applyPhase("stopping");
  render();
  try {
    const response = await postApi("/api/session", { action: "abort", sessionId: session.sessionId });
    if (!response.ok) throw new Error("无法停止这一轮");
  } catch {
    applyPhase(activeTools.length ? "tools" : "streaming");
    showFailure({ error: "无法停止，请检查连接。" });
  }
});

sessionList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-session-id]");
  if (!button || button.dataset.sessionId === session.sessionId) return;
  activateSession(button.dataset.sessionId);
});

document.querySelector("#new-session").addEventListener("click", () => {
  activateSession(null);
});

async function activateSession(sessionId) {
  const response = await postApi("/api/sessions", sessionId ? { sessionId } : { create: true });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    showFailure(body);
    return;
  }
  session = body;
  messages = [];
  draft = null;
  activeTools = [];
  notes = [];
  retry = null;
  applyPhase(session.isStreaming ? "streaming" : "idle");
  const messageResponse = await postApi("/api/session", {
    action: "messages",
    sessionId: session.sessionId,
  });
  if (messageResponse.ok) {
    const payload = await messageResponse.json();
    messages = Array.isArray(payload.messages) ? payload.messages : [];
  }
  stopEvents();
  connection = "live";
  if (session.isStreaming) ensureEvents();
  render();
}

function preferredSession(sessions) {
  const items = (sessions || []).filter((item) => item && item.id);
  let best = null;
  for (const item of items) {
    if (typeof item.updatedAt !== "number") continue;
    if (!best || item.updatedAt > best.updatedAt) best = item;
  }
  return best || items[0] || null;
}

async function boot() {
  renderStatus();
  try {
    const listed = await postApi("/api/sessions", {});
    const body = await listed.json();
    if (!listed.ok) {
      showFailure(body);
      return;
    }
    const first = preferredSession(body.sessions);
    if (!first) {
      await activateSession(null);
      return;
    }
    session.sessionId = first.id;
  } catch {
    showFailure({ error: "无法读取会话" });
    return;
  }
  await reloadSession();
  if (session.isStreaming) ensureEvents();
}

boot();
