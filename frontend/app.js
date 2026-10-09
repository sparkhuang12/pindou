"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const elements = {
  authView: $("#auth-view"),
  appView: $("#app-view"),
  authForm: $("#auth-form"),
  authError: $("#auth-error"),
  authTitle: $("#auth-form-title"),
  authSubtitle: $("#auth-form-subtitle"),
  authSubmit: $("#auth-submit"),
  loginTab: $("#login-tab"),
  registerTab: $("#register-tab"),
  displayNameField: $("#display-name-field"),
  displayName: $("#display-name"),
  email: $("#email"),
  password: $("#password"),
  passwordHelp: $("#password-help"),
  projectList: $("#project-list"),
  projectCount: $("#project-count"),
  fileInput: $("#file-input"),
  newProjectButton: $("#new-project-button"),
  sidebarUpload: $("#sidebar-upload"),
  emptyUpload: $("#empty-upload"),
  emptyWorkspace: $("#empty-workspace"),
  canvasStage: $("#canvas-stage"),
  canvas: $("#selection-canvas"),
  paintCanvas: $("#paint-canvas"),
  resultImage: $("#result-image"),
  canvasLoader: $("#canvas-loader"),
  loaderText: $("#loader-text"),
  cancelJobButton: $("#cancel-job-button"),
  canvasSize: $("#canvas-size"),
  statusMessage: $("#status-message"),
  selectionReadout: $("#selection-readout"),
  selectTool: $("#select-tool"),
  selectAllButton: $("#select-all-button"),
  clearSelectionButton: $("#clear-selection-button"),
  extractButton: $("#extract-button"),
  refineMaskButton: $("#refine-mask-button"),
  maskRefineControls: $("#mask-refine-controls"),
  saveMaskRefineButton: $("#save-mask-refine-button"),
  cancelMaskRefineButton: $("#cancel-mask-refine-button"),
  maskBrushRadius: $("#mask-brush-radius"),
  maskBrushRadiusValue: $("#mask-brush-radius-value"),
  stylizeButton: $("#stylize-button"),
  createColoringButton: $("#create-coloring-button"),
  saveColoringButton: $("#save-coloring-button"),
  aiColorButton: $("#ai-color-button"),
  randomColorButton: $("#random-color-button"),
  clearPaintButton: $("#clear-paint-button"),
  undoPaintButton: $("#undo-paint-button"),
  redoPaintButton: $("#redo-paint-button"),
  patternButton: $("#pattern-button"),
  selectionStatus: $("#selection-status"),
  modelStatus: $("#model-status"),
  patternStatus: $("#pattern-status"),
  coloringStatus: $("#coloring-status"),
  paintControls: $("#paint-controls"),
  paintColor: $("#paint-color"),
  paintColorCode: $("#paint-color-code"),
  paletteGrid: $("#palette-grid"),
  aiColorPrompt: $("#ai-color-prompt"),
  aiColorBadge: $("#ai-color-badge"),
  modelProviderLabel: $("#model-provider-label"),
  localOptions: $("#local-options"),
  modelOptions: $("#model-options"),
  modelPrompt: $("#model-prompt"),
  pixelResolution: $("#pixel-resolution"),
  pixelColors: $("#pixel-colors"),
  gridCols: $("#grid-cols"),
  gridRows: $("#grid-rows"),
  coverage: $("#coverage"),
  coverageValue: $("#coverage-value"),
  padding: $("#padding"),
  paddingValue: $("#padding-value"),
  smoothCells: $("#smooth-cells"),
  paletteCodes: $("#palette-codes"),
  viewTabs: $("#view-tabs"),
  resultSection: $("#result-section"),
  beadCount: $("#bead-count"),
  colorCount: $("#color-count"),
  gridSize: $("#grid-size"),
  downloadPng: $("#download-png"),
  downloadJson: $("#download-json"),
  downloadCsv: $("#download-csv"),
  profileButton: $("#profile-button"),
  adminLink: $("#admin-link"),
  profileName: $("#profile-name"),
  profileAvatar: $("#profile-avatar"),
  profileDialog: $("#profile-dialog"),
  profileForm: $("#profile-form"),
  dialogAvatar: $("#dialog-avatar"),
  dialogEmail: $("#dialog-email"),
  profileDisplayName: $("#profile-display-name"),
  profileBio: $("#profile-bio"),
  currentPassword: $("#current-password"),
  newPassword: $("#new-password"),
  changePasswordButton: $("#change-password-button"),
  exportAccountButton: $("#export-account-button"),
  deleteAccountButton: $("#delete-account-button"),
  usageProjects: $("#usage-projects"),
  usageStorage: $("#usage-storage"),
  usageBeads: $("#usage-beads"),
  messageSubject: $("#message-subject"),
  messageContent: $("#message-content"),
  sendMessageButton: $("#send-message-button"),
  messageHistory: $("#message-history"),
  profileError: $("#profile-error"),
  logoutButton: $("#logout-button"),
  deleteDialog: $("#delete-dialog"),
  deleteProjectName: $("#delete-project-name"),
  confirmDeleteButton: $("#confirm-delete-button"),
  themeToggle: $("#theme-toggle"),
  toastRegion: $("#toast-region"),
};

const statusRank = {
  uploaded: 1,
  extracted: 3,
  stylized: 4,
  coloring: 5,
  completed: 6,
};

const statusLabels = {
  uploaded: "待框选",
  extracted: "已抠图",
  stylized: "已像素化",
  coloring: "已上色",
  completed: "图纸已完成",
};

const state = {
  authMode: "login",
  user: null,
  config: null,
  projects: [],
  activeProject: null,
  sourceImage: null,
  maskImage: null,
  selection: null,
  pointerStart: null,
  pointerId: null,
  activeView: "source",
  palette: [],
  coloring: null,
  paintTool: "brush",
  paintColor: "#9768d6",
  paintCellSize: 16,
  paintPointerId: null,
  lastPaintCell: null,
  undoStack: [],
  redoStack: [],
  coloringDirty: false,
  busy: false,
  pendingDelete: null,
  currentJobId: null,
  refiningMask: false,
  maskMode: "keep",
  maskEdits: { keep: [], remove: [] },
};

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  let data = null;
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) {
    data = await response.json();
  }
  if (!response.ok) {
    let message = data?.detail || `请求失败（${response.status}）`;
    if (Array.isArray(message)) {
      message = message.map((item) => item.msg).join("；");
    }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  if (response.status === 202 && data?.job?.id) {
    return waitForJob(data.job.id);
  }
  return data;
}

async function waitForJob(jobId) {
  const deadline = Date.now() + 5 * 60 * 1000;
  state.currentJobId = jobId;
  elements.cancelJobButton.hidden = false;
  elements.cancelJobButton.disabled = false;
  try {
    while (Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, 800));
    const result = await api(`/api/jobs/${jobId}`);
    const status = result?.job?.status;
    if (status === "completed") return result;
    if (status === "failed") {
      throw new Error(result.job.error_message || "后台处理任务失败");
    }
    }
  } finally {
    state.currentJobId = null;
  }
  throw new Error("后台任务等待超时，请稍后在项目历史中查看结果");
}

function showError(element, message) {
  element.textContent = message;
  element.hidden = false;
}

function clearError(element) {
  element.textContent = "";
  element.hidden = true;
}

function toast(message, kind = "success") {
  const item = document.createElement("div");
  item.className = `toast${kind === "error" ? " is-error" : ""}`;
  item.textContent = message;
  elements.toastRegion.append(item);
  window.setTimeout(() => item.remove(), 3600);
}

function setAuthMode(mode) {
  state.authMode = mode;
  const isRegister = mode === "register";
  elements.loginTab.classList.toggle("is-active", !isRegister);
  elements.loginTab.setAttribute("aria-selected", String(!isRegister));
  elements.registerTab.classList.toggle("is-active", isRegister);
  elements.registerTab.setAttribute("aria-selected", String(isRegister));
  elements.displayNameField.hidden = !isRegister;
  elements.displayName.required = isRegister;
  elements.password.autocomplete = isRegister ? "new-password" : "current-password";
  elements.passwordHelp.textContent = isRegister ? "至少 8 个字符。" : "登录密码区分大小写。";
  elements.authTitle.textContent = isRegister ? "建立你的工作台" : "继续你的图纸";
  elements.authSubtitle.textContent = isRegister
    ? "创建账户后即可保存抠图、像素图和色号图纸。"
    : "使用邮箱登录，项目会保存在这个工作台。";
  elements.authSubmit.textContent = isRegister ? "创建账户" : "登录";
  clearError(elements.authError);
}

function showAuth() {
  state.user = null;
  state.projects = [];
  state.activeProject = null;
  elements.appView.hidden = true;
  elements.authView.hidden = false;
  elements.email.focus({ preventScroll: true });
}

function showApp() {
  elements.authView.hidden = true;
  elements.appView.hidden = false;
  renderProfile();
}

function renderProfile() {
  if (!state.user) return;
  const name = state.user.display_name || state.user.email.split("@")[0];
  const initial = Array.from(name.trim())[0] || "豆";
  elements.profileName.textContent = name;
  elements.profileAvatar.textContent = initial;
  elements.dialogAvatar.textContent = initial;
  elements.dialogEmail.textContent = state.user.email;
  elements.profileDisplayName.value = name;
  elements.profileBio.value = state.user.bio || "";
  elements.adminLink.hidden = state.user.role !== "admin";
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function renderMessageHistory(messages) {
  elements.messageHistory.replaceChildren();
  if (!messages.length) {
    const empty = document.createElement("p");
    empty.textContent = "还没有留言记录。";
    elements.messageHistory.append(empty);
    return;
  }
  for (const message of messages.slice(0, 5)) {
    const item = document.createElement("article");
    const heading = document.createElement("div");
    const title = document.createElement("b");
    const status = document.createElement("span");
    const content = document.createElement("p");
    title.textContent = message.subject;
    status.textContent = { open: "待查看", read: "处理中", resolved: "已解决" }[message.status] || message.status;
    content.textContent = message.admin_note || message.content;
    heading.append(title, status);
    item.append(heading, content);
    elements.messageHistory.append(item);
  }
}

async function loadAccountPanel() {
  try {
    const [usageData, messageData] = await Promise.all([
      api("/api/account/usage"),
      api("/api/messages"),
    ]);
    elements.usageProjects.textContent = Number(usageData.usage.projects).toLocaleString("zh-CN");
    elements.usageStorage.textContent = formatBytes(usageData.usage.storage_bytes);
    elements.usageBeads.textContent = Number(usageData.usage.beads).toLocaleString("zh-CN");
    renderMessageHistory(messageData.messages || []);
  } catch (error) {
    showError(elements.profileError, error.message);
  }
}

async function sendMessage() {
  const subject = elements.messageSubject.value.trim();
  const content = elements.messageContent.value.trim();
  if (!subject || !content) {
    showError(elements.profileError, "请填写留言标题和内容。");
    return;
  }
  clearError(elements.profileError);
  elements.sendMessageButton.disabled = true;
  try {
    await api("/api/messages", {
      method: "POST",
      body: JSON.stringify({ subject, content }),
    });
    elements.messageSubject.value = "";
    elements.messageContent.value = "";
    await loadAccountPanel();
    toast("留言已发送，管理员可以在管理端查看。");
  } catch (error) {
    showError(elements.profileError, error.message);
  } finally {
    elements.sendMessageButton.disabled = false;
  }
}

async function handleAuthSubmit(event) {
  event.preventDefault();
  clearError(elements.authError);
  const payload = {
    email: elements.email.value.trim(),
    password: elements.password.value,
    display_name: elements.displayName.value.trim(),
  };
  if (!payload.email || !payload.password) {
    showError(elements.authError, "请填写邮箱和密码。");
    return;
  }
  elements.authSubmit.disabled = true;
  elements.authSubmit.textContent = state.authMode === "register" ? "正在创建" : "正在登录";
  try {
    const data = await api(`/api/auth/${state.authMode}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.user = data.user;
    elements.authForm.reset();
    showApp();
    await loadPalette();
    setPaintColor(state.paintColor);
    await loadProjects();
  } catch (error) {
    showError(elements.authError, error.message);
  } finally {
    elements.authSubmit.disabled = false;
    elements.authSubmit.textContent = state.authMode === "register" ? "创建账户" : "登录";
  }
}

async function loadProjects(preferredId = null) {
  try {
    const data = await api("/api/projects");
    state.projects = data.projects || [];
    renderProjectList();
    const targetId = preferredId || state.activeProject?.id || state.projects[0]?.id;
    if (targetId) {
      const project = state.projects.find((item) => item.id === targetId) || state.projects[0];
      await selectProject(project);
    } else {
      resetWorkspace();
    }
  } catch (error) {
    if (error.status === 401) {
      showAuth();
    } else {
      toast(error.message, "error");
      elements.projectList.innerHTML = '<p class="project-empty">项目列表加载失败，请刷新页面。</p>';
    }
  }
}

function projectStatusText(project) {
  return statusLabels[project.status] || "处理中";
}

function formatProjectDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚更新";
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(date);
}

function renderProjectList() {
  elements.projectList.replaceChildren();
  elements.projectCount.textContent = `${state.projects.length} 个项目`;
  if (!state.projects.length) {
    const empty = document.createElement("p");
    empty.className = "project-empty";
    empty.textContent = "还没有图纸。上传一张图片开始第一个项目。";
    elements.projectList.append(empty);
    return;
  }

  for (const project of state.projects) {
    const item = document.createElement("div");
    item.className = `project-item${state.activeProject?.id === project.id ? " is-active" : ""}`;
    item.tabIndex = 0;
    item.setAttribute("role", "button");
    item.setAttribute("aria-label", `打开项目 ${project.name}`);

    const image = document.createElement("img");
    image.className = "project-thumb";
    image.alt = "";
    image.loading = "lazy";
    image.src = project.assets.preview || project.assets.painted || project.assets.stylized || project.assets.cutout || project.assets.source;

    const meta = document.createElement("span");
    meta.className = "project-meta";
    const name = document.createElement("b");
    name.textContent = project.name;
    const detail = document.createElement("small");
    detail.textContent = `${projectStatusText(project)} / ${formatProjectDate(project.updated_at)}`;
    meta.append(name, detail);

    const actions = document.createElement("span");
    actions.className = "project-actions";
    const renameButton = document.createElement("button");
    renameButton.type = "button";
    renameButton.title = "重命名项目";
    renameButton.setAttribute("aria-label", `重命名 ${project.name}`);
    renameButton.textContent = "✎";
    renameButton.addEventListener("click", (event) => {
      event.stopPropagation();
      renameProject(project);
    });
    const duplicateButton = document.createElement("button");
    duplicateButton.type = "button";
    duplicateButton.title = "复制项目";
    duplicateButton.setAttribute("aria-label", `复制 ${project.name}`);
    duplicateButton.textContent = "＋";
    duplicateButton.addEventListener("click", (event) => {
      event.stopPropagation();
      duplicateProject(project);
    });
    const deleteButton = document.createElement("button");
    deleteButton.className = "project-delete";
    deleteButton.type = "button";
    deleteButton.title = "删除项目";
    deleteButton.setAttribute("aria-label", `删除 ${project.name}`);
    deleteButton.textContent = "×";
    deleteButton.addEventListener("click", (event) => {
      event.stopPropagation();
      openDeleteDialog(project);
    });

    const open = () => selectProject(project);
    item.addEventListener("click", open);
    item.addEventListener("keydown", (event) => {
      if (event.target !== item) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
    actions.append(renameButton, duplicateButton, deleteButton);
    item.append(image, meta, actions);
    elements.projectList.append(item);
  }
}

function resetWorkspace() {
  state.activeProject = null;
  state.sourceImage = null;
  state.maskImage = null;
  state.selection = null;
  state.coloring = null;
  state.undoStack = [];
  state.redoStack = [];
  state.coloringDirty = false;
  state.activeView = "source";
  state.refiningMask = false;
  state.maskEdits = { keep: [], remove: [] };
  elements.emptyWorkspace.hidden = false;
  elements.canvas.hidden = true;
  elements.paintCanvas.hidden = true;
  elements.resultImage.hidden = true;
  elements.viewTabs.hidden = true;
  elements.canvasSize.textContent = "未载入图片";
  elements.statusMessage.textContent = "等待上传图片";
  elements.selectionReadout.textContent = "选区：未设置";
  elements.resultSection.hidden = true;
  updateControls();
  updateWorkflow();
}

async function selectProject(project) {
  if (!project || state.busy) return;
  if (state.coloringDirty && state.activeProject && state.activeProject.id !== project.id) {
    const saved = await saveColoring({ quiet: true });
    if (!saved) return;
  }
  state.activeProject = project;
  state.maskImage = null;
  state.refiningMask = false;
  state.maskEdits = { keep: [], remove: [] };
  state.selection = isValidSelection(project.selection) ? {
    x: project.selection.x,
    y: project.selection.y,
    width: project.selection.width,
    height: project.selection.height,
  } : null;
  renderProjectList();
  applyProjectSettings(project);
  try {
    await loadSourceImage(project.assets.source);
  } catch {
    elements.canvas.hidden = true;
    elements.resultImage.hidden = true;
    elements.statusMessage.textContent = "源图加载失败，请刷新后重试";
    return;
  }
  state.coloring = null;
  state.undoStack = [];
  state.redoStack = [];
  state.coloringDirty = false;
  if (project.has_coloring) {
    try {
      const data = await api(`/api/projects/${project.id}/coloring`);
      if (state.activeProject?.id === project.id) state.coloring = data.coloring;
    } catch (error) {
      toast(error.message, "error");
    }
  }
  const preferredView = project.assets.pattern
    ? "pattern"
    : state.coloring
      ? "coloring"
      : project.assets.stylized
        ? "stylized"
        : project.assets.cutout
          ? "cutout"
          : "source";
  setView(preferredView);
  updateControls();
  updateWorkflow();
}

function applyProjectSettings(project) {
  const stylize = project.settings?.stylize || {};
  const coloring = project.settings?.coloring || {};
  const pattern = project.settings?.pattern || {};
  elements.pixelResolution.value = stylize.pixel_resolution || 72;
  elements.pixelColors.value = stylize.color_count || 20;
  if (stylize.prompt) elements.modelPrompt.value = stylize.prompt;
  elements.gridCols.value = coloring.cols || pattern.cols || project.cols || 36;
  elements.gridRows.value = coloring.rows || pattern.rows || project.rows || 35;
  elements.coverage.value = Math.round((pattern.coverage ?? 0.32) * 100);
  elements.padding.value = Math.round((pattern.padding ?? 0.04) * 100);
  elements.smoothCells.checked = Boolean(pattern.smooth_cells);
  elements.paletteCodes.value = Array.isArray(pattern.palette_codes) ? pattern.palette_codes.join(" ") : "";
  updateRangeLabels();
}

function loadSourceImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.decoding = "async";
    image.onload = () => {
      state.sourceImage = image;
      elements.canvas.width = image.naturalWidth;
      elements.canvas.height = image.naturalHeight;
      elements.canvasSize.textContent = `${image.naturalWidth} × ${image.naturalHeight} px`;
      drawCanvas();
      resolve();
    };
    image.onerror = () => {
      state.sourceImage = null;
      const error = new Error("源图加载失败");
      toast(error.message, "error");
      reject(error);
    };
    image.src = url;
  });
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.decoding = "async";
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("图片加载失败"));
    image.src = url;
  });
}

function drawCanvas() {
  const image = state.sourceImage;
  if (!image) return;
  const canvas = elements.canvas;
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  if (state.refiningMask && state.maskImage) {
    context.save();
    context.globalAlpha = 0.28;
    context.globalCompositeOperation = "multiply";
    context.drawImage(state.maskImage, 0, 0, canvas.width, canvas.height);
    context.restore();
    for (const point of state.maskEdits.keep) drawMaskPoint(context, point, "#24a36a");
    for (const point of state.maskEdits.remove) drawMaskPoint(context, point, "#bd3168");
    return;
  }

  if (!state.selection) return;
  const rect = selectionToPixels(state.selection, canvas.width, canvas.height);
  context.save();
  context.fillStyle = "rgba(15, 17, 20, 0.48)";
  context.beginPath();
  context.rect(0, 0, canvas.width, canvas.height);
  context.rect(rect.x, rect.y, rect.width, rect.height);
  context.fill("evenodd");
  context.setLineDash([Math.max(4, canvas.width / 160), Math.max(3, canvas.width / 240)]);
  context.lineWidth = Math.max(2, canvas.width / 600);
  context.strokeStyle = "#fdfdfb";
  context.strokeRect(rect.x, rect.y, rect.width, rect.height);
  context.lineDashOffset = Math.max(3, canvas.width / 220);
  context.strokeStyle = "#bd3168";
  context.strokeRect(rect.x, rect.y, rect.width, rect.height);
  context.restore();
}

function setView(view) {
  const project = state.activeProject;
  if (!project) return;
  const url = project.assets[view];
  if (view === "coloring" && !state.coloring) {
    toast("请先生成轮廓与方格。", "error");
    return;
  }
  if (view !== "source" && view !== "coloring" && !url) {
    toast("这个结果还没有生成。", "error");
    return;
  }
  state.activeView = view;
  elements.emptyWorkspace.hidden = true;
  elements.viewTabs.hidden = false;
  elements.canvas.hidden = view !== "source";
  elements.paintCanvas.hidden = view !== "coloring";
  elements.resultImage.hidden = view === "source" || view === "coloring";
  if (view === "coloring") {
    drawPaintCanvas();
    elements.canvasSize.textContent = `${state.coloring.cols} × ${state.coloring.rows} 格`;
  } else if (view !== "source") {
    elements.resultImage.src = url;
    elements.resultImage.alt = {
      cutout: "已抠出的透明背景主体",
      stylized: "像素化角色结果",
      painted: "已保存的手动配色",
      pattern: "带色号的拼豆图纸",
      preview: "拼豆颜色预览",
    }[view] || "当前处理结果";
  } else {
    drawCanvas();
    elements.canvasSize.textContent = `${state.sourceImage.naturalWidth} × ${state.sourceImage.naturalHeight} px`;
  }
  $$(".view-tab").forEach((tab) => {
    const selected = tab.dataset.view === view;
    tab.classList.toggle("is-active", selected);
    tab.setAttribute("aria-selected", String(selected));
    tab.disabled = tab.dataset.view === "coloring"
      ? !state.coloring
      : tab.dataset.view !== "source" && !project.assets[tab.dataset.view];
  });
  elements.statusMessage.textContent = {
    source: "拖动鼠标框选需要保留的主体",
    cutout: "主体已从背景中分离",
    stylized: "像素图已生成，可以继续调整格子",
    coloring: "轮廓已锁定，点击或拖动方格进行上色",
    pattern: "色号图纸已生成，可以导出文件",
  }[view];
}

function updateProject(project) {
  const index = state.projects.findIndex((item) => item.id === project.id);
  if (index >= 0) state.projects[index] = project;
  else state.projects.unshift(project);
  state.projects.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
  state.activeProject = project;
  renderProjectList();
  updateControls();
  updateWorkflow();
}

function updateWorkflow() {
  const rank = state.activeProject ? statusRank[state.activeProject.status] || 1 : 0;
  const currentRank = rank === 0 ? 1 : Math.min(6, rank + (rank < 3 ? 1 : 0));
  $$(".workflow-step").forEach((step, index) => {
    const stepRank = index + 1;
    step.classList.toggle("is-complete", stepRank < currentRank);
    step.classList.toggle("is-current", stepRank === currentRank);
  });
}

function updateControls() {
  const project = state.activeProject;
  const hasProject = Boolean(project);
  const hasSelection = Boolean(state.selection);
  const hasCutout = Boolean(project?.assets.cutout);
  const hasStyled = Boolean(project?.assets.stylized);
  const hasColoring = Boolean(state.coloring);
  const hasPattern = Boolean(project?.assets.pattern);

  elements.extractButton.disabled = state.busy || !hasProject || !hasSelection;
  elements.refineMaskButton.disabled = state.busy || !hasProject || !project?.assets.mask;
  elements.refineMaskButton.hidden = state.refiningMask;
  elements.maskRefineControls.hidden = !state.refiningMask;
  elements.stylizeButton.disabled = state.busy || !hasCutout;
  elements.createColoringButton.disabled = state.busy || !hasCutout;
  elements.saveColoringButton.disabled = state.busy || !state.coloring || !state.coloringDirty;
  elements.aiColorButton.disabled = state.busy || !state.coloring || !state.config?.model_api_configured;
  elements.randomColorButton.disabled = state.busy || !state.coloring;
  elements.clearPaintButton.disabled = state.busy || !state.coloring;
  elements.undoPaintButton.disabled = state.busy || !state.undoStack.length;
  elements.redoPaintButton.disabled = state.busy || !state.redoStack.length;
  elements.patternButton.disabled = state.busy || !hasCutout;
  elements.selectAllButton.disabled = state.busy || !hasProject;
  elements.clearSelectionButton.disabled = state.busy || !hasSelection;
  elements.selectionStatus.textContent = hasSelection ? "已选择" : "待框选";
  elements.selectionStatus.classList.toggle("is-ready", hasSelection);
  elements.patternStatus.textContent = hasPattern ? "已生成" : "未生成";
  elements.patternStatus.classList.toggle("is-ready", hasPattern);
  elements.coloringStatus.textContent = hasColoring
    ? state.coloringDirty ? "未保存" : "可编辑"
    : "未创建";
  elements.coloringStatus.classList.toggle("is-ready", hasColoring && !state.coloringDirty);
  elements.paintControls.hidden = !hasColoring;
  elements.resultSection.hidden = !hasPattern;

  if (hasPattern) {
    elements.beadCount.textContent = Number(project.bead_count).toLocaleString("zh-CN");
    elements.colorCount.textContent = Number(project.colors_used).toLocaleString("zh-CN");
    elements.gridSize.textContent = `${project.cols} × ${project.rows}`;
    elements.downloadPng.href = project.downloads.png;
    elements.downloadJson.href = project.downloads.json;
    elements.downloadCsv.href = project.downloads.csv;
  }

  const availableViews = hasCutout || hasStyled || hasColoring || hasPattern;
  elements.viewTabs.hidden = !hasProject || !availableViews;
  updateSelectionReadout();
}

function updateSelectionReadout() {
  if (!state.selection || !state.sourceImage) {
    elements.selectionReadout.textContent = "选区：未设置";
    return;
  }
  const rect = selectionToPixels(state.selection, state.sourceImage.naturalWidth, state.sourceImage.naturalHeight);
  elements.selectionReadout.textContent = `选区：${Math.round(rect.width)} × ${Math.round(rect.height)} px`;
}

function updateRangeLabels() {
  elements.coverageValue.textContent = `${elements.coverage.value}%`;
  elements.paddingValue.textContent = `${elements.padding.value}%`;
}

function isValidSelection(selection) {
  return selection
    && Number.isFinite(selection.x)
    && Number.isFinite(selection.y)
    && selection.width > 0
    && selection.height > 0;
}

function selectionToPixels(selection, width, height) {
  return {
    x: selection.x * width,
    y: selection.y * height,
    width: selection.width * width,
    height: selection.height * height,
  };
}

function pointerPosition(event) {
  const rect = elements.canvas.getBoundingClientRect();
  const x = Math.max(0, Math.min(elements.canvas.width, (event.clientX - rect.left) * elements.canvas.width / rect.width));
  const y = Math.max(0, Math.min(elements.canvas.height, (event.clientY - rect.top) * elements.canvas.height / rect.height));
  return { x, y };
}

function drawMaskPoint(context, point, color) {
  const radius = Number(elements.maskBrushRadius.value || 32);
  context.save();
  context.fillStyle = color;
  context.globalAlpha = 0.72;
  context.beginPath();
  context.arc(point.x * elements.canvas.width, point.y * elements.canvas.height, radius, 0, Math.PI * 2);
  context.fill();
  context.restore();
}

function addMaskEdit(event) {
  const position = pointerPosition(event);
  const edits = state.maskEdits[state.maskMode];
  if (edits.length >= 2000) return;
  const point = {
    x: position.x / elements.canvas.width,
    y: position.y / elements.canvas.height,
  };
  const previous = edits[edits.length - 1];
  if (previous && Math.hypot(previous.x - point.x, previous.y - point.y) < 0.003) return;
  edits.push(point);
  drawCanvas();
}

function startSelection(event) {
  if (!state.sourceImage || state.busy || state.activeView !== "source") return;
  if (state.refiningMask) {
    state.pointerId = event.pointerId;
    elements.canvas.setPointerCapture(event.pointerId);
    addMaskEdit(event);
    return;
  }
  state.pointerStart = pointerPosition(event);
  state.pointerId = event.pointerId;
  elements.canvas.setPointerCapture(event.pointerId);
  state.selection = null;
  drawCanvas();
  updateControls();
}

function moveSelection(event) {
  if (state.refiningMask) {
    if (event.pointerId === state.pointerId) addMaskEdit(event);
    return;
  }
  if (state.pointerStart === null || event.pointerId !== state.pointerId) return;
  const current = pointerPosition(event);
  const left = Math.min(state.pointerStart.x, current.x);
  const top = Math.min(state.pointerStart.y, current.y);
  const width = Math.abs(current.x - state.pointerStart.x);
  const height = Math.abs(current.y - state.pointerStart.y);
  state.selection = {
    x: left / elements.canvas.width,
    y: top / elements.canvas.height,
    width: width / elements.canvas.width,
    height: height / elements.canvas.height,
  };
  drawCanvas();
  updateSelectionReadout();
}

function endSelection(event) {
  if (state.refiningMask) {
    if (event.pointerId === state.pointerId) state.pointerId = null;
    return;
  }
  if (state.pointerStart === null || event.pointerId !== state.pointerId) return;
  const tooSmall = !state.selection
    || state.selection.width * elements.canvas.width < 8
    || state.selection.height * elements.canvas.height < 8;
  if (tooSmall) state.selection = null;
  state.pointerStart = null;
  state.pointerId = null;
  drawCanvas();
  updateControls();
}

function selectWholeImage() {
  if (!state.sourceImage) return;
  setView("source");
  state.selection = { x: 0.015, y: 0.015, width: 0.97, height: 0.97 };
  drawCanvas();
  updateControls();
}

function clearSelection() {
  if (state.refiningMask) return;
  state.selection = null;
  drawCanvas();
  updateControls();
}

async function beginMaskRefine() {
  if (!state.activeProject || state.busy || !state.activeProject.assets.mask) return;
  try {
    state.maskImage = await loadImage(state.activeProject.assets.mask);
    state.refiningMask = true;
    state.maskMode = "keep";
    state.maskEdits = { keep: [], remove: [] };
    setView("source");
    drawCanvas();
    updateControls();
  } catch (error) {
    toast(error.message, "error");
  }
}

function cancelMaskRefine() {
  state.refiningMask = false;
  state.maskEdits = { keep: [], remove: [] };
  drawCanvas();
  updateControls();
}

async function applyMaskRefine() {
  if (!state.activeProject || state.busy) return;
  if (!state.maskEdits.keep.length && !state.maskEdits.remove.length) {
    toast("请先添加至少一处轮廓修正。", "error");
    return;
  }
  setBusy(true, "正在应用抠图轮廓修正");
  try {
    const data = await api(`/api/projects/${state.activeProject.id}/mask/refine`, {
      method: "POST",
      body: JSON.stringify({
        keep: state.maskEdits.keep,
        remove: state.maskEdits.remove,
        radius: Number(elements.maskBrushRadius.value),
      }),
    });
    updateProject(data.project);
    state.refiningMask = false;
    state.maskEdits = { keep: [], remove: [] };
    setView("cutout");
    toast("抠图轮廓已修正，后续结果已重置。");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function setMaskMode(mode) {
  state.maskMode = mode;
  $$(".mask-mode-button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.maskMode === mode);
  });
}

function setBusy(busy, message = "正在处理图片") {
  state.busy = busy;
  elements.canvasLoader.hidden = !busy;
  elements.loaderText.textContent = message;
  elements.cancelJobButton.hidden = !busy || !state.currentJobId;
  elements.cancelJobButton.disabled = !state.currentJobId;
  updateControls();
}

async function cancelCurrentJob() {
  if (!state.currentJobId) return;
  const jobId = state.currentJobId;
  elements.cancelJobButton.disabled = true;
  try {
    await api(`/api/jobs/${jobId}/cancel`, { method: "POST" });
    toast("已请求取消当前处理任务。");
  } catch (error) {
    toast(error.message, "error");
    elements.cancelJobButton.disabled = false;
  }
}

async function renameProject(project) {
  if (state.busy) return;
  const name = window.prompt("新的项目名称", project.name);
  if (name === null || !name.trim() || name.trim() === project.name) return;
  try {
    const data = await api(`/api/projects/${project.id}`, {
      method: "PATCH",
      body: JSON.stringify({ name: name.trim() }),
    });
    updateProject(data.project);
    toast("项目名称已更新。");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function duplicateProject(project) {
  if (state.busy) return;
  try {
    const data = await api(`/api/projects/${project.id}/duplicate`, { method: "POST" });
    updateProject(data.project);
    await selectProject(data.project);
    toast("项目副本已创建。");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function uploadFile(file) {
  if (!file || state.busy) return;
  if (!file.type.startsWith("image/")) {
    toast("请选择 PNG、JPG 或 WebP 图片。", "error");
    return;
  }
  if (file.size > 20 * 1024 * 1024) {
    toast("图片不能超过 20 MB。", "error");
    return;
  }
  if (state.coloringDirty && !await saveColoring({ quiet: true })) return;
  const form = new FormData();
  form.append("image", file);
  form.append("name", file.name.replace(/\.[^.]+$/, ""));
  setBusy(true, "正在上传并读取图片");
  try {
    const data = await api("/api/projects", { method: "POST", body: form });
    state.projects.unshift(data.project);
    updateProject(data.project);
    setBusy(false);
    await selectProject(data.project);
    toast("图片已加入工作台。拖动鼠标框选主体。");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    elements.fileInput.value = "";
    setBusy(false);
  }
}

async function extractSubject() {
  if (!state.activeProject || !state.selection || state.busy) return;
  setBusy(true, "正在分析选区并抠出主体");
  try {
    const data = await api(`/api/projects/${state.activeProject.id}/extract`, {
      method: "POST",
      body: JSON.stringify(state.selection),
    });
    state.coloring = null;
    resetPaintHistory();
    updateProject(data.project);
    setView("cutout");
    toast("主体已抠出，可以继续生成像素图。");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function selectedProvider() {
  return $("input[name='provider']:checked")?.value || "local";
}

function updateProviderOptions() {
  const provider = selectedProvider();
  elements.localOptions.hidden = provider !== "local";
  elements.modelOptions.hidden = provider !== "model";
}

async function stylizeSubject() {
  if (!state.activeProject || state.busy) return;
  const provider = selectedProvider();
  if (provider === "model" && !state.config?.model_api_configured) {
    toast("请先在服务端配置模型 API。", "error");
    return;
  }
  const payload = {
    provider,
    prompt: elements.modelPrompt.value.trim(),
    pixel_resolution: Number(elements.pixelResolution.value),
    color_count: Number(elements.pixelColors.value),
  };
  setBusy(true, provider === "model" ? "模型正在重绘像素角色" : "正在生成本地像素图");
  try {
    const data = await api(`/api/projects/${state.activeProject.id}/stylize`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.coloring = null;
    resetPaintHistory();
    updateProject(data.project);
    setView("stylized");
    toast("像素图已生成。调整格子后即可生成色号图。");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function parsePaletteCodes() {
  return elements.paletteCodes.value
    .split(/[\s,，]+/)
    .map((code) => code.trim().toUpperCase())
    .filter(Boolean);
}

function validGridSize() {
  const cols = Number(elements.gridCols.value);
  const rows = Number(elements.gridRows.value);
  if (!Number.isInteger(cols) || !Number.isInteger(rows) || cols < 8 || rows < 8 || cols > 100 || rows > 100) {
    toast("宽高格数需要在 8 到 100 之间。", "error");
    return null;
  }
  return { cols, rows };
}

async function loadPalette() {
  if (state.palette.length) return;
  const data = await api("/api/palette");
  state.palette = data.colors || [];
  renderPalette();
}

function renderPalette() {
  elements.paletteGrid.replaceChildren();
  for (const color of state.palette) {
    const button = document.createElement("button");
    button.className = "palette-swatch";
    button.type = "button";
    button.style.setProperty("--swatch", color.hex);
    button.title = `${color.code} / ${color.hex.toUpperCase()}`;
    button.setAttribute("aria-label", `选择色号 ${color.code}`);
    button.dataset.code = color.code;
    button.dataset.color = color.hex;
    button.addEventListener("click", () => setPaintColor(color.hex, color.code));
    elements.paletteGrid.append(button);
  }
}

function setPaintColor(value, code = "自定义") {
  state.paintColor = value.toLowerCase();
  elements.paintColor.value = state.paintColor;
  const exact = state.palette.find((item) => item.hex.toLowerCase() === state.paintColor);
  elements.paintColorCode.textContent = exact?.code || code;
  $$(".palette-swatch", elements.paletteGrid).forEach((swatch) => {
    swatch.classList.toggle("is-selected", swatch.dataset.color.toLowerCase() === state.paintColor);
  });
}

function cloneCells(cells) {
  return cells.map((row) => row.slice());
}

function resetPaintHistory() {
  state.undoStack = [];
  state.redoStack = [];
  state.coloringDirty = false;
}

function pushPaintHistory() {
  if (!state.coloring) return;
  state.undoStack.push(cloneCells(state.coloring.cells));
  if (state.undoStack.length > 30) state.undoStack.shift();
  state.redoStack = [];
}

function setColoringChanged() {
  state.coloringDirty = true;
  drawPaintCanvas();
  updateControls();
}

function undoPaint() {
  if (!state.coloring || !state.undoStack.length) return;
  state.redoStack.push(cloneCells(state.coloring.cells));
  state.coloring.cells = state.undoStack.pop();
  setColoringChanged();
}

function redoPaint() {
  if (!state.coloring || !state.redoStack.length) return;
  state.undoStack.push(cloneCells(state.coloring.cells));
  state.coloring.cells = state.redoStack.pop();
  setColoringChanged();
}

function setPaintTool(tool) {
  state.paintTool = tool;
  $$(".paint-tool").forEach((button) => {
    const active = button.dataset.paintTool === tool;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  elements.paintCanvas.dataset.tool = tool;
}

function isBoundaryCell(row, col) {
  const grid = state.coloring;
  if (!grid?.mask[row]?.[col]) return false;
  return row === 0
    || col === 0
    || row === grid.rows - 1
    || col === grid.cols - 1
    || !grid.mask[row - 1][col]
    || !grid.mask[row + 1][col]
    || !grid.mask[row][col - 1]
    || !grid.mask[row][col + 1];
}

function drawPaintCanvas() {
  const grid = state.coloring;
  if (!grid) return;
  const cell = Math.max(8, Math.min(24, Math.floor(820 / Math.max(grid.cols, grid.rows))));
  state.paintCellSize = cell;
  const canvas = elements.paintCanvas;
  canvas.width = grid.cols * cell;
  canvas.height = grid.rows * cell;
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);

  const checker = Math.max(6, Math.floor(cell / 2));
  context.fillStyle = "#e8e4e2";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = "#f4f1ed";
  for (let y = 0; y < canvas.height; y += checker) {
    for (let x = 0; x < canvas.width; x += checker) {
      if ((x / checker + y / checker) % 2 === 0) context.fillRect(x, y, checker, checker);
    }
  }

  for (let row = 0; row < grid.rows; row += 1) {
    for (let col = 0; col < grid.cols; col += 1) {
      if (!grid.mask[row][col]) continue;
      const x = col * cell;
      const y = row * cell;
      const color = grid.cells[row][col];
      context.fillStyle = color || "#faf7f1";
      context.fillRect(x, y, cell, cell);
      if (!color) {
        context.fillStyle = "#c4bdba";
        context.beginPath();
        context.arc(x + cell / 2, y + cell / 2, Math.max(1.4, cell * 0.09), 0, Math.PI * 2);
        context.fill();
      }
      context.strokeStyle = "rgba(75, 69, 73, 0.24)";
      context.lineWidth = 1;
      context.strokeRect(x + 0.5, y + 0.5, cell - 1, cell - 1);
      if (isBoundaryCell(row, col)) {
        context.strokeStyle = "#3d353b";
        context.lineWidth = Math.max(1.5, cell * 0.1);
        context.beginPath();
        if (row === 0 || !grid.mask[row - 1][col]) {
          context.moveTo(x, y);
          context.lineTo(x + cell, y);
        }
        if (row === grid.rows - 1 || !grid.mask[row + 1][col]) {
          context.moveTo(x, y + cell);
          context.lineTo(x + cell, y + cell);
        }
        if (col === 0 || !grid.mask[row][col - 1]) {
          context.moveTo(x, y);
          context.lineTo(x, y + cell);
        }
        if (col === grid.cols - 1 || !grid.mask[row][col + 1]) {
          context.moveTo(x + cell, y);
          context.lineTo(x + cell, y + cell);
        }
        context.stroke();
      }
    }
  }
}

function paintCellFromPointer(event) {
  if (!state.coloring) return null;
  const rect = elements.paintCanvas.getBoundingClientRect();
  const col = Math.floor((event.clientX - rect.left) * elements.paintCanvas.width / rect.width / state.paintCellSize);
  const row = Math.floor((event.clientY - rect.top) * elements.paintCanvas.height / rect.height / state.paintCellSize);
  if (row < 0 || col < 0 || row >= state.coloring.rows || col >= state.coloring.cols) return null;
  if (!state.coloring.mask[row][col]) return null;
  return { row, col };
}

function floodFill(row, col, replacement) {
  const grid = state.coloring;
  const target = grid.cells[row][col];
  if (target === replacement) return false;
  const queue = [[row, col]];
  const seen = new Set();
  while (queue.length) {
    const [currentRow, currentCol] = queue.pop();
    const key = `${currentRow}:${currentCol}`;
    if (seen.has(key) || !grid.mask[currentRow]?.[currentCol] || grid.cells[currentRow][currentCol] !== target) continue;
    seen.add(key);
    grid.cells[currentRow][currentCol] = replacement;
    queue.push([currentRow - 1, currentCol], [currentRow + 1, currentCol], [currentRow, currentCol - 1], [currentRow, currentCol + 1]);
  }
  return seen.size > 0;
}

function applyPaintAt(cell) {
  if (!cell || !state.coloring) return false;
  const { row, col } = cell;
  if (state.paintTool === "eyedropper") {
    const sampled = state.coloring.cells[row][col];
    if (sampled) setPaintColor(sampled);
    return false;
  }
  const replacement = state.paintTool === "eraser" ? null : state.paintColor;
  if (state.paintTool === "fill") return floodFill(row, col, replacement);
  if (state.coloring.cells[row][col] === replacement) return false;
  state.coloring.cells[row][col] = replacement;
  return true;
}

function startPainting(event) {
  if (!state.coloring || state.busy || state.activeView !== "coloring") return;
  const cell = paintCellFromPointer(event);
  if (!cell) return;
  if (state.paintTool !== "eyedropper") pushPaintHistory();
  state.paintPointerId = event.pointerId;
  state.lastPaintCell = `${cell.row}:${cell.col}`;
  elements.paintCanvas.setPointerCapture(event.pointerId);
  if (applyPaintAt(cell)) setColoringChanged();
}

function movePainting(event) {
  if (event.pointerId !== state.paintPointerId || !["brush", "eraser"].includes(state.paintTool)) return;
  const cell = paintCellFromPointer(event);
  if (!cell) return;
  const key = `${cell.row}:${cell.col}`;
  if (key === state.lastPaintCell) return;
  state.lastPaintCell = key;
  if (applyPaintAt(cell)) setColoringChanged();
}

function endPainting(event) {
  if (event.pointerId !== state.paintPointerId) return;
  state.paintPointerId = null;
  state.lastPaintCell = null;
}

function clearPaintColors() {
  if (!state.coloring) return;
  pushPaintHistory();
  state.coloring.cells = state.coloring.cells.map((row) => row.map(() => null));
  setColoringChanged();
}

function randomizeColors() {
  if (!state.coloring || !state.palette.length) return;
  const requested = new Set(parsePaletteCodes());
  let candidates = requested.size
    ? state.palette.filter((color) => requested.has(color.code))
    : state.palette.filter((color) => !["H1", "H2", "H7", "H16"].includes(color.code));
  if (!candidates.length) {
    toast("手头色号中没有可用于随机配色的颜色。", "error");
    return;
  }
  pushPaintHistory();
  candidates = candidates.slice().sort(() => Math.random() - 0.5);
  const picked = candidates.slice(0, Math.min(6, candidates.length));
  const luminance = (color) => {
    const value = color.hex.slice(1);
    return 0.2126 * parseInt(value.slice(0, 2), 16)
      + 0.7152 * parseInt(value.slice(2, 4), 16)
      + 0.0722 * parseInt(value.slice(4, 6), 16);
  };
  picked.sort((a, b) => luminance(a) - luminance(b));
  const seed = Math.random() * 1000;
  for (let row = 0; row < state.coloring.rows; row += 1) {
    for (let col = 0; col < state.coloring.cols; col += 1) {
      if (!state.coloring.mask[row][col]) continue;
      let index;
      if (isBoundaryCell(row, col)) {
        index = 0;
      } else {
        const regionRow = Math.floor(row / 3);
        const regionCol = Math.floor(col / 3);
        const wave = Math.sin((regionRow + seed) * 1.73) + Math.cos((regionCol - seed) * 1.19);
        index = 1 + Math.abs(Math.floor((wave + 2) * 997)) % Math.max(1, picked.length - 1);
      }
      state.coloring.cells[row][col] = picked[Math.min(index, picked.length - 1)].hex;
    }
  }
  setColoringChanged();
  toast(`已用 ${picked.length} 个色号生成连贯随机配色。`);
}

async function createColoring() {
  if (!state.activeProject || state.busy) return;
  if (state.coloringDirty && !window.confirm("重新生成轮廓会替换尚未保存的上色，继续吗？")) return;
  const size = validGridSize();
  if (!size) return;
  const payload = {
    ...size,
    coverage: Number(elements.coverage.value) / 100,
    padding: Number(elements.padding.value) / 100,
    smooth_cells: elements.smoothCells.checked ? 1 : 0,
    source: state.activeProject.assets.stylized ? "stylized" : "cutout",
    palette_codes: parsePaletteCodes(),
  };
  setBusy(true, `正在创建 ${size.cols} × ${size.rows} 轮廓方格`);
  try {
    const data = await api(`/api/projects/${state.activeProject.id}/coloring`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.coloring = data.coloring;
    resetPaintHistory();
    updateProject(data.project);
    setView("coloring");
    toast("轮廓与方格已生成，可以开始上色。所有处理都可撤销。");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function saveColoring({ quiet = false } = {}) {
  if (!state.activeProject || !state.coloring || state.busy) return false;
  if (!state.coloringDirty) return true;
  setBusy(true, "正在保存上色画布");
  try {
    const data = await api(`/api/projects/${state.activeProject.id}/coloring`, {
      method: "PUT",
      body: JSON.stringify({ cells: state.coloring.cells }),
    });
    state.coloring = data.coloring;
    state.coloringDirty = false;
    updateProject(data.project);
    if (!quiet) toast("上色已保存，并会作为最终图纸的颜色来源。");
    return true;
  } catch (error) {
    toast(error.message, "error");
    return false;
  } finally {
    setBusy(false);
    drawPaintCanvas();
  }
}

async function aiColoring() {
  if (!state.activeProject || !state.coloring || state.busy) return;
  if (!state.config?.model_api_configured) {
    toast("请先在服务端配置模型 API。", "error");
    return;
  }
  if (state.coloringDirty && !await saveColoring({ quiet: true })) return;
  setBusy(true, "AI 正在为锁定轮廓生成配色");
  try {
    const data = await api(`/api/projects/${state.activeProject.id}/coloring/ai`, {
      method: "POST",
      body: JSON.stringify({
        prompt: elements.aiColorPrompt.value.trim(),
        palette_codes: parsePaletteCodes(),
      }),
    });
    state.coloring = data.coloring;
    resetPaintHistory();
    updateProject(data.project);
    setView("coloring");
    toast("AI 配色已完成，轮廓和格子保持不变。");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function generatePattern() {
  if (!state.activeProject || state.busy) return;
  const size = validGridSize();
  if (!size) return;
  if (state.coloringDirty && !await saveColoring({ quiet: true })) return;
  const { cols, rows } = size;
  const payload = {
    cols,
    rows,
    coverage: Number(elements.coverage.value) / 100,
    padding: Number(elements.padding.value) / 100,
    smooth_cells: elements.smoothCells.checked ? 1 : 0,
    source: state.activeProject.has_coloring ? "painted" : state.activeProject.assets.stylized ? "stylized" : "cutout",
    palette_codes: parsePaletteCodes(),
  };
  setBusy(true, `正在生成 ${cols} × ${rows} 色号图`);
  try {
    const data = await api(`/api/projects/${state.activeProject.id}/pattern`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    updateProject(data.project);
    setView("pattern");
    toast("色号图纸已完成，可以导出 PNG、JSON 或 CSV。");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function openDeleteDialog(project) {
  if (state.busy) return;
  state.pendingDelete = project;
  elements.deleteProjectName.textContent = `删除“${project.name}”？`;
  elements.deleteDialog.showModal();
}

async function confirmDelete(event) {
  if (event.submitter?.value !== "confirm") return;
  event.preventDefault();
  const project = state.pendingDelete;
  if (!project) return;
  elements.confirmDeleteButton.disabled = true;
  try {
    await api(`/api/projects/${project.id}`, { method: "DELETE" });
    state.projects = state.projects.filter((item) => item.id !== project.id);
    const deletedActive = state.activeProject?.id === project.id;
    state.pendingDelete = null;
    elements.deleteDialog.close();
    renderProjectList();
    if (deletedActive) {
      if (state.projects[0]) await selectProject(state.projects[0]);
      else resetWorkspace();
    }
    toast("项目已删除。");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    elements.confirmDeleteButton.disabled = false;
  }
}

async function saveProfile(event) {
  if (event.submitter?.value !== "save") return;
  event.preventDefault();
  clearError(elements.profileError);
  try {
    const data = await api("/api/profile", {
      method: "PUT",
      body: JSON.stringify({
        display_name: elements.profileDisplayName.value.trim(),
        bio: elements.profileBio.value.trim(),
      }),
    });
    state.user = data.user;
    renderProfile();
    elements.profileDialog.close();
    toast("个人资料已保存。");
  } catch (error) {
    showError(elements.profileError, error.message);
  }
}

async function changePassword() {
  const current_password = elements.currentPassword.value;
  const new_password = elements.newPassword.value;
  if (!current_password || !new_password) {
    showError(elements.profileError, "请填写当前密码和新密码。");
    return;
  }
  elements.changePasswordButton.disabled = true;
  try {
    await api("/api/password", {
      method: "PUT",
      body: JSON.stringify({ current_password, new_password }),
    });
    elements.currentPassword.value = "";
    elements.newPassword.value = "";
    toast("密码已更新，请重新登录后继续使用。");
  } catch (error) {
    showError(elements.profileError, error.message);
  } finally {
    elements.changePasswordButton.disabled = false;
  }
}

async function exportAccount() {
  elements.exportAccountButton.disabled = true;
  try {
    const data = await api("/api/account/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "pindou-account-export.json";
    link.click();
    URL.revokeObjectURL(url);
    toast("账户数据已导出。");
  } catch (error) {
    showError(elements.profileError, error.message);
  } finally {
    elements.exportAccountButton.disabled = false;
  }
}

async function deleteAccount() {
  const password = window.prompt("请输入当前密码以确认注销账户。此操作不可撤销。", "");
  if (password === null) return;
  try {
    await api("/api/account", { method: "DELETE", body: JSON.stringify({ password }) });
    elements.profileDialog.close();
    showAuth();
    toast("账户及其项目已删除。");
  } catch (error) {
    showError(elements.profileError, error.message);
  }
}

async function logout() {
  if (state.coloringDirty && !await saveColoring({ quiet: true })) return;
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch (error) {
    console.warn(error);
  }
  elements.profileDialog.close();
  showAuth();
}

function applyTheme(theme) {
  if (theme === "light" || theme === "dark") {
    document.documentElement.dataset.theme = theme;
  } else {
    delete document.documentElement.dataset.theme;
  }
}

function toggleTheme() {
  const currentDark = document.documentElement.dataset.theme === "dark"
    || (!document.documentElement.dataset.theme && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const next = currentDark ? "light" : "dark";
  localStorage.setItem("pindou-theme", next);
  applyTheme(next);
}

function handleWorkflowClick(event) {
  const step = event.currentTarget.dataset.step;
  if (step === "upload") {
    elements.fileInput.click();
  } else if (!state.activeProject) {
    toast("请先上传一张图片。", "error");
  } else if (step === "select") {
    setView("source");
    elements.canvas.focus();
  } else if (step === "extract") {
    if (state.activeProject.assets.cutout) setView("cutout");
    else toast("先在原图上框选并抠出主体。", "error");
  } else if (step === "stylize") {
    if (state.activeProject.assets.stylized) setView("stylized");
    else toast("先完成抠图，再生成像素图。", "error");
  } else if (step === "coloring") {
    if (state.coloring) setView("coloring");
    else toast("先生成轮廓与方格，再进入上色工作台。", "error");
  } else if (step === "pattern") {
    if (state.activeProject.assets.pattern) setView("pattern");
    else toast("设置格子宽高后生成色号图。", "error");
  }
}

function bindEvents() {
  elements.loginTab.addEventListener("click", () => setAuthMode("login"));
  elements.registerTab.addEventListener("click", () => setAuthMode("register"));
  elements.authForm.addEventListener("submit", handleAuthSubmit);

  [elements.newProjectButton, elements.sidebarUpload, elements.emptyUpload].forEach((button) => {
    button.addEventListener("click", () => elements.fileInput.click());
  });
  elements.fileInput.addEventListener("change", () => uploadFile(elements.fileInput.files?.[0]));

  elements.canvasStage.addEventListener("dragover", (event) => {
    if (!state.busy) event.preventDefault();
  });
  elements.canvasStage.addEventListener("drop", (event) => {
    event.preventDefault();
    uploadFile(event.dataTransfer?.files?.[0]);
  });

  elements.canvas.addEventListener("pointerdown", startSelection);
  elements.canvas.addEventListener("pointermove", moveSelection);
  elements.canvas.addEventListener("pointerup", endSelection);
  elements.canvas.addEventListener("pointercancel", endSelection);
  elements.paintCanvas.addEventListener("pointerdown", startPainting);
  elements.paintCanvas.addEventListener("pointermove", movePainting);
  elements.paintCanvas.addEventListener("pointerup", endPainting);
  elements.paintCanvas.addEventListener("pointercancel", endPainting);
  elements.selectAllButton.addEventListener("click", selectWholeImage);
  elements.clearSelectionButton.addEventListener("click", clearSelection);
  elements.extractButton.addEventListener("click", extractSubject);
  elements.refineMaskButton.addEventListener("click", beginMaskRefine);
  elements.saveMaskRefineButton.addEventListener("click", applyMaskRefine);
  elements.cancelMaskRefineButton.addEventListener("click", cancelMaskRefine);
  elements.maskBrushRadius.addEventListener("input", () => {
    elements.maskBrushRadiusValue.textContent = `${elements.maskBrushRadius.value} px`;
    drawCanvas();
  });
  $$(".mask-mode-button").forEach((button) => {
    button.addEventListener("click", () => setMaskMode(button.dataset.maskMode));
  });
  elements.stylizeButton.addEventListener("click", stylizeSubject);
  elements.createColoringButton.addEventListener("click", createColoring);
  elements.saveColoringButton.addEventListener("click", () => saveColoring());
  elements.aiColorButton.addEventListener("click", aiColoring);
  elements.randomColorButton.addEventListener("click", randomizeColors);
  elements.clearPaintButton.addEventListener("click", clearPaintColors);
  elements.undoPaintButton.addEventListener("click", undoPaint);
  elements.redoPaintButton.addEventListener("click", redoPaint);
  elements.patternButton.addEventListener("click", generatePattern);
  elements.paintColor.addEventListener("input", () => setPaintColor(elements.paintColor.value));
  $$(".paint-tool").forEach((button) => {
    button.addEventListener("click", () => setPaintTool(button.dataset.paintTool));
  });

  $$("input[name='provider']").forEach((input) => input.addEventListener("change", updateProviderOptions));
  [elements.coverage, elements.padding].forEach((input) => input.addEventListener("input", updateRangeLabels));
  $$(".view-tab").forEach((tab) => tab.addEventListener("click", () => setView(tab.dataset.view)));
  $$(".workflow-step").forEach((step) => step.addEventListener("click", handleWorkflowClick));

  elements.profileButton.addEventListener("click", () => {
    clearError(elements.profileError);
    renderProfile();
    elements.profileDialog.showModal();
    loadAccountPanel();
  });
  elements.profileForm.addEventListener("submit", saveProfile);
  elements.sendMessageButton.addEventListener("click", sendMessage);
  elements.logoutButton.addEventListener("click", logout);
  elements.cancelJobButton.addEventListener("click", cancelCurrentJob);
  elements.changePasswordButton.addEventListener("click", changePassword);
  elements.exportAccountButton.addEventListener("click", exportAccount);
  elements.deleteAccountButton.addEventListener("click", deleteAccount);
  $("form", elements.deleteDialog).addEventListener("submit", confirmDelete);
  elements.themeToggle.addEventListener("click", toggleTheme);
  window.addEventListener("beforeunload", (event) => {
    if (!state.coloringDirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  document.addEventListener("keydown", (event) => {
    const tag = document.activeElement?.tagName;
    const editing = tag === "INPUT" || tag === "TEXTAREA";
    if (editing) return;
    const modifier = event.ctrlKey || event.metaKey;
    if (state.activeView === "coloring" && modifier && event.key.toLowerCase() === "z") {
      event.preventDefault();
      if (event.shiftKey) redoPaint();
      else undoPaint();
      return;
    }
    if (state.activeView === "coloring" && modifier && event.key.toLowerCase() === "y") {
      event.preventDefault();
      redoPaint();
      return;
    }
    if (event.key === "Escape" && !elements.profileDialog.open && !elements.deleteDialog.open && state.activeView === "source") {
      clearSelection();
    }
    if (event.key.toLowerCase() === "a" && state.activeProject && state.activeView === "source") {
      event.preventDefault();
      selectWholeImage();
    }
    if (event.key.toLowerCase() === "v" && state.activeProject) {
      setView("source");
      elements.canvas.focus();
    }
    if (state.activeView === "coloring") {
      const tools = { b: "brush", g: "fill", e: "eraser", i: "eyedropper" };
      if (tools[event.key.toLowerCase()]) setPaintTool(tools[event.key.toLowerCase()]);
    }
  });
}

async function initialize() {
  bindEvents();
  setPaintTool("brush");
  applyTheme(localStorage.getItem("pindou-theme") || "system");
  setAuthMode("login");
  resetWorkspace();
  try {
    state.config = await api("/api/config");
    elements.modelPrompt.value = state.config.default_prompt || "";
    elements.aiColorPrompt.value = state.config.default_coloring_prompt || "";
    const modelInput = $("input[value='model']");
    modelInput.disabled = !state.config.model_api_configured;
    elements.modelProviderLabel.title = state.config.model_api_configured
      ? "使用服务端配置的模型 API"
      : "需要配置 PINDOU_MODEL_API_URL";
    elements.modelStatus.textContent = state.config.model_api_configured ? "模型已连接" : "本地可用";
    elements.aiColorBadge.textContent = state.config.model_api_configured ? "模型已连接" : "需配置 API";
  } catch (error) {
    console.warn(error);
  }

  try {
    const data = await api("/api/auth/me");
    state.user = data.user;
    showApp();
    await loadPalette();
    setPaintColor(state.paintColor);
    await loadProjects();
  } catch (error) {
    showAuth();
  }
}

initialize();
