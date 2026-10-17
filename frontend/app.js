const state = {
  documents: [],
  taxonomies: [],
  runs: [],
  results: [],
  selectedDocumentIds: new Set(),
  activeDocument: null,
  activeResult: null,
  generatedSchemes: [],
  taxonomyOrigin: "manual",
  editingTaxonomyId: null,
  activeResultTaxonomyId: null,
  activeResultRunId: null,
  activeResultCategoryKey: null,
  zoteroPreview: null,
  generationConfigured: false,
  jevConnectionStatus: null,
};

const elements = {
  health: document.querySelector("#health-status"),
  documentGroups: document.querySelector("#document-groups"),
  documentEmpty: document.querySelector("#document-empty"),
  taxonomyList: document.querySelector("#taxonomy-list"),
  taxonomyEmpty: document.querySelector("#taxonomy-empty"),
  resultBrowser: document.querySelector("#result-browser"),
  resultTaxonomyFilter: document.querySelector("#result-taxonomy-filter"),
  resultRunFilter: document.querySelector("#result-run-filter"),
  deleteResultRunButton: document.querySelector("#delete-result-run-button"),
  resultExportActions: document.querySelector("#result-export-actions"),
  openZoteroImportButton: document.querySelector("#open-zotero-import-button"),
  exportResultsCsv: document.querySelector("#export-results-csv"),
  exportResultsJson: document.querySelector("#export-results-json"),
  resultCategoryTabs: document.querySelector("#result-category-tabs"),
  resultTableHost: document.querySelector("#result-table-host"),
  resultEmpty: document.querySelector("#result-empty"),
  fileInput: document.querySelector("#file-input"),
  uploadForm: document.querySelector("#upload-form"),
  categoryEditor: document.querySelector("#category-editor"),
  taxonomySelect: document.querySelector("#run-taxonomy-select"),
  modelSettingsDialog: document.querySelector("#model-settings-dialog"),
  modelSettingsForm: document.querySelector("#model-settings-form"),
  documentDialog: document.querySelector("#document-dialog"),
  resultDialog: document.querySelector("#result-dialog"),
  zoteroImportDialog: document.querySelector("#zotero-import-dialog"),
  zoteroImportForm: document.querySelector("#zotero-import-form"),
  zoteroImportStatus: document.querySelector("#zotero-import-status"),
  zoteroImportSummary: document.querySelector("#zotero-import-summary"),
  zoteroImportList: document.querySelector("#zotero-import-list"),
  zoteroWriteTags: document.querySelector("#zotero-write-tags"),
  zoteroWriteCollections: document.querySelector("#zotero-write-collections"),
  confirmZoteroImportButton: document.querySelector("#confirm-zotero-import-button"),
  notificationRegion: document.querySelector("#notification-region"),
  generationModeButton: document.querySelector('[data-taxonomy-mode="generated"]'),
  generationUnavailableNotice: document.querySelector("#generation-unavailable-notice"),
};

async function responseErrorMessage(response) {
  let message = `请求失败 (${response.status})`;
  try {
    const payload = await response.json();
    message = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
  } catch (_) {
    // Keep the HTTP fallback when a proxy returns a non-JSON error page.
  }
  return message;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(await responseErrorMessage(response));
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response.text();
}

function toast(message, type = "success") {
  const notificationType = ["success", "error", "warning", "info"].includes(type)
    ? type
    : "info";
  const titles = {
    success: "操作成功",
    error: "操作失败",
    warning: "请注意",
    info: "提示",
  };
  const region = elements.notificationRegion;
  const duplicate = [...region.children].find(
    (item) => item.dataset.message === message && item.dataset.type === notificationType,
  );
  if (duplicate) duplicate.remove();
  while (region.children.length >= 4) region.firstElementChild.remove();

  const item = document.createElement("section");
  item.className = `notification ${notificationType}`;
  item.dataset.message = message;
  item.dataset.type = notificationType;
  item.setAttribute("role", notificationType === "error" ? "alert" : "status");

  const content = document.createElement("div");
  content.className = "notification-content";
  const title = document.createElement("strong");
  title.textContent = titles[notificationType];
  const detail = document.createElement("p");
  detail.textContent = message;
  content.append(title, detail);

  const close = document.createElement("button");
  close.className = "notification-close";
  close.type = "button";
  close.textContent = "×";
  close.setAttribute("aria-label", "关闭通知");

  let timeoutId;
  const remove = () => {
    window.clearTimeout(timeoutId);
    item.remove();
    if (
      !region.childElementCount
      && typeof region.hidePopover === "function"
      && region.matches(":popover-open")
    ) {
      region.hidePopover();
    }
  };
  const scheduleRemoval = () => {
    const delay = { success: 4500, info: 5200, warning: 7000, error: 9000 }[notificationType];
    timeoutId = window.setTimeout(remove, delay);
  };
  close.addEventListener("click", remove);
  item.addEventListener("mouseenter", () => window.clearTimeout(timeoutId));
  item.addEventListener("mouseleave", scheduleRemoval);
  item.append(content, close);
  region.append(item);

  if (typeof region.showPopover === "function") {
    if (!region.matches(":popover-open")) region.showPopover();
  } else {
    region.removeAttribute("popover");
  }
  scheduleRemoval();
}

async function downloadResultExport(event, format) {
  event.preventDefault();
  const link = event.currentTarget;
  if (link.dataset.downloading === "true") return;
  link.dataset.downloading = "true";
  link.setAttribute("aria-busy", "true");
  try {
    const response = await fetch(link.href);
    if (!response.ok) throw new Error(await responseErrorMessage(response));
    const blobUrl = URL.createObjectURL(await response.blob());
    const download = document.createElement("a");
    const disposition = response.headers.get("content-disposition") || "";
    const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1]
      || `classifications.${format}`;
    download.href = blobUrl;
    download.download = filename;
    document.body.append(download);
    download.click();
    download.remove();
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 0);
    toast(`当前运行批次的 ${format.toUpperCase()} 已导出`);
  } catch (error) {
    toast(error.message, "error");
  } finally {
    delete link.dataset.downloading;
    link.removeAttribute("aria-busy");
  }
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function formatPercent(value) {
  return value == null ? "-" : `${(value * 100).toFixed(1)}%`;
}

function slugify(value) {
  const ascii = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\s_-]/g, "")
    .replace(/[\s-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return ascii.slice(0, 72).replace(/_+$/g, "");
}

function setView(viewName) {
  document.querySelectorAll(".view").forEach((view) => view.classList.remove("is-active"));
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.remove("is-active");
    item.removeAttribute("aria-current");
  });
  document.querySelector(`#view-${viewName}`).classList.add("is-active");
  const activeItem = document.querySelector(`[data-view="${viewName}"]`);
  activeItem.classList.add("is-active");
  activeItem.setAttribute("aria-current", "page");
}

function updateCounters() {
  const ready = state.documents.filter(
    (item) => item.parse_status === "ready" && item.metadata_status === "confirmed",
  ).length;
  const errors = state.documents.length - ready;
  document.querySelector("#metric-total").textContent = state.documents.length;
  document.querySelector("#metric-ready").textContent = ready;
  document.querySelector("#metric-errors").textContent = errors;
  document.querySelector("#nav-document-count").textContent = state.documents.length;
  document.querySelector("#nav-selected-count").textContent = state.selectedDocumentIds.size;
  document.querySelector("#run-selected-count").textContent = `${state.selectedDocumentIds.size} 篇文献待分类`;
  document.querySelector("#document-selection-label").textContent = state.selectedDocumentIds.size
    ? `已选择 ${state.selectedDocumentIds.size} 篇`
    : "尚未选择文献";
}

function isDocumentReady(item) {
  return item.parse_status === "ready" && item.metadata_status === "confirmed";
}

function localDateKey(value) {
  const date = new Date(value);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function relativeDateLabel(key) {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (key === localDateKey(today)) return "今天上传";
  if (key === localDateKey(yesterday)) return "昨天上传";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(new Date(`${key}T00:00:00`));
}

function createDocumentRow(item) {
  const row = document.createElement("tr");
  const selectable = isDocumentReady(item);

  const checkCell = document.createElement("td");
  checkCell.className = "check-cell";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.disabled = !selectable;
  checkbox.checked = state.selectedDocumentIds.has(item.id);
  checkbox.setAttribute("aria-label", `选择 ${item.title || item.original_name}`);
  checkbox.addEventListener("change", () => {
    checkbox.checked
      ? state.selectedDocumentIds.add(item.id)
      : state.selectedDocumentIds.delete(item.id);
    updateCounters();
  });
  checkCell.append(checkbox);

  const titleCell = document.createElement("td");
  titleCell.className = "document-cell";
  const title = document.createElement("strong");
  title.textContent = item.title || item.original_name;
  const filename = document.createElement("span");
  filename.textContent = item.original_name;
  titleCell.append(title, filename);

  const abstractCell = document.createElement("td");
  abstractCell.textContent = item.abstract ? "已提取" : "未识别";
  const statusCell = document.createElement("td");
  const status = document.createElement("span");
  const needsConfirmation = item.metadata_status !== "confirmed";
  status.className = `status ${item.parse_status === "error" ? "error" : needsConfirmation ? "pending" : "ready"}`;
  status.textContent = item.parse_status === "error" ? "解析失败" : needsConfirmation ? "需要确认" : "可分类";
  status.title = item.parse_error || "";
  statusCell.append(status);
  const sizeCell = document.createElement("td");
  sizeCell.textContent = formatBytes(item.size_bytes);
  const actionCell = document.createElement("td");
  const editButton = document.createElement("button");
  editButton.className = "button text-button table-action";
  editButton.type = "button";
  editButton.textContent = selectable ? "查看/修正" : "处理";
  editButton.addEventListener("click", () => openDocumentEditor(item));
  actionCell.append(editButton);
  row.append(checkCell, titleCell, abstractCell, statusCell, sizeCell, actionCell);
  return row;
}

function createDocumentGroup({ label, items, attention = false, open = false }) {
  const group = document.createElement("details");
  group.className = `document-group${attention ? " needs-attention" : ""}`;
  group.open = open;

  const summary = document.createElement("summary");
  const heading = document.createElement("strong");
  heading.textContent = label;
  const meta = document.createElement("span");
  meta.textContent = attention
    ? `${items.length} 篇需要处理`
    : `${items.length} 篇文献`;
  summary.append(heading, meta);

  const tableWrap = document.createElement("div");
  tableWrap.className = "table-wrap";
  const table = document.createElement("table");
  table.innerHTML = `
    <thead><tr>
      <th class="check-cell"><span class="sr-only">选择</span></th>
      <th>文献</th><th>摘要</th><th>状态</th><th>大小</th><th>操作</th>
    </tr></thead>`;
  const body = document.createElement("tbody");
  items.forEach((item) => body.append(createDocumentRow(item)));
  table.append(body);
  tableWrap.append(table);
  group.append(summary, tableWrap);
  return group;
}

function renderDocuments() {
  elements.documentGroups.replaceChildren();
  elements.documentEmpty.classList.toggle("is-hidden", state.documents.length > 0);
  if (!state.documents.length) {
    updateCounters();
    return;
  }

  const attention = state.documents.filter((item) => !isDocumentReady(item));
  if (attention.length) {
    elements.documentGroups.append(
      createDocumentGroup({ label: "需要处理", items: attention, attention: true, open: true }),
    );
  }

  const documentsByDate = new Map();
  state.documents.filter(isDocumentReady).forEach((item) => {
    const key = localDateKey(item.created_at);
    if (!documentsByDate.has(key)) documentsByDate.set(key, []);
    documentsByDate.get(key).push(item);
  });
  [...documentsByDate.entries()].forEach(([key, items], index) => {
    elements.documentGroups.append(
      createDocumentGroup({ label: relativeDateLabel(key), items, open: index === 0 }),
    );
  });
  updateCounters();
}

async function loadDocuments() {
  state.documents = await api("/api/documents");
  const validIds = new Set(
    state.documents
      .filter(isDocumentReady)
      .map((item) => item.id),
  );
  state.selectedDocumentIds = new Set(
    [...state.selectedDocumentIds].filter((documentId) => validIds.has(documentId)),
  );
  renderDocuments();
}

async function uploadFiles(files) {
  if (!files.length) return;
  const button = document.querySelector("#upload-button");
  button.disabled = true;
  button.textContent = "正在上传";
  try {
    const body = new FormData();
    [...files].forEach((file) => body.append("files", file));
    const uploaded = await api("/api/documents/upload", { method: "POST", body });
    const duplicateCount = uploaded.filter((item) => item.duplicate).length;
    const newDocuments = uploaded.filter((item) => !item.duplicate);
    const readyCount = newDocuments.filter(isDocumentReady).length;
    const reviewCount = newDocuments.length - readyCount;
    const parts = [`${readyCount} 篇可直接分类`];
    if (reviewCount) parts.push(`${reviewCount} 篇需要处理`);
    if (duplicateCount) parts.push(`${duplicateCount} 篇已存在`);
    toast(parts.join("，"));
    await loadDocuments();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "选择 PDF";
    elements.fileInput.value = "";
  }
}

function openDocumentEditor(item) {
  state.activeDocument = item;
  document.querySelector("#document-dialog-title").textContent = item.title || item.original_name;
  document.querySelector("#document-dialog-file").textContent = item.original_name;
  document.querySelector("#document-title-input").value = item.title || "";
  document.querySelector("#document-abstract-input").value = item.abstract || "";
  document.querySelector("#document-keywords-input").value = item.keywords.join("，");
  document.querySelector("#extracted-title").textContent = item.extracted_title || "未识别";
  document.querySelector("#extracted-abstract").textContent = item.extracted_abstract || "未识别";
  document.querySelector("#extracted-keywords").textContent = item.extracted_keywords.join("，") || "未识别";

  const warningList = document.querySelector("#document-warning-list");
  warningList.replaceChildren();
  const warnings = item.quality_warnings.length ? item.quality_warnings : ["未发现明显的解析问题"];
  for (const warning of warnings) {
    const badge = document.createElement("span");
    badge.className = `quality-warning ${item.quality_warnings.length ? "" : "is-ok"}`;
    badge.textContent = warning;
    warningList.append(badge);
  }
  elements.documentDialog.showModal();
}

async function saveDocumentMetadata(event) {
  event.preventDefault();
  if (!state.activeDocument) return;
  const submit = event.submitter || event.currentTarget.querySelector('[type="submit"]');
  submit.disabled = true;
  try {
    const keywords = document
      .querySelector("#document-keywords-input")
      .value.split(/[,，;；\n]/)
      .map((value) => value.trim())
      .filter(Boolean);
    await api(`/api/documents/${state.activeDocument.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: document.querySelector("#document-title-input").value.trim(),
        abstract: document.querySelector("#document-abstract-input").value.trim(),
        keywords,
      }),
    });
    elements.documentDialog.close();
    state.activeDocument = null;
    await loadDocuments();
    toast("元数据已保存并确认");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    submit.disabled = false;
  }
}

function addCategoryRow(category = {}) {
  const row = document.createElement("div");
  row.className = "category-row";

  const codeInput = document.createElement("input");
  codeInput.type = "hidden";
  codeInput.className = "category-code";
  codeInput.value = category.code || "";

  const nameLabel = document.createElement("label");
  nameLabel.innerHTML = "<span>类别名称</span>";
  const nameInput = document.createElement("input");
  nameInput.className = "category-name";
  nameInput.required = true;
  nameInput.value = category.name || "";
  nameLabel.append(nameInput);

  const definitionLabel = document.createElement("label");
  definitionLabel.innerHTML = "<span>定义与边界</span>";
  const definitionInput = document.createElement("textarea");
  definitionInput.className = "category-definition";
  definitionInput.required = true;
  definitionInput.rows = 2;
  definitionInput.placeholder = "说明纳入内容，并指出与相邻类别的区别";
  definitionInput.value = category.definition || "";
  definitionInput.dataset.inclusion = category.inclusion || "";
  definitionInput.dataset.exclusion = category.exclusion || "";
  definitionLabel.append(definitionInput);

  const remove = document.createElement("button");
  remove.className = "icon-button";
  remove.type = "button";
  remove.textContent = "×";
  remove.setAttribute("aria-label", "删除类别");
  remove.addEventListener("click", () => {
    if (elements.categoryEditor.children.length <= 2) {
      toast("至少保留两个类别", "warning");
      return;
    }
    row.remove();
  });

  row.append(codeInput, nameLabel, definitionLabel, remove);
  elements.categoryEditor.append(row);
}

function collectCategories() {
  const usedCodes = new Set(["none_of_above"]);
  return [...elements.categoryEditor.querySelectorAll(".category-row")].map((row, index) => {
    const definition = row.querySelector(".category-definition");
    const name = row.querySelector(".category-name").value.trim();
    const storedCode = row.querySelector(".category-code").value.trim();
    const baseCode = storedCode || slugify(name) || `category_${index + 1}`;
    let code = baseCode;
    let suffix = 2;
    while (usedCodes.has(code)) {
      code = `${baseCode}_${suffix}`;
      suffix += 1;
    }
    usedCodes.add(code);
    return {
      code,
      name,
      definition: definition.value.trim(),
      inclusion: definition.dataset.inclusion || "",
      exclusion: definition.dataset.exclusion || "",
    };
  });
}

function taxonomyRootId(taxonomy, byId) {
  let current = taxonomy;
  const visited = new Set();
  while (current.parent_id && byId.has(current.parent_id) && !visited.has(current.id)) {
    visited.add(current.id);
    current = byId.get(current.parent_id);
  }
  return current.id;
}

function createTaxonomyItem(taxonomy, editable) {
  const item = document.createElement("article");
  item.className = `taxonomy-item${editable ? " is-current" : " is-history"}`;

  const main = document.createElement("div");
  main.className = "taxonomy-item-main";
  const title = document.createElement("div");
  title.className = "taxonomy-title";
  const name = document.createElement("h3");
  name.textContent = taxonomy.name;
  const status = document.createElement("span");
  status.className = `status ${editable ? "ready" : "history"}`;
  status.textContent = editable ? "当前版本" : "历史版本";
  title.append(name, status);

  const description = document.createElement("p");
  description.textContent = taxonomy.objective || "未填写分类目的";
  const meta = document.createElement("div");
  meta.className = "taxonomy-meta";
  const count = document.createElement("span");
  count.textContent = `${taxonomy.categories.length} 个类别`;
  const version = document.createElement("span");
  version.textContent = `版本 ${taxonomy.version}`;
  meta.append(count, version);
  if (editable) {
    const actions = document.createElement("div");
    actions.className = "taxonomy-actions";
    const edit = document.createElement("button");
    edit.className = "button secondary taxonomy-edit-button";
    edit.type = "button";
    edit.textContent = "编辑并创建新版本";
    edit.addEventListener("click", () => beginTaxonomyEdit(taxonomy));
    const remove = document.createElement("button");
    remove.className = "button danger taxonomy-delete-button";
    remove.type = "button";
    remove.textContent = "删除分类体系";
    remove.addEventListener("click", () => deleteTaxonomy(taxonomy));
    actions.append(edit, remove);
    meta.append(actions);
  }
  main.append(title, description, meta);

  const categories = document.createElement("details");
  categories.className = "taxonomy-categories";
  const summary = document.createElement("summary");
  summary.textContent = `查看 ${taxonomy.categories.length} 个类别边界`;
  const categoryList = document.createElement("div");
  categoryList.className = "taxonomy-category-list";
  taxonomy.categories.forEach((category) => {
    const row = document.createElement("div");
    const heading = document.createElement("div");
    const categoryName = document.createElement("strong");
    categoryName.textContent = category.name;
    heading.append(categoryName);
    const definition = document.createElement("p");
    definition.textContent = category.definition;
    row.append(heading, definition);
    if (category.inclusion) {
      const inclusion = document.createElement("span");
      inclusion.textContent = `纳入：${category.inclusion}`;
      row.append(inclusion);
    }
    if (category.exclusion) {
      const exclusion = document.createElement("span");
      exclusion.textContent = `排除：${category.exclusion}`;
      row.append(exclusion);
    }
    categoryList.append(row);
  });
  categories.append(summary, categoryList);
  item.append(main, categories);
  return item;
}

function renderTaxonomies() {
  elements.taxonomyList.replaceChildren();
  elements.taxonomyEmpty.classList.toggle("is-hidden", state.taxonomies.length > 0);
  elements.taxonomySelect.replaceChildren();

  const activeTaxonomies = state.taxonomies.filter((taxonomy) => taxonomy.status === "active");
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = activeTaxonomies.length ? "请选择当前分类体系" : "尚无可用分类体系";
  elements.taxonomySelect.append(placeholder);
  activeTaxonomies.forEach((taxonomy) => {
    const option = document.createElement("option");
    option.value = taxonomy.id;
    option.textContent = `${taxonomy.name} · 版本 ${taxonomy.version} (${taxonomy.categories.length} 类)`;
    elements.taxonomySelect.append(option);
  });

  const byId = new Map(state.taxonomies.map((taxonomy) => [taxonomy.id, taxonomy]));
  const families = new Map();
  state.taxonomies.forEach((taxonomy) => {
    const rootId = taxonomyRootId(taxonomy, byId);
    if (!families.has(rootId)) families.set(rootId, []);
    families.get(rootId).push(taxonomy);
  });

  families.forEach((versions) => {
    versions.sort((left, right) => right.version - left.version);
    const current = versions.find((taxonomy) => taxonomy.status === "active") || versions[0];
    const family = document.createElement("section");
    family.className = "taxonomy-family";
    family.append(createTaxonomyItem(current, current.status === "active"));
    const history = versions.filter((taxonomy) => taxonomy.id !== current.id);
    if (history.length) {
      const historyPanel = document.createElement("details");
      historyPanel.className = "taxonomy-history";
      const historySummary = document.createElement("summary");
      historySummary.textContent = `查看 ${history.length} 个历史版本`;
      const historyList = document.createElement("div");
      history.forEach((taxonomy) => historyList.append(createTaxonomyItem(taxonomy, false)));
      historyPanel.append(historySummary, historyList);
      family.append(historyPanel);
    }
    elements.taxonomyList.append(family);
  });
}

async function loadTaxonomies() {
  state.taxonomies = await api("/api/taxonomies");
  renderTaxonomies();
}

async function deleteTaxonomy(taxonomy) {
  const confirmed = window.confirm(
    `确定删除“${taxonomy.name}”及其全部历史版本吗？\n\n对应的分类运行和全部分类结果也会永久删除，且无法恢复。`,
  );
  if (!confirmed) return;
  try {
    await api(`/api/taxonomies/${taxonomy.id}`, { method: "DELETE" });
    if (state.editingTaxonomyId === taxonomy.id) resetTaxonomyEditor();
    await Promise.all([loadTaxonomies(), loadResults()]);
    toast("分类体系及对应分类结果已删除");
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderSchemes() {
  const container = document.querySelector("#scheme-candidates");
  container.replaceChildren();
  state.generatedSchemes.forEach((scheme, index) => {
    const article = document.createElement("article");
    article.className = "scheme-item";
    const header = document.createElement("div");
    header.className = "scheme-item-header";
    const copy = document.createElement("div");
    const title = document.createElement("h3");
    title.textContent = scheme.name;
    const description = document.createElement("p");
    description.textContent = scheme.description;
    copy.append(title, description);
    const useButton = document.createElement("button");
    useButton.className = "button secondary";
    useButton.type = "button";
    useButton.textContent = "选择此方案";
    useButton.addEventListener("click", () => useGeneratedScheme(index));
    header.append(copy, useButton);
    const categories = document.createElement("div");
    categories.className = "scheme-categories";
    scheme.categories.forEach((category) => {
      const cell = document.createElement("div");
      cell.className = "scheme-category";
      const name = document.createElement("strong");
      name.textContent = category.name;
      const definition = document.createElement("span");
      definition.textContent = category.definition;
      cell.append(name, definition);
      categories.append(cell);
    });
    article.append(header, categories);
    container.append(article);
  });
}

function switchTaxonomyMode(mode) {
  if (mode === "generated" && !state.generationConfigured) {
    toast("请先在模型设置中配置通用大模型；自定义分类体系分类体系仍可正常使用", "warning");
    return;
  }
  if (mode === "generated" && state.editingTaxonomyId) resetTaxonomyEditor();
  if (mode === "manual") state.taxonomyOrigin = "manual";
  document.querySelectorAll("[data-taxonomy-mode]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.taxonomyMode === mode);
  });
  document.querySelector("#manual-taxonomy-form").classList.toggle("is-hidden", mode !== "manual");
  document.querySelector("#generate-taxonomy-form").classList.toggle("is-hidden", mode !== "generated");
}

function resetTaxonomyEditor() {
  state.editingTaxonomyId = null;
  state.taxonomyOrigin = "manual";
  document.querySelector("#manual-taxonomy-form").reset();
  document.querySelector("#taxonomy-edit-context").classList.add("is-hidden");
  document.querySelector("#save-taxonomy-button").textContent = "保存分类体系";
  elements.categoryEditor.replaceChildren();
  addCategoryRow({ code: "category_a", name: "类别 A", definition: "请填写清晰的类别定义" });
  addCategoryRow({ code: "category_b", name: "类别 B", definition: "请填写与其他类别不同的边界" });
}

function beginTaxonomyEdit(taxonomy) {
  switchTaxonomyMode("manual");
  state.editingTaxonomyId = taxonomy.id;
  state.taxonomyOrigin = taxonomy.mode;
  document.querySelector("#taxonomy-name").value = taxonomy.name;
  document.querySelector("#taxonomy-objective").value = taxonomy.objective;
  elements.categoryEditor.replaceChildren();
  taxonomy.categories.forEach(addCategoryRow);
  document.querySelector("#taxonomy-edit-label").textContent =
    `正在编辑“${taxonomy.name}”版本 ${taxonomy.version}`;
  document.querySelector("#taxonomy-edit-context").classList.remove("is-hidden");
  document.querySelector("#save-taxonomy-button").textContent =
    `保存为版本 ${taxonomy.version + 1}`;
  document.querySelector("#manual-taxonomy-form").scrollIntoView({ behavior: "smooth", block: "start" });
}

function useGeneratedScheme(index) {
  const scheme = state.generatedSchemes[index];
  resetTaxonomyEditor();
  document.querySelector("#taxonomy-name").value = scheme.name;
  document.querySelector("#taxonomy-objective").value = document.querySelector("#generation-objective").value;
  elements.categoryEditor.replaceChildren();
  scheme.categories.forEach(addCategoryRow);
  switchTaxonomyMode("manual");
  state.taxonomyOrigin = "generated";
  toast("候选方案已载入，可编辑后保存");
}

function statusLabel(value) {
  const labels = {
    pending: "待复核",
    confirmed: "已确认",
    corrected: "已修正",
    deferred: "暂不分类",
    unclassified: "未分类",
    propose_new: "未分类",
  };
  return labels[value] || value;
}

function runStatusLabel(value) {
  const labels = {
    queued: "等待中",
    running: "运行中",
    completed: "已完成",
    completed_with_errors: "部分失败",
    failed: "失败",
  };
  return labels[value] || value;
}

function formatDateTime(value) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function needsReview(result) {
  return Boolean(result.error_message)
    || !["confirmed", "corrected", "unclassified", "propose_new"].includes(result.review_status);
}

function createResultTable(results) {
  const wrapper = document.createElement("div");
  wrapper.className = "table-wrap result-table";
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  ["文献", "总体置信度", "复核状态", "输入", "操作"].forEach((label) => {
    const cell = document.createElement("th");
    cell.textContent = label;
    headRow.append(cell);
  });
  head.append(headRow);
  const body = document.createElement("tbody");

  results.forEach((result) => {
    const row = document.createElement("tr");
    row.className = "clickable";
    row.tabIndex = 0;
    row.addEventListener("click", () => openResult(result));
    row.addEventListener("keydown", (event) => {
      if (event.target !== row) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openResult(result);
      }
    });

    const documentCell = document.createElement("td");
    documentCell.className = "document-cell";
    const title = document.createElement("strong");
    title.textContent = result.document_title || result.document_name;
    const filename = document.createElement("span");
    filename.textContent = result.document_name;
    documentCell.append(title, filename);

    const confidenceCell = document.createElement("td");
    confidenceCell.className = "confidence-value";
    confidenceCell.textContent = formatPercent(result.confidence);
    const reviewCell = document.createElement("td");
    const status = document.createElement("span");
    status.className = `status ${result.error_message ? "error" : result.review_status}`;
    status.textContent = result.error_message ? "需要处理" : statusLabel(result.review_status);
    reviewCell.append(status);
    const inputCell = document.createElement("td");
    inputCell.textContent = result.input_level;
    const actionCell = document.createElement("td");
    const remove = document.createElement("button");
    remove.className = "button text-button result-delete-button";
    remove.type = "button";
    remove.textContent = "删除";
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteResult(result, remove);
    });
    actionCell.append(remove);
    row.append(documentCell, confidenceCell, reviewCell, inputCell, actionCell);
    body.append(row);
  });
  table.append(head, body);
  wrapper.append(table);
  return wrapper;
}

function resultGroupsForRun(runId) {
  const groups = new Map();
  state.results.filter((result) => result.run_id === runId).forEach((result) => {
    const key = result.error_message
      ? "__error__"
      : result.reviewed_category_code || result.category_code || "__unassigned__";
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        label: result.error_message ? "分类失败" : result.category_name || "未分类",
        results: [],
      });
    }
    groups.get(key).results.push(result);
  });
  return [...groups.values()]
    .map((group) => {
      group.results.sort((left, right) => {
        const attention = Number(needsReview(right)) - Number(needsReview(left));
        return attention || (left.confidence ?? -1) - (right.confidence ?? -1);
      });
      return { ...group, pending: group.results.filter(needsReview).length };
    })
    .sort((left, right) => left.label.localeCompare(right.label, "zh-CN"));
}

function renderResults() {
  const hasRuns = state.runs.length > 0;
  elements.openZoteroImportButton.disabled = !hasRuns;
  elements.resultExportActions.classList.toggle("is-hidden", !hasRuns);
  elements.resultBrowser.classList.toggle("is-hidden", !hasRuns);
  elements.resultEmpty.classList.toggle("is-hidden", hasRuns);
  if (!hasRuns) return;

  const taxonomyGroups = new Map();
  state.runs.forEach((run) => {
    if (!taxonomyGroups.has(run.taxonomy_id)) taxonomyGroups.set(run.taxonomy_id, []);
    taxonomyGroups.get(run.taxonomy_id).push(run);
  });
  if (!taxonomyGroups.has(state.activeResultTaxonomyId)) {
    state.activeResultTaxonomyId = taxonomyGroups.keys().next().value;
    state.activeResultRunId = null;
    state.activeResultCategoryKey = null;
  }

  elements.resultTaxonomyFilter.replaceChildren();
  taxonomyGroups.forEach((runs, taxonomyId) => {
    const option = document.createElement("option");
    option.value = taxonomyId;
    option.textContent = `${runs[0].taxonomy_name} · 版本 ${runs[0].taxonomy_version} (${runs.length} 次运行)`;
    option.selected = taxonomyId === state.activeResultTaxonomyId;
    elements.resultTaxonomyFilter.append(option);
  });

  const runs = taxonomyGroups.get(state.activeResultTaxonomyId);
  if (!runs.some((run) => run.id === state.activeResultRunId)) {
    state.activeResultRunId = runs[0].id;
    state.activeResultCategoryKey = null;
  }
  elements.resultRunFilter.replaceChildren();
  runs.forEach((run) => {
    const option = document.createElement("option");
    option.value = run.id;
    option.textContent = `${formatDateTime(run.created_at)} · ${runStatusLabel(run.status)}`;
    option.selected = run.id === state.activeResultRunId;
    elements.resultRunFilter.append(option);
  });

  const run = runs.find((item) => item.id === state.activeResultRunId);
  const runQuery = `?run_id=${encodeURIComponent(run.id)}`;
  elements.exportResultsCsv.href = `/api/exports/results.csv${runQuery}`;
  elements.exportResultsJson.href = `/api/exports/results.json${runQuery}`;
  const groups = resultGroupsForRun(run.id);
  const pending = groups.reduce((total, group) => total + group.pending, 0);
  document.querySelector("#result-run-state").textContent = `${runStatusLabel(run.status)} · ${run.model_name}`;
  document.querySelector("#result-success-count").textContent = run.completed_documents;
  document.querySelector("#result-failure-count").textContent = run.failed_documents;
  document.querySelector("#result-review-count").textContent = pending;
  elements.deleteResultRunButton.disabled = ["queued", "running"].includes(run.status);
  elements.openZoteroImportButton.disabled = ["queued", "running"].includes(run.status);

  if (!groups.some((group) => group.key === state.activeResultCategoryKey)) {
    state.activeResultCategoryKey = groups.reduce(
      (best, group) => (!best || group.pending > best.pending ? group : best),
      null,
    )?.key || null;
  }

  elements.resultCategoryTabs.replaceChildren();
  groups.forEach((group) => {
    const button = document.createElement("button");
    button.className = "result-category-tab";
    button.type = "button";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", "result-table-host");
    button.setAttribute("aria-selected", String(group.key === state.activeResultCategoryKey));
    const label = document.createElement("strong");
    label.textContent = group.label;
    const meta = document.createElement("span");
    meta.textContent = `${group.results.length} 篇${group.pending ? ` · ${group.pending} 待处理` : ""}`;
    button.append(label, meta);
    button.addEventListener("click", () => {
      state.activeResultCategoryKey = group.key;
      elements.resultCategoryTabs.querySelectorAll("[role='tab']").forEach((tab) => {
        tab.setAttribute("aria-selected", String(tab === button));
      });
      elements.resultTableHost.replaceChildren(createResultTable(group.results));
    });
    elements.resultCategoryTabs.append(button);
  });

  elements.resultTableHost.replaceChildren();
  const activeGroup = groups.find((group) => group.key === state.activeResultCategoryKey);
  if (activeGroup) {
    elements.resultTableHost.append(createResultTable(activeGroup.results));
  } else {
    const empty = document.createElement("p");
    empty.className = "result-run-empty";
    empty.textContent = "此运行尚无分类结果";
    elements.resultTableHost.append(empty);
  }
}

async function loadResults() {
  [state.runs, state.results] = await Promise.all([
    api("/api/classifications/runs"),
    api("/api/classifications/results"),
  ]);
  renderResults();
}

function zoteroMatchLabel(status) {
  return {
    linked: "已关联 Zotero 条目",
    matched: "找到唯一匹配条目",
    ambiguous: "发现多个匹配条目，请选择",
    unmatched: "未找到相同条目，将新建",
  }[status] || status;
}

function updateZoteroImportReadiness() {
  const selects = [...elements.zoteroImportList.querySelectorAll("select")];
  const unresolved = selects.filter((select) => !select.value).length;
  const hasOutputMode = elements.zoteroWriteTags.checked || elements.zoteroWriteCollections.checked;
  elements.zoteroImportDialog.classList.toggle("hide-zotero-tags", !elements.zoteroWriteTags.checked);
  elements.zoteroImportDialog.classList.toggle("hide-zotero-collections", !elements.zoteroWriteCollections.checked);
  elements.confirmZoteroImportButton.disabled = !selects.length || unresolved > 0 || !hasOutputMode;
  if (state.zoteroPreview) {
    if (!hasOutputMode) {
      elements.zoteroImportSummary.textContent = "请至少选择导出标签或导出目录";
    } else {
      elements.zoteroImportSummary.textContent = unresolved
        ? `${state.zoteroPreview.items.length} 篇文献 · 还有 ${unresolved} 篇需要选择处理方式`
        : `${state.zoteroPreview.items.length} 篇文献已准备，可以确认导入`;
    }
  }
}

function renderZoteroPreview(preview) {
  state.zoteroPreview = preview;
  elements.zoteroImportList.replaceChildren();
  preview.items.forEach((item) => {
    const row = document.createElement("section");
    row.className = "zotero-import-row";
    row.dataset.resultId = item.result_id;

    const literature = document.createElement("div");
    literature.className = "zotero-import-literature";
    const title = document.createElement("strong");
    title.textContent = item.document_title || item.document_name;
    const filename = document.createElement("span");
    filename.textContent = item.document_name;
    const tag = document.createElement("code");
    tag.className = "zotero-preview-tag";
    tag.textContent = `标签：${item.proposed_tag}`;
    const collection = document.createElement("code");
    collection.className = "zotero-preview-collection";
    collection.textContent = `目录：${item.proposed_collection_path.join(" / ")}`;
    literature.append(title, filename, tag, collection);

    const choice = document.createElement("label");
    choice.className = "zotero-import-choice";
    const status = document.createElement("span");
    status.textContent = zoteroMatchLabel(item.match_status);
    const select = document.createElement("select");
    select.setAttribute("aria-label", `选择 ${title.textContent} 的 Zotero 导入方式`);
    if (!item.default_action) {
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "请选择处理方式";
      select.append(placeholder);
    }
    item.candidates.forEach((candidate) => {
      const option = document.createElement("option");
      option.value = `reuse:${candidate.item_key}`;
      option.dataset.action = "reuse";
      option.dataset.itemKey = candidate.item_key;
      option.dataset.itemVersion = candidate.version;
      option.textContent = `复用：${candidate.title}${candidate.date ? ` (${candidate.date})` : ""} · ${candidate.match_reason}`;
      option.selected = item.default_action === "reuse" && candidate.item_key === item.selected_item_key;
      select.append(option);
    });
    const createOption = document.createElement("option");
    createOption.value = "create";
    createOption.dataset.action = "create";
    createOption.textContent = "新建 Zotero 文献并导入 PDF";
    createOption.selected = item.default_action === "create";
    select.append(createOption);
    select.addEventListener("change", updateZoteroImportReadiness);
    choice.append(status, select);
    row.append(literature, choice);
    elements.zoteroImportList.append(row);
  });
  elements.zoteroImportStatus.textContent = `已连接 Zotero · 分类体系：${preview.taxonomy_name}`;
  elements.zoteroImportSummary.classList.remove("is-hidden");
  updateZoteroImportReadiness();
}

async function openZoteroImport() {
  const run = state.runs.find((item) => item.id === state.activeResultRunId);
  if (!run) {
    toast("请先选择一次分类运行", "warning");
    return;
  }
  state.zoteroPreview = null;
  elements.zoteroWriteTags.checked = true;
  elements.zoteroWriteCollections.checked = true;
  elements.zoteroImportList.replaceChildren();
  elements.zoteroImportSummary.classList.add("is-hidden");
  elements.zoteroImportStatus.textContent = "正在检测本地 Zotero";
  elements.confirmZoteroImportButton.disabled = true;
  elements.zoteroImportDialog.showModal();
  try {
    const status = await api("/api/zotero/status");
    elements.zoteroImportStatus.textContent = status.message;
    if (!status.writable) return;
    const preview = await api("/api/zotero/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: run.id }),
    });
    renderZoteroPreview(preview);
  } catch (error) {
    elements.zoteroImportStatus.textContent = error.message;
    toast(error.message, "error");
  }
}

async function submitZoteroImport(event) {
  event.preventDefault();
  if (!state.zoteroPreview) return;
  const writeTags = elements.zoteroWriteTags.checked;
  const writeCollections = elements.zoteroWriteCollections.checked;
  if (!writeTags && !writeCollections) {
    toast("请至少选择导出标签或导出目录", "warning");
    return;
  }
  const selections = [...elements.zoteroImportList.querySelectorAll(".zotero-import-row")].map((row) => {
    const option = row.querySelector("select").selectedOptions[0];
    return {
      result_id: row.dataset.resultId,
      action: option.dataset.action,
      item_key: option.dataset.itemKey || null,
      item_version: option.dataset.itemVersion ? Number(option.dataset.itemVersion) : null,
    };
  });
  if (selections.some((selection) => !selection.action)) {
    toast("请先处理所有匹配冲突", "warning");
    return;
  }
  const createCount = selections.filter((selection) => selection.action === "create").length;
  const outputNames = [writeTags && "分类标签", writeCollections && "分类目录"].filter(Boolean);
  const confirmed = window.confirm(
    `确定将这 ${selections.length} 篇文献导入 Zotero，并写入${outputNames.join("和")}吗？\n\n其中 ${createCount} 篇会新建文献条目，其余将复用已有条目。`,
  );
  if (!confirmed) return;
  elements.confirmZoteroImportButton.disabled = true;
  elements.zoteroImportStatus.textContent = "正在等待 Zotero 写入授权并导入文献，请留意 Zotero 窗口";
  try {
    const response = await api("/api/zotero/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: state.zoteroPreview.run_id,
        server_id: state.zoteroPreview.server_id,
        write_tags: writeTags,
        write_collections: writeCollections,
        selections,
      }),
    });
    elements.zoteroImportStatus.textContent = response.failed_count
      ? `导入结束：新建 ${response.created_count}，更新 ${response.updated_count}，失败 ${response.failed_count}`
      : `导入完成：新建 ${response.created_count}，更新 ${response.updated_count}，目录归档 ${response.collection_count}，PDF 附件 ${response.attachment_count}`;
    elements.zoteroImportSummary.textContent = response.errors.length
      ? response.errors.join("；")
      : `另有 ${response.unchanged_count} 篇无需修改。`;
    response.items.forEach((item) => {
      const row = elements.zoteroImportList.querySelector(`[data-result-id="${item.result_id}"]`);
      if (!row) return;
      row.classList.toggle("is-success", item.status === "success");
      row.classList.toggle("is-error", item.status === "failed");
      row.querySelector(".zotero-import-choice > span").textContent = item.message;
      row.querySelector("select").disabled = true;
    });
    toast(response.failed_count ? "Zotero 导入完成，部分文献需要处理" : "文献分类结果已导入 Zotero", response.failed_count ? "error" : "success");
  } catch (error) {
    elements.zoteroImportStatus.textContent = error.message;
    toast(error.message, "error");
    elements.confirmZoteroImportButton.disabled = false;
  }
}

async function deleteResult(result, button) {
  const title = result.document_title || result.document_name;
  const confirmed = window.confirm(`确定删除“${title}”的这条分类结果吗？\n\n此操作无法恢复。`);
  if (!confirmed) return;
  button.disabled = true;
  try {
    await api(`/api/classifications/results/${result.id}`, { method: "DELETE" });
    await loadResults();
    toast("分类结果已删除");
  } catch (error) {
    button.disabled = false;
    toast(error.message, "error");
  }
}

async function deleteResultRun() {
  const run = state.runs.find((item) => item.id === state.activeResultRunId);
  if (!run) return;
  const resultCount = state.results.filter((result) => result.run_id === run.id).length;
  const confirmed = window.confirm(
    `确定删除 ${formatDateTime(run.created_at)} 的整批分类结果吗？\n\n共 ${resultCount} 篇文献结果，删除后无法恢复。分类体系会保留。`,
  );
  if (!confirmed) return;
  elements.deleteResultRunButton.disabled = true;
  try {
    await api(`/api/classifications/runs/${run.id}`, { method: "DELETE" });
    state.activeResultRunId = null;
    state.activeResultCategoryKey = null;
    await loadResults();
    toast("本次分类结果已删除");
  } catch (error) {
    elements.deleteResultRunButton.disabled = false;
    toast(error.message, "error");
  }
}

function openResult(result) {
  state.activeResult = result;
  document.querySelector("#detail-title").textContent = result.document_title || result.document_name;
  document.querySelector("#detail-file").textContent = result.document_name;
  document.querySelector("#detail-category").textContent = result.category_name || result.category_code || "分类失败";
  document.querySelector("#detail-confidence").textContent = formatPercent(result.confidence);
  document.querySelector("#detail-gap").textContent = formatPercent(result.top_gap);

  const probabilityList = document.querySelector("#probability-list");
  probabilityList.replaceChildren();
  const entries = Object.entries(result.probabilities).sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    const error = document.createElement("div");
    error.className = "inline-notice";
    error.textContent = result.error_message || "没有可显示的概率数据";
    probabilityList.append(error);
  }
  entries.forEach(([code, probability]) => {
    const row = document.createElement("div");
    row.className = "probability-row";
    const label = document.createElement("span");
    label.className = "probability-label";
    label.textContent = result.probability_labels[code] || code;
    const line = document.createElement("span");
    line.className = "probability-line";
    const fill = document.createElement("span");
    fill.className = "probability-fill";
    fill.style.width = `${Math.max(0, Math.min(100, probability * 100))}%`;
    line.append(fill);
    const value = document.createElement("span");
    value.className = "probability-value";
    value.textContent = formatPercent(probability);
    row.append(label, line, value);
    probabilityList.append(row);
  });

  const select = document.querySelector("#review-category-select");
  select.replaceChildren();
  Object.entries(result.probability_labels).forEach(([code, label]) => {
    const option = document.createElement("option");
    option.value = code;
    option.textContent = label;
    option.selected = code === (result.reviewed_category_code || result.category_code);
    select.append(option);
  });
  document.querySelector("#review-note").value = result.review_note || "";
  document.querySelector("#detail-metadata").textContent = [
    `模型 ${result.model_version || "未知"}`,
    `输入层级 ${result.input_level}`,
    `复核状态 ${statusLabel(result.review_status)}`,
  ].join(" | ");
  elements.resultDialog.showModal();
}

async function submitReview(action) {
  if (!state.activeResult) return;
  try {
    const payload = {
      action,
      category_code: action === "correct" ? document.querySelector("#review-category-select").value : null,
      note: document.querySelector("#review-note").value.trim(),
    };
    const updated = await api(`/api/classifications/results/${state.activeResult.id}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const index = state.results.findIndex((item) => item.id === updated.id);
    if (index >= 0) state.results[index] = updated;
    state.activeResult = updated;
    renderResults();
    elements.resultDialog.close();
    toast("复核结果已保存");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function pollRun(runId) {
  const job = document.querySelector("#job-status");
  job.classList.remove("is-hidden");
  for (;;) {
    const run = await api(`/api/classifications/runs/${runId}`);
    const processed = run.completed_documents + run.failed_documents;
    document.querySelector("#job-status-count").textContent = `${processed} / ${run.total_documents}`;
    document.querySelector("#job-status-detail").textContent = `成功 ${run.completed_documents}，失败 ${run.failed_documents}`;
    if (["completed", "completed_with_errors", "failed"].includes(run.status)) {
      document.querySelector("#job-status-title").textContent =
        run.status === "completed" ? "分类任务已完成" : "分类任务已结束，请检查结果";
      await loadResults();
      if (run.status === "completed") {
        toast(`分类完成，共处理 ${run.completed_documents} 篇文献`);
      } else if (run.status === "completed_with_errors") {
        toast(
          `分类结束：成功 ${run.completed_documents} 篇，失败 ${run.failed_documents} 篇`,
          "warning",
        );
      } else {
        toast(run.error_message || "分类任务失败，请检查模型配置和服务状态", "error");
      }
      return;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 900));
  }
}

async function checkHealth() {
  try {
    const health = await api("/api/health");
    showJevStatus(health.jev_connection_status, health.model);
    setGenerationAvailability(health.generation_configured);
  } catch (error) {
    elements.health.textContent = "服务状态不可用";
    elements.health.className = "header-status is-error";
    setGenerationAvailability(false);
    toast(error.message, "error");
  }
}

function showJevStatus(status, model) {
  const states = {
    unconfigured: ["Jev 未配置", "is-warning"],
    unverified: [`Jev 已填写，尚未验证 · ${model}`, "is-warning"],
    available: [`Jev 连接正常 · ${model}`, "is-ready"],
    authentication_failed: ["Jev 认证失败", "is-error"],
    model_unavailable: [`Jev 模型不可用 · ${model}`, "is-error"],
    connection_failed: ["Jev 连接异常", "is-error"],
    service_error: ["Jev 服务异常", "is-error"],
  };
  const [label, className] = states[status] || states.service_error;
  state.jevConnectionStatus = status;
  elements.health.textContent = label;
  elements.health.className = `header-status ${className}`;
}

function setGenerationAvailability(configured) {
  state.generationConfigured = configured;
  elements.generationModeButton.disabled = !configured;
  elements.generationModeButton.title = configured
    ? "使用通用大模型生成候选分类方案"
    : "请先在模型设置中配置通用大模型";
  elements.generationUnavailableNotice.classList.toggle("is-hidden", configured);
  if (!configured && !document.querySelector("#generate-taxonomy-form").classList.contains("is-hidden")) {
    switchTaxonomyMode("manual");
  }
}

function showProviderState(selector, configured, configuredLabel = "密钥已填写") {
  const target = document.querySelector(selector);
  target.textContent = configured ? configuredLabel : "尚未配置密钥";
  target.className = `provider-state ${configured ? "is-configured" : "is-missing"}`;
}

function showJevProviderState(status) {
  const states = {
    unconfigured: ["尚未配置密钥", "is-missing"],
    unverified: ["密钥已填写，尚未验证", "is-pending"],
    available: ["连接正常", "is-configured"],
    authentication_failed: ["认证失败", "is-error"],
    model_unavailable: ["所选模型不可用", "is-error"],
    connection_failed: ["连接异常", "is-error"],
    service_error: ["服务异常", "is-error"],
  };
  const [label, className] = states[status] || states.service_error;
  const target = document.querySelector("#typesafe-key-state");
  target.textContent = label;
  target.className = `provider-state ${className}`;
}

function applyModelSettings(settings) {
  const typesafeKey = document.querySelector("#typesafe-api-key-input");
  const generationKey = document.querySelector("#generation-api-key-input");
  typesafeKey.value = "";
  typesafeKey.placeholder = settings.typesafe_api_key_configured ? "留空则保留当前密钥" : "请输入 TypeSafe API Key";
  document.querySelector("#typesafe-model-input").value = settings.typesafe_model;
  generationKey.value = "";
  generationKey.placeholder = settings.generation_api_key_configured ? "留空则保留当前密钥" : "请输入生成模型 API Key";
  document.querySelector("#generation-base-url-input").value = settings.generation_base_url;
  document.querySelector("#generation-model-input").value = settings.generation_model;
  const jevStatus = settings.jev_connection_status === "unverified"
    ? (state.jevConnectionStatus || "unverified")
    : settings.jev_connection_status;
  showJevProviderState(jevStatus);
  showProviderState("#generation-key-state", settings.generation_api_key_configured);
}

async function openModelSettings() {
  elements.modelSettingsDialog.showModal();
  try {
    applyModelSettings(await api("/api/settings/models"));
  } catch (error) {
    elements.modelSettingsDialog.close();
    toast(error.message, "error");
  }
}

function closeModelSettings() {
  document.querySelector("#typesafe-api-key-input").value = "";
  document.querySelector("#generation-api-key-input").value = "";
  elements.modelSettingsDialog.close();
}

async function saveModelSettings(event) {
  event.preventDefault();
  const submit = event.submitter;
  submit.disabled = true;
  submit.textContent = "正在保存并验证";
  try {
    const settings = await api("/api/settings/models", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        typesafe_api_key: document.querySelector("#typesafe-api-key-input").value,
        typesafe_model: document.querySelector("#typesafe-model-input").value,
        generation_api_key: document.querySelector("#generation-api-key-input").value,
        generation_base_url: document.querySelector("#generation-base-url-input").value,
        generation_model: document.querySelector("#generation-model-input").value,
      }),
    });
    showJevStatus(settings.jev_connection_status, settings.typesafe_model);
    applyModelSettings(settings);
    setGenerationAvailability(
      settings.generation_api_key_configured && Boolean(settings.generation_model),
    );
    elements.modelSettingsDialog.close();
    const validationMessages = {
      unconfigured: ["模型配置已保存；Jev 尚未配置", "info"],
      available: ["模型配置已保存，Jev 连接正常", "success"],
      authentication_failed: ["模型配置已保存，但 Jev API Key 认证失败", "error"],
      model_unavailable: ["模型配置已保存，但当前 Jev 模型不可用", "error"],
      connection_failed: ["模型配置已保存，但暂时无法连接 Jev 服务", "error"],
      service_error: ["模型配置已保存，但 Jev 服务验证失败", "error"],
    };
    const [message, type] = validationMessages[settings.jev_connection_status]
      || ["模型配置已保存，Jev 状态尚未验证", "warning"];
    toast(message, type);
  } catch (error) {
    toast(error.message, "error");
  } finally {
    submit.disabled = false;
    submit.textContent = "保存配置";
  }
}

function bindEvents() {
  document.querySelector("#open-model-settings-button").addEventListener("click", openModelSettings);
  elements.modelSettingsForm.addEventListener("submit", saveModelSettings);
  ["#close-model-settings-button", "#cancel-model-settings-button"].forEach((selector) => {
    document.querySelector(selector).addEventListener("click", closeModelSettings);
  });
  elements.modelSettingsDialog.addEventListener("click", (event) => {
    if (event.target === elements.modelSettingsDialog) closeModelSettings();
  });
  elements.modelSettingsDialog.addEventListener("close", () => {
    document.querySelector("#typesafe-api-key-input").value = "";
    document.querySelector("#generation-api-key-input").value = "";
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  elements.resultTaxonomyFilter.addEventListener("change", () => {
    state.activeResultTaxonomyId = elements.resultTaxonomyFilter.value;
    state.activeResultRunId = null;
    state.activeResultCategoryKey = null;
    renderResults();
  });
  elements.resultRunFilter.addEventListener("change", () => {
    state.activeResultRunId = elements.resultRunFilter.value;
    state.activeResultCategoryKey = null;
    renderResults();
  });
  elements.deleteResultRunButton.addEventListener("click", deleteResultRun);
  elements.openZoteroImportButton.addEventListener("click", openZoteroImport);
  elements.exportResultsCsv.addEventListener("click", (event) => downloadResultExport(event, "csv"));
  elements.exportResultsJson.addEventListener("click", (event) => downloadResultExport(event, "json"));
  elements.zoteroImportForm.addEventListener("submit", submitZoteroImport);
  elements.zoteroWriteTags.addEventListener("change", updateZoteroImportReadiness);
  elements.zoteroWriteCollections.addEventListener("change", updateZoteroImportReadiness);
  ["#close-zotero-import-button", "#cancel-zotero-import-button"].forEach((selector) => {
    document.querySelector(selector).addEventListener("click", () => elements.zoteroImportDialog.close());
  });
  elements.zoteroImportDialog.addEventListener("click", (event) => {
    if (event.target === elements.zoteroImportDialog) elements.zoteroImportDialog.close();
  });
  document.querySelector("#upload-button").addEventListener("click", () => elements.fileInput.click());
  elements.fileInput.addEventListener("change", () => uploadFiles(elements.fileInput.files));
  ["dragenter", "dragover"].forEach((name) => {
    elements.uploadForm.addEventListener(name, (event) => {
      event.preventDefault();
      elements.uploadForm.classList.add("is-dragging");
    });
  });
  ["dragleave", "drop"].forEach((name) => {
    elements.uploadForm.addEventListener(name, (event) => {
      event.preventDefault();
      elements.uploadForm.classList.remove("is-dragging");
    });
  });
  elements.uploadForm.addEventListener("drop", (event) => uploadFiles(event.dataTransfer.files));

  document.querySelector("#select-all-button").addEventListener("click", () => {
    const readyIds = state.documents
      .filter((item) => item.parse_status === "ready" && item.metadata_status === "confirmed")
      .map((item) => item.id);
    const allSelected = readyIds.length && readyIds.every((id) => state.selectedDocumentIds.has(id));
    state.selectedDocumentIds = new Set(allSelected ? [] : readyIds);
    renderDocuments();
  });

  document.querySelector("#document-metadata-form").addEventListener("submit", saveDocumentMetadata);
  ["#close-document-dialog-button", "#cancel-document-edit-button"].forEach((selector) => {
    document.querySelector(selector).addEventListener("click", () => elements.documentDialog.close());
  });
  elements.documentDialog.addEventListener("click", (event) => {
    if (event.target === elements.documentDialog) elements.documentDialog.close();
  });

  document.querySelectorAll("[data-taxonomy-mode]").forEach((button) => {
    button.addEventListener("click", () => switchTaxonomyMode(button.dataset.taxonomyMode));
  });
  document.querySelector("#add-category-button").addEventListener("click", () => addCategoryRow());
  document.querySelector("#cancel-taxonomy-edit-button").addEventListener("click", resetTaxonomyEditor);

  document.querySelector("#manual-taxonomy-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = event.submitter;
    const editingTaxonomyId = state.editingTaxonomyId;
    submit.disabled = true;
    try {
      await api(
        editingTaxonomyId
          ? `/api/taxonomies/${editingTaxonomyId}/versions`
          : "/api/taxonomies",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: document.querySelector("#taxonomy-name").value.trim(),
            objective: document.querySelector("#taxonomy-objective").value.trim(),
            mode: state.taxonomyOrigin,
            categories: collectCategories(),
          }),
        },
      );
      toast(editingTaxonomyId ? "新版本已保存，原版本已转入历史" : "分类体系已保存");
      resetTaxonomyEditor();
      await loadTaxonomies();
      setView(editingTaxonomyId ? "taxonomy" : "results");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      submit.disabled = false;
    }
  });

  document.querySelector("#generate-taxonomy-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.generationConfigured) {
      toast("请先配置通用大模型，或改用自定义分类体系分类体系", "warning");
      return;
    }
    if (state.selectedDocumentIds.size < 2) {
      toast("生成方案前至少选择两篇可用文献", "warning");
      return;
    }
    const submit = event.submitter;
    submit.disabled = true;
    submit.textContent = "正在生成";
    state.generatedSchemes = [];
    renderSchemes();
    document.querySelector("#objective-interpretation").classList.add("is-hidden");
    try {
      const response = await api("/api/schemes/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_ids: [...state.selectedDocumentIds],
          objective: document.querySelector("#generation-objective").value.trim(),
          category_count: Number(document.querySelector("#generation-category-count").value),
          scheme_count: Number(document.querySelector("#generation-scheme-count").value),
        }),
      });
      state.generatedSchemes = response.schemes;
      document.querySelector("#objective-interpretation-text").textContent =
        response.objective_interpretation;
      document.querySelector("#objective-interpretation").classList.remove("is-hidden");
      renderSchemes();
      toast(`已生成 ${response.schemes.length} 套候选分类方案`);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      submit.disabled = false;
      submit.textContent = "生成分类方案";
    }
  });

  document.querySelector("#run-classification-button").addEventListener("click", async () => {
    const taxonomyId = elements.taxonomySelect.value;
    if (!taxonomyId || !state.selectedDocumentIds.size) {
      toast("请选择分类体系和至少一篇文献", "warning");
      return;
    }
    const button = document.querySelector("#run-classification-button");
    button.disabled = true;
    try {
      const run = await api("/api/classifications/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ taxonomy_id: taxonomyId, document_ids: [...state.selectedDocumentIds] }),
      });
      await pollRun(run.id);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  document.querySelector("#close-dialog-button").addEventListener("click", () => elements.resultDialog.close());
  elements.resultDialog.addEventListener("click", (event) => {
    if (event.target === elements.resultDialog) elements.resultDialog.close();
  });
  document.querySelectorAll("[data-review-action]").forEach((button) => {
    button.addEventListener("click", () => submitReview(button.dataset.reviewAction));
  });
}

async function init() {
  bindEvents();
  resetTaxonomyEditor();
  try {
    await Promise.all([checkHealth(), loadDocuments(), loadTaxonomies(), loadResults()]);
  } catch (error) {
    toast(error.message, "error");
  }
}

init();
