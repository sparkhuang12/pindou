"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const elements = {
  app: $("#admin-app"),
  denied: $("#admin-denied"),
  deniedMessage: $("#admin-denied-message"),
  identity: $("#admin-identity"),
  overview: $("#overview-grid"),
  usersBody: $("#users-body"),
  userSearch: $("#user-search"),
  userStatus: $("#user-status"),
  reloadUsers: $("#reload-users"),
  projectGrid: $("#admin-project-grid"),
  projectSearch: $("#project-search"),
  reloadProjects: $("#reload-projects"),
  activityList: $("#activity-list"),
  activitySearch: $("#activity-search"),
  activityStatus: $("#activity-status"),
  reloadActivity: $("#reload-activity"),
  jobsList: $("#jobs-list"),
  reloadJobs: $("#reload-jobs"),
  messageList: $("#admin-message-list"),
  messageStatus: $("#message-status"),
  reloadMessages: $("#reload-messages"),
  detailDialog: $("#user-detail-dialog"),
  detailTitle: $("#user-detail-title"),
  detailContent: $("#user-detail-content"),
  toastRegion: $("#toast-region"),
};

const state = { user: null, activeView: "users" };

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  const data = (response.headers.get("content-type") || "").includes("application/json")
    ? await response.json()
    : null;
  if (!response.ok) throw new Error(data?.detail || `请求失败（${response.status}）`);
  return data;
}

function toast(message, kind = "success") {
  const item = document.createElement("div");
  item.className = `toast${kind === "error" ? " is-error" : ""}`;
  item.textContent = message;
  elements.toastRegion.append(item);
  window.setTimeout(() => item.remove(), 3600);
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function formatDate(value) {
  if (!value) return "从未";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function appendTextCell(row, text, className = "") {
  const cell = document.createElement("td");
  if (className) cell.className = className;
  cell.textContent = text;
  row.append(cell);
  return cell;
}

function emptyState(container, text) {
  container.replaceChildren();
  const empty = document.createElement("p");
  empty.className = "admin-empty";
  empty.textContent = text;
  container.append(empty);
}

function jsonDetails(label, value) {
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  const pre = document.createElement("pre");
  summary.textContent = label;
  pre.textContent = JSON.stringify(value || {}, null, 2);
  details.append(summary, pre);
  return details;
}

async function loadOverview() {
  const data = await api("/api/admin/overview");
  const cards = [
    ["用户", data.overview.users],
    ["历史项目", data.overview.projects],
    ["存储占用", formatBytes(data.overview.storage_bytes)],
    ["审计记录", data.overview.activities],
    ["失败请求", data.overview.failed_requests],
    ["待处理消息", data.overview.open_messages],
    ["模型任务", data.overview.model_jobs],
  ];
  elements.overview.replaceChildren();
  for (const [label, value] of cards) {
    const card = document.createElement("article");
    const title = document.createElement("span");
    const number = document.createElement("b");
    title.textContent = label;
    number.textContent = Number.isFinite(value) ? Number(value).toLocaleString("zh-CN") : value;
    card.append(title, number);
    elements.overview.append(card);
  }
}

async function loadUsers() {
  const params = new URLSearchParams();
  if (elements.userSearch.value.trim()) params.set("query", elements.userSearch.value.trim());
  if (elements.userStatus.value) params.set("status", elements.userStatus.value);
  const data = await api(`/api/admin/users?${params}`);
  elements.usersBody.replaceChildren();
  for (const user of data.users) {
    const row = document.createElement("tr");
    const identity = document.createElement("td");
    const name = document.createElement("b");
    const email = document.createElement("small");
    name.textContent = user.display_name;
    email.textContent = user.email;
    identity.append(name, email);
    row.append(identity);

    const roleCell = document.createElement("td");
    const role = document.createElement("select");
    role.setAttribute("aria-label", `${user.display_name} 的角色`);
    role.append(new Option("用户", "user"), new Option("管理员", "admin"));
    role.value = user.role;
    roleCell.append(role);
    row.append(roleCell);

    const statusCell = document.createElement("td");
    const status = document.createElement("select");
    status.setAttribute("aria-label", `${user.display_name} 的状态`);
    status.append(new Option("正常", "active"), new Option("停用", "disabled"));
    status.value = user.status;
    statusCell.append(status);
    row.append(statusCell);

    appendTextCell(row, String(user.project_count));
    appendTextCell(row, formatBytes(user.storage_bytes));
    appendTextCell(row, formatDate(user.last_login_at));

    const actions = document.createElement("td");
    actions.className = "admin-row-actions";
    const detail = document.createElement("button");
    const save = document.createElement("button");
    detail.className = "button button-quiet";
    save.className = "button button-secondary";
    detail.type = save.type = "button";
    detail.textContent = "详情";
    save.textContent = "保存";
    detail.addEventListener("click", () => openUserDetail(user.id));
    save.addEventListener("click", async () => {
      save.disabled = true;
      try {
        await api(`/api/admin/users/${user.id}`, {
          method: "PUT",
          body: JSON.stringify({ role: role.value, status: status.value }),
        });
        toast("用户权限已更新。");
        await Promise.all([loadUsers(), loadOverview()]);
      } catch (error) {
        toast(error.message, "error");
      } finally {
        save.disabled = false;
      }
    });
    actions.append(detail, save);
    row.append(actions);
    elements.usersBody.append(row);
  }
  if (!data.users.length) {
    const row = document.createElement("tr");
    const cell = appendTextCell(row, "没有符合条件的用户。", "admin-empty-cell");
    cell.colSpan = 7;
    elements.usersBody.append(row);
  }
}

function summaryList(items) {
  const list = document.createElement("div");
  list.className = "admin-detail-list";
  for (const [label, value] of items) {
    const item = document.createElement("div");
    const term = document.createElement("span");
    const detail = document.createElement("b");
    term.textContent = label;
    detail.textContent = value;
    item.append(term, detail);
    list.append(item);
  }
  return list;
}

async function openUserDetail(userId) {
  try {
    const data = await api(`/api/admin/users/${userId}`);
    elements.detailTitle.textContent = `${data.user.display_name} / ${data.user.email}`;
    elements.detailContent.replaceChildren();
    elements.detailContent.append(summaryList([
      ["角色", data.user.role],
      ["状态", data.user.status],
      ["历史项目", String(data.usage.projects)],
      ["存储", formatBytes(data.usage.storage_bytes)],
      ["累计拼豆", Number(data.usage.beads).toLocaleString("zh-CN")],
      ["登录次数", String(data.user.login_count)],
      ["最近登录 IP", data.user.last_login_ip || "未记录"],
    ]));
    const projectTitle = document.createElement("h3");
    projectTitle.textContent = "最近项目";
    elements.detailContent.append(projectTitle);
    const projectGrid = document.createElement("div");
    projectGrid.className = "admin-project-grid compact";
    renderProjects(data.projects.slice(0, 6), projectGrid);
    elements.detailContent.append(projectGrid);
    elements.detailContent.append(jsonDetails("最近处理任务", data.jobs.slice(0, 10)));
    elements.detailContent.append(jsonDetails("最近使用记录", data.activities.slice(0, 10)));
    elements.detailDialog.showModal();
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderProjects(projects, target = elements.projectGrid) {
  target.replaceChildren();
  if (!projects.length) {
    emptyState(target, "没有历史项目。");
    return;
  }
  for (const project of projects) {
    const card = document.createElement("article");
    const image = document.createElement("img");
    const body = document.createElement("div");
    const title = document.createElement("b");
    const owner = document.createElement("span");
    const detail = document.createElement("small");
    image.alt = project.name;
    image.loading = "lazy";
    image.src = project.assets.preview || project.assets.painted || project.assets.stylized || project.assets.cutout || project.assets.source;
    title.textContent = project.name;
    owner.textContent = project.user_email || `${project.source_width} × ${project.source_height}px`;
    detail.textContent = `${project.status} / ${project.cols}×${project.rows} 格 / ${formatBytes(project.storage_bytes)}`;
    body.append(title, owner, detail);
    card.append(image, body);
    target.append(card);
  }
}

async function loadProjects() {
  const params = new URLSearchParams();
  if (elements.projectSearch.value.trim()) params.set("query", elements.projectSearch.value.trim());
  const data = await api(`/api/admin/projects?${params}`);
  renderProjects(data.projects);
}

function auditCard(item, kind = "activity") {
  const card = document.createElement("article");
  const head = document.createElement("div");
  const titleWrap = document.createElement("div");
  const title = document.createElement("b");
  const meta = document.createElement("span");
  const status = document.createElement("em");
  title.textContent = kind === "job" ? item.operation : item.action;
  meta.textContent = `${item.user_email || "匿名"} / ${formatDate(item.started_at || item.created_at)} / ${item.duration_ms || 0} ms`;
  status.textContent = item.status;
  status.className = item.status === "failed" ? "is-failed" : "";
  titleWrap.append(title, meta);
  head.append(titleWrap, status);
  card.append(head);
  if (kind === "job") {
    const sub = document.createElement("p");
    sub.textContent = `${item.provider}${item.model_name ? ` / ${item.model_name}` : ""}${item.project_name ? ` / ${item.project_name}` : ""}`;
    card.append(sub, jsonDetails("输入内容", item.input), jsonDetails("输出内容", item.output));
  } else {
    const sub = document.createElement("p");
    sub.textContent = `${item.method || item.category} ${item.path || ""}`.trim();
    card.append(sub, jsonDetails("输入摘要", item.input), jsonDetails("输出摘要", item.output));
  }
  if (item.error_message) {
    const error = document.createElement("p");
    error.className = "audit-error";
    error.textContent = item.error_message;
    card.append(error);
  }
  return card;
}

async function loadActivity() {
  const params = new URLSearchParams({ limit: "150" });
  if (elements.activitySearch.value.trim()) params.set("action", elements.activitySearch.value.trim());
  if (elements.activityStatus.value) params.set("status", elements.activityStatus.value);
  const data = await api(`/api/admin/activity?${params}`);
  elements.activityList.replaceChildren(...data.activities.map((item) => auditCard(item)));
  if (!data.activities.length) emptyState(elements.activityList, "没有符合条件的使用记录。");
}

async function loadJobs() {
  const data = await api("/api/admin/jobs?limit=150");
  elements.jobsList.replaceChildren(...data.jobs.map((item) => auditCard(item, "job")));
  if (!data.jobs.length) emptyState(elements.jobsList, "还没有图片处理任务。");
}

async function loadMessages() {
  const params = new URLSearchParams();
  if (elements.messageStatus.value) params.set("status", elements.messageStatus.value);
  const data = await api(`/api/admin/messages?${params}`);
  elements.messageList.replaceChildren();
  for (const message of data.messages) {
    const card = document.createElement("article");
    const head = document.createElement("div");
    const titleWrap = document.createElement("div");
    const title = document.createElement("b");
    const meta = document.createElement("span");
    const content = document.createElement("p");
    const controls = document.createElement("div");
    const status = document.createElement("select");
    const note = document.createElement("textarea");
    const save = document.createElement("button");
    title.textContent = message.subject;
    meta.textContent = `${message.user_name} / ${message.user_email} / ${formatDate(message.created_at)}`;
    content.textContent = message.content;
    status.append(new Option("待查看", "open"), new Option("处理中", "read"), new Option("已解决", "resolved"));
    status.value = message.status;
    note.rows = 2;
    note.maxLength = 2000;
    note.placeholder = "管理员备注或回复摘要";
    note.value = message.admin_note || "";
    save.className = "button button-primary";
    save.type = "button";
    save.textContent = "保存处理结果";
    save.addEventListener("click", async () => {
      save.disabled = true;
      try {
        await api(`/api/admin/messages/${message.id}`, {
          method: "PUT",
          body: JSON.stringify({ status: status.value, admin_note: note.value.trim() }),
        });
        toast("消息状态已更新。");
        await Promise.all([loadMessages(), loadOverview()]);
      } catch (error) {
        toast(error.message, "error");
      } finally {
        save.disabled = false;
      }
    });
    titleWrap.append(title, meta);
    head.append(titleWrap, status);
    controls.append(note, save);
    card.append(head, content, controls);
    elements.messageList.append(card);
  }
  if (!data.messages.length) emptyState(elements.messageList, "没有符合条件的用户消息。");
}

async function activateView(view) {
  state.activeView = view;
  $$(".admin-tab").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.adminView === view));
  $$(".admin-panel").forEach((panel) => { panel.hidden = panel.id !== `admin-panel-${view}`; });
  try {
    await { users: loadUsers, projects: loadProjects, activity: loadActivity, jobs: loadJobs, messages: loadMessages }[view]();
  } catch (error) {
    toast(error.message, "error");
  }
}

function bindEvents() {
  $$(".admin-tab").forEach((tab) => tab.addEventListener("click", () => activateView(tab.dataset.adminView)));
  elements.reloadUsers.addEventListener("click", loadUsers);
  elements.reloadProjects.addEventListener("click", loadProjects);
  elements.reloadActivity.addEventListener("click", loadActivity);
  elements.reloadJobs.addEventListener("click", loadJobs);
  elements.reloadMessages.addEventListener("click", loadMessages);
  [elements.userSearch, elements.projectSearch, elements.activitySearch].forEach((input) => {
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") activateView(state.activeView);
    });
  });
}

async function initialize() {
  bindEvents();
  const theme = localStorage.getItem("pindou-theme");
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  try {
    const data = await api("/api/auth/me");
    if (data.user.role !== "admin") throw new Error("当前账户不是管理员");
    state.user = data.user;
    elements.identity.textContent = `${data.user.display_name} / 管理员`;
    elements.app.hidden = false;
    await Promise.all([loadOverview(), loadUsers()]);
  } catch (error) {
    elements.denied.hidden = false;
    elements.deniedMessage.textContent = error.message;
    elements.identity.textContent = "无管理权限";
  }
}

initialize();
