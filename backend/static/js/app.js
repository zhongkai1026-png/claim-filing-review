/* 破产管理人债权申报与审查系统 - 前端逻辑 */
"use strict";

// ---------- API ----------
const api = {
  async req(url, opts = {}) {
    const res = await fetch(url, opts);
    if (!res.ok) {
      let msg = `请求失败 (${res.status})`;
      try { const j = await res.json(); msg = j.detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    const ct = res.headers.get("content-type") || "";
    return ct.includes("application/json") ? res.json() : res;
  },
  get: (u) => api.req(u),
  post: (u, body) => api.req(u, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  put: (u, body) => api.req(u, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  del: (u) => api.req(u, { method: "DELETE" }),
  upload: (u, files) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return api.req(u, { method: "POST", body: fd });
  },
};

// ---------- 工具 ----------
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
// 金额显示：统一千分位（2000000 → 2,000,000；有小数时保留 2 位）
function fmtMoney(v) {
  const n = Number(v || 0);
  if (!isFinite(n)) return "0";
  const isInt = Math.abs(n - Math.round(n)) < 0.005;
  return n.toLocaleString("zh-CN", isInt
    ? { minimumFractionDigits: 0, maximumFractionDigits: 0 }
    : { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
// 统计卡用：大金额自动缩写为 万/亿，避免超出显示框；悬浮显示精确值
function fmtMoneySmart(v, withSymbol = true) {
  const n = Number(v || 0);
  const abs = Math.abs(n);
  const sym = withSymbol ? "¥" : "";
  if (abs >= 1e8) return sym + trimZero(n / 1e8) + "亿";
  if (abs >= 1e4) return sym + trimZero(n / 1e4) + "万";
  return sym + fmtMoney(n);
}
function trimZero(s) {
  s = s.toFixed(2);
  return s.replace(/\.?0+$/, "");
}
// 万元显示：金额(元) → X.XX 万元
function fmtWan(v, digits = 2) {
  const n = Number(v || 0) / 10000;
  return n.toLocaleString("zh-CN", { minimumFractionDigits: 0,
    maximumFractionDigits: digits });
}
function statNum(v, label) {
  // 统计卡数字：智能缩写 + 悬浮显示完整值
  const n = Number(v || 0);
  const text = Math.abs(n) >= 1e4 ? fmtMoneySmart(n) : fmtMoney(n);
  return `<div class="num" title="${esc(fmtMoney(n))}">${text}</div><div class="label">${esc(label)}</div>`;
}
function statusBadge(s) {
  const m = { pending: ["badge-pending", "待登记"], registered: ["badge-registered", "已登记"], reviewed: ["badge-reviewed", "已复核"] };
  const [cls, txt] = m[s] || ["badge-none", s || "—"];
  return `<span class="badge ${cls}">${txt}</span>`;
}
function aiBadge(s) {
  const m = { none: ["badge-none", "未审查"], running: ["badge-running", "审查中…"], done: ["badge-done", "已审查"], failed: ["badge-failed", "失败"] };
  const [cls, txt] = m[s] || ["badge-none", s];
  return `<span class="badge ${cls}">${txt}</span>`;
}
// 提示条：每条独立计时移除（不可用共享 timer，否则前一条会被 cancel 而永久残留）
function toast(msg, isError = false) {
  let root = document.getElementById("toastRoot");
  if (!root) {
    root = document.createElement("div");
    root.id = "toastRoot";
    document.body.appendChild(root);
  }
  const t = document.createElement("div");
  t.className = "toast" + (isError ? " error" : "");
  t.textContent = msg;
  t.title = "点击关闭";
  t.onclick = () => { try { t.remove(); } catch (e) {} };
  root.appendChild(t);
  setTimeout(() => { try { t.remove(); } catch (e) {} }, 3500);
  // 同屏最多保留 4 条，超出自动清理最早的
  while (root.children.length > 4) {
    try { root.removeChild(root.firstChild); } catch (e) { break; }
  }
}

// ---------- AI 模型配置（系统内添加/切换多个模型） ----------
function updateAIBadge(health) {
  const badge = $("#aiBadge");
  if (!badge) return;
  if (health && health.ai_enabled) {
    badge.textContent = `AI：${health.ai_config || ""} / ${health.ai_model || ""}`.trim();
    badge.classList.add("on");
  } else {
    badge.textContent = "AI 未配置（规则引擎）";
    badge.classList.remove("on");
  }
}

async function openAISettings() {
  let configs = [];
  try { configs = await api.get("/api/ai-configs"); } catch (e) { toast(e.message, true); }
  const active = configs.find((c) => c.is_active);
  const listHtml = configs.length ? configs.map((c) => `
    <tr>
      <td>${esc(c.name)} ${c.is_active ? '<span class="badge badge-done">当前</span>' : ""}</td>
      <td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.base_url)}</td>
      <td>${esc(c.model)}</td>
      <td>${c.api_key ? "已填写" : '<span style="color:var(--red)">缺失</span>'}</td>
      <td style="white-space:nowrap">
        ${c.is_active ? "" : `<button class="btn btn-sm" onclick="activateAIConfig(${c.id})">切换</button>`}
        <button class="btn btn-sm" onclick="editAIConfig(${c.id})">编辑</button>
        <button class="btn btn-sm btn-danger" onclick="deleteAIConfig(${c.id})">删除</button>
      </td>
    </tr>`).join("")
    : `<tr><td colspan="5" class="empty">暂无模型配置，请在下方添加（支持任何 OpenAI 兼容接口：DeepSeek / 通义千问 / 智谱 / OpenAI 等）</td></tr>`;

  openModal(`${modalHead("AI 模型配置")}
    <div class="modal-body">
      <div class="audit-section" style="margin-bottom:12px">
        <h4 style="margin-bottom:8px">🤖 当前模型：${active ? esc(active.name) + " / " + esc(active.model) : '<span style="color:var(--amber)">未激活（AI 审查将使用规则引擎）</span>'}</h4>
        <div style="color:var(--text-2);font-size:12px">切换模型后，下一次 AI 审查立即使用新模型；历史审查结果不受影响。</div>
      </div>
      <table class="tbl">
        <thead><tr><th>名称</th><th>接口地址</th><th>模型名</th><th>Key</th><th>操作</th></tr></thead>
        <tbody>${listHtml}</tbody>
      </table>
      <div class="audit-section" style="margin-top:14px">
        <h4 style="margin-bottom:10px">＋ 添加 / 编辑模型配置</h4>
        <div class="grid-2">
          <div class="field"><label>配置名称 *</label><input id="ac_name" placeholder="如：DeepSeek / 通义千问"></div>
          <div class="field"><label>模型名 *</label><input id="ac_model" placeholder="如：deepseek-chat / qwen-max"></div>
          <div class="field" style="grid-column:1/-1"><label>接口地址（OpenAI 兼容 Base URL）*</label><input id="ac_base" placeholder="如：https://api.deepseek.com/v1"></div>
          <div class="field" style="grid-column:1/-1"><label>API Key *</label><input id="ac_key" type="password" placeholder="sk-…" autocomplete="off"></div>
        </div>
        <label style="display:flex;align-items:center;gap:6px;font-size:13px;cursor:pointer">
          <input type="checkbox" id="ac_active" checked> 保存后立即切换为该模型
        </label>
      </div>
    </div>
    <div class="modal-foot">
      <button class="btn" onclick="testAIConfig()">🔌 测试连接</button>
      <button class="btn" onclick="closeModal()">关闭</button>
      <button class="btn btn-primary" onclick="saveAIConfig()">保存配置</button>
    </div>`, { wide: true });
  window.__acEditId = null;
  window.__aiConfigs = configs;
}

async function saveAIConfig() {
  const body = {
    name: $("#ac_name").value.trim(),
    base_url: $("#ac_base").value.trim(),
    api_key: $("#ac_key").value.trim(),
    model: $("#ac_model").value.trim(),
    activate: $("#ac_active").checked,
  };
  if (!body.name) return toast("请填写配置名称", true);
  if (!body.base_url) return toast("请填写接口地址", true);
  if (!body.model) return toast("请填写模型名", true);
  if (!body.api_key) return toast("请填写 API Key", true);
  try {
    const id = window.__acEditId;
    if (id) await api.put(`/api/ai-configs/${id}`, body);
    else await api.post("/api/ai-configs", body);
    toast(id ? "配置已更新" : "配置已保存");
    const health = await api.get("/api/health");
    updateAIBadge(health);
    openAISettings();
  } catch (e) { toast(e.message, true); }
}

async function editAIConfig(id) {
  const c = (window.__aiConfigs || []).find((x) => x.id === id);
  if (!c) return;
  window.__acEditId = id;
  $("#ac_name").value = c.name;
  $("#ac_base").value = c.base_url;
  $("#ac_key").value = c.api_key;
  $("#ac_model").value = c.model;
  $("#ac_active").checked = !c.is_active;
}

async function activateAIConfig(id) {
  try {
    await api.post(`/api/ai-configs/${id}/activate`);
    toast("已切换模型");
    const health = await api.get("/api/health");
    updateAIBadge(health);
    openAISettings();
  } catch (e) { toast(e.message, true); }
}

async function deleteAIConfig(id) {
  if (!confirm("确认删除该模型配置？")) return;
  try {
    await api.del(`/api/ai-configs/${id}`);
    toast("已删除");
    const health = await api.get("/api/health");
    updateAIBadge(health);
    openAISettings();
  } catch (e) { toast(e.message, true); }
}

async function testAIConfig() {
  const body = {
    name: $("#ac_name").value.trim() || "test",
    base_url: $("#ac_base").value.trim(),
    api_key: $("#ac_key").value.trim(),
    model: $("#ac_model").value.trim(),
  };
  if (!body.base_url) return toast("请先填写接口地址", true);
  if (!body.api_key) return toast("请先填写 API Key", true);
  if (!body.model) return toast("请先填写模型名", true);
  try {
    const r = await api.post("/api/ai-configs/test", body);
    if (r.ok) toast(`✅ ${r.message}`);
    else toast(`❌ ${r.message}`, true);
  } catch (e) { toast(e.message, true); }
}

// ---------- 当前项目（session 记忆，刷新后仍保留） ----------
function getCurrentProject() {
  try { return JSON.parse(sessionStorage.getItem("currentProject") || "null"); }
  catch (e) { return null; }
}
function setCurrentProject(p) {
  sessionStorage.setItem("currentProject", JSON.stringify({ id: p.id, name: p.name }));
}
function clearCurrentProject() { sessionStorage.removeItem("currentProject"); }

async function renderProjectSwitcher(currentId) {
  const el = $("#projectSwitcher");
  if (!el) return;
  const projects = await api.get("/api/projects").catch(() => []);
  const cur = getCurrentProject();
  const options = projects.map((p) =>
    `<option value="${p.id}" ${p.id === currentId ? "selected" : ""}>${esc(p.name)}</option>`).join("");
  el.innerHTML = projects.length
    ? `<select onchange="switchProject(this.value)" title="当前项目">
         <option value="">— 选择项目 —</option>${options}</select>`
    : "";
}
function switchProject(id) {
  if (!id) return;
  api.get(`/api/projects/${id}`).then((p) => {
    setCurrentProject(p);
    location.hash = `#/ledger?project=${p.id}`;
  }).catch(() => toast("项目不存在", true));
}

// 项目选择视图（无当前项目时展示，可直接点选进入）
function renderProjectPicker(app, title, sub) {
  app.innerHTML = `
    <div class="page-head">
      <div><div class="page-title">${esc(title)}</div>
      <div class="page-sub">${esc(sub || "请先选择一个项目，之后的操作将默认在该项目下进行")}</div></div>
      <a class="btn" href="#/projects">＋ 新建项目</a>
    </div>
    <div class="project-grid" id="pickGrid"></div>`;
  api.get("/api/projects").then(async (projects) => {
    const grid = $("#pickGrid");
    if (!projects.length) {
      grid.innerHTML = `<div class="empty" style="grid-column:1/-1"><div class="icon">📂</div>
        <p>暂无项目，<a class="link" href="#/projects">前往项目管理新建</a></p></div>`;
      return;
    }
    const stats = await Promise.all(projects.map((p) =>
      api.get(`/api/projects/${p.id}/stats`).catch(() => null)));
    grid.innerHTML = projects.map((p, i) => {
      const s = stats[i] || {};
      return `<div class="project-card" onclick="enterProject(${p.id})">
        <div class="p-name">${esc(p.name)}</div>
        <div class="p-meta">
          ${p.case_no ? `案号：${esc(p.case_no)}<br>` : ""}
          ${p.debtor ? `债务人：${esc(p.debtor)}<br>` : ""}
          债权 ${s.total || 0} 笔　申报 ${fmtMoneySmart(s.sum_claimed)}<br>
          <span style="color:var(--primary)">点击进入该项目 →</span>
        </div></div>`;
    }).join("");
  }).catch((e) => { $("#pickGrid").innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`; });
}
function enterProject(id) {
  api.get(`/api/projects/${id}`).then((p) => {
    setCurrentProject(p);
    location.hash = `#/ledger?project=${p.id}`;
  }).catch(() => toast("项目不存在", true));
}

function openModal(html, { wide = false } = {}) {
  const root = $("#modalRoot");
  root.innerHTML = `<div class="modal-mask" onclick="if(event.target===this)closeModal()">
    <div class="modal" style="${wide ? "max-width:1100px" : ""}">${html}</div></div>`;
}
function closeModal() { $("#modalRoot").innerHTML = ""; }
function modalHead(title) {
  return `<div class="modal-head"><h3>${esc(title)}</h3>
    <button class="modal-close" onclick="closeModal()">×</button></div>`;
}

// ---------- 路由 ----------
const routes = {
  "#/projects": renderProjects, "#/ledger": renderLedger,
  "#/audit": renderAudit, "#/dashboard": renderDashboard,
  "#/detail": renderDetail,
};
function parseHash() {
  const [path, query] = (location.hash || "#/projects").slice(1).split("?");
  const params = {};
  (query || "").split("&").forEach((kv) => {
    const [k, v] = kv.split("=");
    if (k) params[decodeURIComponent(k)] = decodeURIComponent(v || "");
  });
  return { path: path || "/projects", params };
}
async function router() {
  const { path, params } = parseHash();
  const nav = $("#topnav");
  const items = [
    ["#/projects", "项目管理"], ["#/ledger", "债权台账"],
    ["#/audit", "审查工作台"], ["#/dashboard", "📊 数据后台"],
  ];
  nav.innerHTML = items.map(([h, t]) => {
    const active = (path.startsWith("/ledger") && h === "#/ledger") ||
                   (path.startsWith("/audit") && h === "#/audit") ||
                   (path.startsWith("/dashboard") && h === "#/dashboard") ||
                   (path === "/projects" && h === "#/projects");
    return `<a href="${h}" class="${active ? "active" : ""}">${t}</a>`;
  }).join("");

  // 项目切换器（当前项目记忆）
  const currentId = params.project ? Number(params.project)
    : (getCurrentProject() || {}).id || null;
  renderProjectSwitcher(currentId);
  // AI 徽标：每次路由切换都刷新（避免非项目管理页显示"AI 未配置"）
  api.get("/api/health").then(updateAIBadge).catch(() => {});

  // 台账页内的「审查」Tab 复用审查工作台视图（同页双 Tab，URL 可回溯）
  const view = (path === "/ledger" && params.tab === "audit")
    ? renderAudit
    : (routes["#" + path] || renderProjects);
  const app = $("#app");
  // 离开数据后台时销毁图表实例（防止重复初始化）
  if (!path.startsWith("/dashboard")) destroyDashCharts();
  app.innerHTML = `<div class="empty"><div class="icon">⏳</div>加载中…</div>`;
  try { await view(params, app); } catch (e) {
    app.innerHTML = `<div class="empty"><div class="icon">⚠️</div><p>${esc(e.message)}</p></div>`;
  }
}
window.addEventListener("hashchange", router);

// ---------- 视图：项目管理 ----------
async function renderProjects(params, app) {
  const [projects, health] = await Promise.all([api.get("/api/projects"), api.get("/api/health")]);
  updateAIBadge(health);

  app.innerHTML = `
    <div class="page-head">
      <div><div class="page-title">项目管理</div>
      <div class="page-sub">每个破产案件创建一个项目，债权申报数据按项目独立管理</div></div>
      <button class="btn btn-primary" onclick="openNewProject()">＋ 新建项目</button>
    </div>
    <div class="project-grid" id="projectGrid"></div>`;
  const grid = $("#projectGrid");
  if (!projects.length) {
    grid.innerHTML = `<div class="empty" style="grid-column:1/-1"><div class="icon">📂</div>
      <p>暂无项目，点击右上角「新建项目」开始</p></div>`;
    return;
  }
  // 统计
  const stats = await Promise.all(projects.map((p) => api.get(`/api/projects/${p.id}/stats`).catch(() => null)));
  grid.innerHTML = projects.map((p, i) => {
    const s = stats[i] || {};
    return `<div class="project-card" onclick="location.hash='#/ledger?project=${p.id}'">
      <div class="p-name">${esc(p.name)}
        <button class="btn btn-sm" style="float:right" onclick="event.stopPropagation();openEditProject(${p.id})">✏️ 编辑</button>
      </div>
      <div class="p-meta">
        ${p.case_no ? `案号：${esc(p.case_no)}<br>` : ""}
        ${p.debtor ? `债务人：${esc(p.debtor)}<br>` : ""}
        ${p.manager ? `管理人：${esc(p.manager)}<br>` : ""}
        ${p.accept_date ? `受理日期：${esc(p.accept_date)}<br>` : ""}
        ${p.cloud_code ? `云端项目码：${esc(p.cloud_code)}<br>` : '<span style="color:var(--amber)">未填云端项目码<br></span>'}
        债权 ${s.total || 0} 笔（待登记 ${s.pending || 0} / 已登记 ${s.registered || 0} / 已复核 ${s.reviewed || 0}）<br>
        申报总额 ${fmtMoneySmart(s.sum_claimed)}　审核总额 ${fmtMoneySmart(s.sum_audited)}
      </div></div>`;
  }).join("");
}

async function openEditProject(projectId) {
  const p = await api.get(`/api/projects/${projectId}`);
  openModal(`${modalHead("编辑项目")}
    <div class="modal-body">
      <div class="field"><label>项目名称 *</label><input id="ep_name" value="${esc(p.name)}"></div>
      <div class="grid-2">
        <div class="field"><label>案号</label><input id="ep_case" value="${esc(p.case_no)}"></div>
        <div class="field"><label>债务人名称</label><input id="ep_debtor" value="${esc(p.debtor)}"></div>
      </div>
      <div class="grid-2">
        <div class="field"><label>管理人</label><input id="ep_manager" value="${esc(p.manager)}"></div>
        <div class="field"><label>破产受理日期</label><input id="ep_accept_date" type="date" value="${esc((p.accept_date || "").slice(0, 10))}"><div style="font-size:11px;color:var(--text-2)">法院裁定受理日（利息止息基准）</div></div>
      </div>
      <div class="grid-2">
        <div class="field"><label>云端项目码</label><input id="ep_cloud_code" value="${esc(p.cloud_code)}" placeholder="如：DEMO2026（与云端 CLOUD_PROJECT_CODES 一致）"></div>
        <div class="field"><label>备注</label><input id="ep_remark" value="${esc(p.remark)}"></div>
      </div>
    </div>
    <div class="modal-foot">
      <button class="btn" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="saveEditProject(${projectId})">保存</button>
    </div>`);
}
async function saveEditProject(projectId) {
  const body = {
    name: $("#ep_name").value.trim(),
    case_no: $("#ep_case").value.trim(),
    debtor: $("#ep_debtor").value.trim(),
    manager: $("#ep_manager").value.trim(),
    accept_date: $("#ep_accept_date").value,
    cloud_code: $("#ep_cloud_code").value.trim(),
    remark: $("#ep_remark").value.trim(),
  };
  if (!body.name) return toast("请填写项目名称", true);
  try {
    await api.put(`/api/projects/${projectId}`, body);
    closeModal();
    toast("项目已保存");
    renderProjects(parseHash().params, $("#app"));
  } catch (e) { toast(e.message, true); }
}

function openNewProject() {
  openModal(`${modalHead("新建项目")}
    <div class="modal-body">
      <div class="field"><label>项目名称 *</label><input id="np_name" placeholder="如：XX公司破产清算债权申报"></div>
      <div class="grid-2">
        <div class="field"><label>案号</label><input id="np_case" placeholder="如：（2024）粤01破1号"></div>
        <div class="field"><label>债务人名称</label><input id="np_debtor"></div>
      </div>
      <div class="grid-2">
        <div class="field"><label>管理人</label><input id="np_manager" placeholder="如：XX律师事务所"></div>
        <div class="field"><label>破产受理日期</label><input id="np_accept_date" type="date"><div style="font-size:11px;color:var(--text-2)">法院裁定受理日（利息止息基准）</div></div>
      </div>
      <div class="grid-2">
        <div class="field"><label>云端项目码</label><input id="np_cloud_code" placeholder="如：DEMO2026（与云端 CLOUD_PROJECT_CODES 一致）"></div>
        <div class="field"><label>备注</label><input id="np_remark"></div>
      </div>
    </div>
    <div class="modal-foot">
      <button class="btn" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="submitNewProject()">创建</button>
    </div>`);
}
async function submitNewProject() {
  const body = {
    name: $("#np_name").value.trim(),
    case_no: $("#np_case").value.trim(),
    debtor: $("#np_debtor").value.trim(),
    manager: $("#np_manager").value.trim(),
    accept_date: $("#np_accept_date").value,
    cloud_code: $("#np_cloud_code").value.trim(),
    remark: $("#np_remark").value.trim(),
  };
  if (!body.name) return toast("请填写项目名称", true);
  const p = await api.post("/api/projects", body);
  closeModal();
  toast(`项目「${p.name}」已创建`);
  location.hash = `#/ledger?project=${p.id}`;
}

// ---------- 视图：债权台账 ----------
let ledgerState = { projectId: null, keyword: "", status: "", category: "",
                    nature: "", aiStatus: "", minAmt: "", maxAmt: "", selected: {} };

// 债权性质标准 7 类（台账/审查/统计统一口径）
const NATURE_OPTIONS = ["购房者优先权", "工程款优先权", "抵押债权", "职工债权",
                        "税收债权", "普通债权", "劣后债权"];

// 台账完整列（与导入模板一致）
const LEDGER_COLS = [
  { key: "seq", label: "序号", w: 50 },
  { key: "claim_no", label: "债权编号", w: 90 },
  { key: "name", label: "债权人名称", w: 200 },
  { key: "credit_code", label: "统一社会信用代码/身份证号码", w: 180 },
  { key: "legal_rep", label: "法定代表人/负责人", w: 110 },
  { key: "contact_info", label: "联系方式", w: 130 },
  { key: "address", label: "联系地址", w: 220 },
  { key: "agent_name", label: "代理人姓名", w: 100 },
  { key: "agent_id_no", label: "代理人身份证号", w: 170 },
  { key: "agent_contact", label: "代理人联系方式", w: 130 },
  { key: "agent_address", label: "代理人地址", w: 200 },
  { key: "account_name", label: "开户名称", w: 130 },
  { key: "bank_name", label: "开户行", w: 160 },
  { key: "account_no", label: "账号", w: 160 },
  { key: "claim_category", label: "债权种类", w: 90 },
  { key: "litigation_status", label: "涉诉涉执情况", w: 110 },
  { key: "claim_nature", label: "申报债权性质", w: 120 },
  { key: "claim_date", label: "申报债权时间", w: 120 },
  { key: "principal", label: "申报本金", w: 110, money: true },
  { key: "interest", label: "申报利息", w: 110, money: true },
  { key: "others", label: "申报其他", w: 110, money: true },
  { key: "claim_amount", label: "申报总额", w: 120, money: true },
  // 虚拟列：核减金额 = 申报总额 − 审核总额（审核金额为空时不显示）
  { key: "reduction", label: "核减金额", w: 140, virtual: true },
  { key: "audited_principal", label: "审核本金", w: 110, money: true },
  { key: "audited_interest", label: "审核利息", w: 110, money: true },
  { key: "audited_others", label: "审核其他", w: 110, money: true },
  { key: "audited_amount", label: "审核总额", w: 120, money: true },
  { key: "debt_nature", label: "债权性质", w: 110 },
  { key: "guarantee_notes", label: "担保情况备注", w: 180 },
  { key: "claim_type", label: "债权类型", w: 100 },
  { key: "status", label: "状态", w: 90 },
  { key: "source_files", label: "来源材料", w: 180 },
  { key: "created_at", label: "创建时间", w: 150 },
];
// 默认显示的列（精简为 8 列：编号/名称/性质/申报总额/核减/状态 + AI审查 + 操作）
const DEFAULT_VISIBLE = ["claim_no", "name", "claim_nature", "claim_amount",
                         "reduction", "status"];
const COLS_KEY = "ledger_cols_v2";   // v2：默认列精简后换键，避免沿用旧的 12 列设置

function getVisibleCols() {
  try {
    const v = JSON.parse(localStorage.getItem(COLS_KEY));
    if (Array.isArray(v) && v.length) {
      const keys = LEDGER_COLS.map((c) => c.key);
      return v.filter((k) => keys.includes(k));
    }
  } catch (e) {}
  return DEFAULT_VISIBLE.slice();
}
function saveVisibleCols(keys) {
  localStorage.setItem(COLS_KEY, JSON.stringify(keys));
}

function cellValue(c, col) {
  if (col.key === "seq") return c.seq || "";
  if (col.money) return fmtMoney(c[col.key]);
  const v = c[col.key];
  if (v === null || v === undefined || v === "") return "—";
  return v;
}

async function renderLedger(params, app) {
  // 项目来源：URL 参数 > 当前项目记忆；都没有则展示项目选择
  let projectId = params.project ? Number(params.project) : null;
  if (!projectId) {
    const cur = getCurrentProject();
    if (cur && cur.id) projectId = cur.id;
  }
  if (!projectId) {
    renderProjectPicker(app, "债权台账", "选择一个项目进入台账，之后的操作默认在该项目下进行");
    return;
  }
  ledgerState.projectId = projectId;
  const [project, stats, claims] = await Promise.all([
    api.get(`/api/projects/${projectId}`),
    api.get(`/api/projects/${projectId}/stats`),
    api.get(`/api/claims?project_id=${projectId}`),
  ]);
  setCurrentProject(project); // 记住当前项目
  renderLedgerHTML(app, project, stats, claims);
}

function renderLedgerHTML(app, project, stats, claims) {
  const kw = ledgerState.keyword, st = ledgerState.status, cat = ledgerState.category;
  const cats = [...new Set(claims.map((c) => c.claim_category).filter(Boolean))];
  // 初始渲染时的条数（审查状态筛选在异步拉取审查记录后于 renderLedgerList 中精确计算）
  const filtered = filterClaims(claims, null);
  const visibleCols = getVisibleCols();
  ledgerState.selected = {};

  app.innerHTML = `
    ${ledgerTabsHtml(project.id, "ledger")}
    ${acceptDateWarningHtml(project)}
    <div class="page-head">
      <div>
        <div class="page-title">${esc(project.name)}<span style="font-weight:400;color:var(--text-2);font-size:13px">　${esc(project.case_no || "")}</span></div>
        <div class="page-sub">上传申报材料 → AI 解析识别 → 登记/复核 → AI 审查 → 导出</div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn" onclick="openLedgerGuide()">❓ 使用指引</button>
      </div>
    </div>
    <div class="stats">
      <div class="stat-card clickable ${st === "" ? "active" : ""}" onclick="setLedgerStatus('')" title="点击查看全部">
        <div class="num">${stats.total}</div><div class="label">债权总笔数</div></div>
      <div class="stat-card clickable ${st === "pending" ? "active" : ""}" onclick="setLedgerStatus('pending')" title="点击只看待登记">
        <div class="num">${stats.pending}</div><div class="label">待登记（待初审/编辑）</div></div>
      <div class="stat-card clickable ${st === "registered" ? "active" : ""}" onclick="setLedgerStatus('registered')" title="点击只看已登记">
        <div class="num">${stats.registered}</div><div class="label">已登记（待审查/复核）</div></div>
      <div class="stat-card clickable ${st === "reviewed" ? "active" : ""}" onclick="setLedgerStatus('reviewed')" title="点击只看已复核">
        <div class="num">${stats.reviewed}</div><div class="label">已复核（可导出）</div></div>
      <div class="stat-card">${statNum(stats.sum_claimed, "申报总额")}</div>
      <div class="stat-card">${statNum(stats.sum_audited, "审核总额")}</div>
    </div>
    ${ledgerActionAreaHtml(claims.length > 0)}
    <div id="parsePanel" class="parse-panel" style="display:none;margin-bottom:14px"></div>
    <div class="card">
      <div class="ledger-toolbar">
        <div class="filter-bar" style="margin-bottom:0">
          <input id="fkw" placeholder="搜索 名称/编号/信用代码" value="${esc(kw)}" oninput="ledgerState.keyword=this.value;renderLedgerList()">
          <div class="seg" id="statusSeg">
            <button class="seg-btn ${st === "" ? "on" : ""}" onclick="setLedgerStatus('')">全部 <b>${claims.length}</b></button>
            <button class="seg-btn ${st === "pending" ? "on" : ""}" onclick="setLedgerStatus('pending')">待登记 <b>${stats.pending}</b></button>
            <button class="seg-btn ${st === "registered" ? "on" : ""}" onclick="setLedgerStatus('registered')">已登记 <b>${stats.registered}</b></button>
            <button class="seg-btn ${st === "reviewed" ? "on" : ""}" onclick="setLedgerStatus('reviewed')">已复核 <b>${stats.reviewed}</b></button>
          </div>
          <button class="btn btn-sm" onclick="toggleAdvFilter()">⚙ 高级筛选<span id="advDot" class="adv-dot" ${hasAdvFilter() ? "" : "hidden"}>•</span></button>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn" onclick="openColumnSettings()">⚙️ 列设置</button>
          <button class="btn" id="btnBatchDel" style="display:none" onclick="batchDeleteClaims()">🗑 批量删除（<span id="selCount">0</span>）</button>
        </div>
      </div>
      <div class="batch-bar" id="batchBar" hidden>
        <span class="cnt">已选 <b id="batchCount">0</b> 笔</span>
        <button class="btn btn-sm btn-primary" onclick="batchRegisterClaims()">✓ 批量登记</button>
        <button class="btn btn-sm btn-primary" onclick="batchAiAudit()">🤖 批量 AI 审查</button>
        <button class="btn btn-sm" onclick="batchExportLedger()">📊 导出选中台账</button>
        <button class="btn btn-sm" onclick="batchExportOpinions()">📄 导出选中意见书</button>
        <button class="btn btn-sm btn-danger" onclick="batchDeleteClaims()">🗑 批量删除</button>
        <button class="btn btn-sm" onclick="clearSelection()">✕ 取消选择</button>
      </div>
      <div class="chips" id="filterChips"></div>
      <div class="filter-bar adv-filter" id="advFilter" ${hasAdvFilter() ? "" : "hidden"}>
        <select id="fcat" onchange="ledgerState.category=this.value;renderLedgerList()">
          <option value="">全部种类</option>${cats.map((c) => `<option ${ledgerState.category === c ? "selected" : ""}>${esc(c)}</option>`).join("")}
        </select>
        <select id="fnat" onchange="ledgerState.nature=this.value;renderLedgerList()">
          <option value="">全部性质</option>
          ${NATURE_OPTIONS.map((n) => `<option value="${n}" ${ledgerState.nature === n ? "selected" : ""}>${n}</option>`).join("")}
        </select>
        <select id="fai" onchange="ledgerState.aiStatus=this.value;renderLedgerList()">
          <option value="">AI 审查：全部</option>
          <option value="none" ${ledgerState.aiStatus === "none" ? "selected" : ""}>AI 未审查</option>
          <option value="running" ${ledgerState.aiStatus === "running" ? "selected" : ""}>AI 审查中</option>
          <option value="done" ${ledgerState.aiStatus === "done" ? "selected" : ""}>AI 已审查</option>
          <option value="failed" ${ledgerState.aiStatus === "failed" ? "selected" : ""}>AI 审查失败</option>
        </select>
        <span style="font-size:12px;color:var(--text-2);white-space:nowrap">申报金额</span>
        <input id="fmin" type="number" placeholder="≥" style="width:100px" value="${ledgerState.minAmt}"
          oninput="ledgerState.minAmt=this.value;renderLedgerList()">
        <input id="fmax" type="number" placeholder="≤" style="width:100px" value="${ledgerState.maxAmt}"
          oninput="ledgerState.maxAmt=this.value;renderLedgerList()">
        <button class="btn btn-sm" onclick="resetLedgerFilter()">↺ 重置筛选</button>
        <span style="color:var(--text-2);font-size:12px">共 ${filtered.length} / ${claims.length} 条</span>
      </div>
      <div class="ledger-scroll">
        <table class="tbl nowrap">
          <thead><tr>
            <th class="chk"><input type="checkbox" id="chkAll" onclick="toggleSelectAll(this)"></th>
            ${visibleCols.map((k) => {
              const col = LEDGER_COLS.find((c) => c.key === k);
              if (!col) return "";
              const num = col.money || col.key === "reduction" ? " class=\"num\"" : "";
              return `<th${num} style="min-width:${col.w}px">${esc(col.label)}</th>`;
            }).join("")}
            <th style="min-width:80px">AI审查</th>
            <th class="col-actions" style="min-width:170px">操作</th>
          </tr></thead>
          <tbody id="ledgerBody"></tbody>
        </table>
      </div>
      <div class="table-tip">提示：点任意一行进入「债权审查工作台」；每行只显示当前该做的一步，其余操作在「⋯」里。</div>
    </div>`;

  // 新增债权申报：按钮选文件 + 把卡片/操作条本身作为拖拽目标（两种形态都带 id=dropzone）
  const dz = $("#dropzone");
  const upBtn = $("#quickUploadBtn");
  if (upBtn) upBtn.addEventListener("click", () => $("#fileInput").click());
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
  dz.addEventListener("dragleave", (e) => {
    if (!dz.contains(e.relatedTarget)) dz.classList.remove("drag");
  });
  dz.addEventListener("drop", (e) => {
    e.preventDefault(); dz.classList.remove("drag");
    handleUpload([...e.dataTransfer.files]);
  });
  $("#fileInput").addEventListener("change", (e) => handleUpload([...e.target.files]));
  // 关闭行内「⋯」菜单：点击空白处、按 Esc、滚动或切换页面
  if (!window.__rowMenuBound) {
    window.__rowMenuBound = true;
    document.addEventListener("click", (e) => {
      if (!e.target.closest || !e.target.closest(".row-menu")) closeAllRowMenus();
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAllRowMenus(); });
    document.addEventListener("scroll", closeAllRowMenus, true);   // 表格内部滚动也收起
    window.addEventListener("resize", closeAllRowMenus);
    window.addEventListener("hashchange", closeAllRowMenus);
  }
  renderLedgerList();
  refreshOnlineBadge();
}

/* ---------------- 高级筛选展开/收起、状态切换 ---------------- */
function hasAdvFilter() {
  const { category, nature, aiStatus, minAmt, maxAmt } = ledgerState;
  return !!(category || nature || aiStatus || minAmt !== "" || maxAmt !== "");
}
function toggleAdvFilter() {
  const box = $("#advFilter");
  if (!box) return;
  box.hidden = !box.hidden;
}
/* 高级筛选是否生效：提示点随每次列表刷新同步（改了筛选立即有反馈） */
function updateAdvDot() {
  const dot = $("#advDot");
  if (dot) dot.hidden = !hasAdvFilter();
}
/* ---------------- 台账 / 审查 双 Tab ---------------- */
function ledgerTabsHtml(projectId, active) {
  const suffix = projectId ? `?project=${projectId}` : "";
  return `<div class="view-tabs">
    <a class="view-tab ${active === "ledger" ? "on" : ""}" href="#/ledger${suffix}">📋 债权台账</a>
    <a class="view-tab ${active === "audit" ? "on" : ""}" href="#/ledger${suffix}${suffix ? "&" : "?"}tab=audit">🔍 审查</a>
  </div>`;
}
/* 破产受理日缺失提示：它是时效/优先权期限/止息判断的基准，也是统计口径的一部分 */
function acceptDateWarningHtml(project) {
  if (!project || str(project.accept_date).trim()) return "";
  return `<div class="warn-bar">
    ⚠ 本项目未填写「<b>破产受理日</b>」：AI 审查无法准确判断诉讼时效、建设工程优先权行使期限
    与利息止息（模型会在对应级别标注"无法判断，需补充"），数据后台的期间口径也不完整。
    <a class="link" onclick="openEditProject(${project.id})">现在补填 →</a>
  </div>`;
}
function str(v) { return v === null || v === undefined ? "" : String(v); }
/* ---------------- 已生效筛选标签（可单个移除） ---------------- */
const FILTER_LABELS = { category: "种类", nature: "性质", aiStatus: "AI审查" };
const AI_STATUS_TEXT = { none: "未审查", running: "审查中", done: "已审查", failed: "失败" };
function updateFilterChips() {
  const box = $("#filterChips");
  if (!box) return;
  const { keyword, category, nature, aiStatus, minAmt, maxAmt, status } = ledgerState;
  const chips = [];
  if (keyword) chips.push(["keyword", `搜索：<b>${esc(keyword)}</b>`]);
  if (status) chips.push(["status", `流程状态：<b>${{ pending: "待登记", registered: "已登记", reviewed: "已复核" }[status] || status}</b>`]);
  if (category) chips.push(["category", `${FILTER_LABELS.category}：<b>${esc(category)}</b>`]);
  if (nature) chips.push(["nature", `${FILTER_LABELS.nature}：<b>${esc(nature)}</b>`]);
  if (aiStatus) chips.push(["aiStatus", `${FILTER_LABELS.aiStatus}：<b>${AI_STATUS_TEXT[aiStatus] || aiStatus}</b>`]);
  if (minAmt !== "" && minAmt !== undefined) chips.push(["minAmt", `金额 ≥ <b>${esc(String(minAmt))}</b>`]);
  if (maxAmt !== "" && maxAmt !== undefined) chips.push(["maxAmt", `金额 ≤ <b>${esc(String(maxAmt))}</b>`]);
  box.innerHTML = chips.length
    ? chips.map(([k, html]) =>
        `<span class="chip">${html}<span class="x" title="移除该条件" onclick="clearLedgerFilter('${k}')">✕</span></span>`).join("")
      + (chips.length > 1 ? `<span class="clear" onclick="resetLedgerFilter()">清除全部</span>` : "")
    : "";
}
function clearLedgerFilter(key) {
  ledgerState[key] = "";
  // 同步回对应的控件
  if (key === "keyword" && $("#fkw")) $("#fkw").value = "";
  if (key === "category" && $("#fcat")) $("#fcat").value = "";
  if (key === "nature" && $("#fnat")) $("#fnat").value = "";
  if (key === "aiStatus" && $("#fai")) $("#fai").value = "";
  if (key === "minAmt" && $("#fmin")) $("#fmin").value = "";
  if (key === "maxAmt" && $("#fmax")) $("#fmax").value = "";
  if (key === "status") {
    $$(".stat-card.clickable").forEach((el) => el.classList.remove("active"));
    const all = $$(".stat-card.clickable")[0];
    if (all) all.classList.add("active");
    $$("#statusSeg .seg-btn").forEach((b, i) => b.classList.toggle("on", i === 0));
  }
  renderLedgerList();
}
/* ---------------- 数据进出（新增 / 导入 / 在线申报 / 导出） ---------------- */
const FILE_ACCEPT = ".pdf,.doc,.docx,.txt,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp";
// 空项目：4 张动作卡说明差异；有数据：收成一行紧凑操作条（两者都是拖拽上传目标）
function ledgerActionAreaHtml(hasData) {
  if (hasData) {
    return `
    <div class="card quick-actions" id="dropzone" title="把申报材料拖到这里＝新增一笔债权申报">
      <input type="file" id="fileInput" multiple hidden accept="${FILE_ACCEPT}">
      <div class="quick-row">
        <button class="btn btn-primary" id="quickUploadBtn">🆕 新增债权申报</button>
        <button class="btn" onclick="importLedger()">📥 导入台账</button>
        <a class="link" onclick="downloadTemplate()" title="下载导入模板（Excel，可作为台账导出格式）">📋 模板</a>
        <span class="quick-sep"></span>
        <button class="btn" onclick="openOnlineClaims()">🌐 在线申报 <span id="ocBadge" class="oc-badge" style="display:none"></span></button>
        <span class="quick-sep"></span>
        <button class="btn" onclick="exportLedger()">📊 导出台账</button>
        <button class="btn" onclick="exportOpinions()">📄 意见书 zip</button>
        <span class="quick-hint">新增＝上传材料自动建档（也可把文件拖到本区域）｜补充材料请在行内「⋯」里操作</span>
      </div>
      <div id="ocHint" style="font-size:12px;color:var(--text-2);margin-top:6px"></div>
    </div>`;
  }
  return `
  <div class="action-cards">
    <div class="action-card primary droppable" id="dropzone">
      <input type="file" id="fileInput" multiple hidden accept="${FILE_ACCEPT}">
      <div class="ac-icon">🆕</div>
      <div class="ac-title">新增债权申报</div>
      <div class="ac-desc">上传债权申报材料（图片 / PDF / Word，可多选），系统自动建成一笔债权（编号 PC-001…）
        并 AI 识别债权人信息、金额等字段。</div>
      <div class="ac-actions"><button class="btn btn-primary" id="quickUploadBtn">选择文件上传</button></div>
      <div class="ac-hint">也可把文件直接拖到这张卡片上</div>
    </div>
    <div class="action-card">
      <div class="ac-icon">📥</div>
      <div class="ac-title">导入台账 Excel</div>
      <div class="ac-desc">把已经登记好的债权台账批量搬进本系统（按模板列对应导入），适合历史案件迁移。</div>
      <div class="ac-actions">
        <button class="btn" onclick="importLedger()">选择 Excel 导入</button>
      </div>
      <div class="ac-hint"><a class="link" onclick="downloadTemplate()">📋 下载导入模板</a>（导入前请先对照列名）</div>
    </div>
    <div class="action-card">
      <div class="ac-icon">🌐</div>
      <div class="ac-title">在线申报 <span id="ocBadge" class="oc-badge" style="display:none"></span></div>
      <div class="ac-desc">把云端申报链接发给债权人，他们自行填写并上传材料；管理人在这里拉取、一键导入台账（同名自动查重）。</div>
      <div class="ac-actions"><button class="btn" onclick="openOnlineClaims()">打开在线申报</button></div>
      <div class="ac-hint" id="ocHint"></div>
    </div>
    <div class="action-card">
      <div class="ac-icon">📊</div>
      <div class="ac-title">导出</div>
      <div class="ac-desc">台账 Excel（含审核金额与核减）用于对外报送与留档；审查意见书 zip 是按债权人分份的正式文书。</div>
      <div class="ac-actions">
        <button class="btn" onclick="exportLedger()">导出台账 Excel</button>
        <button class="btn" onclick="exportOpinions()">导出意见书 zip</button>
      </div>
      <div class="ac-hint">只导其中几笔：先勾选行，再用批量条「导出选中…」</div>
    </div>
  </div>`;
}

/* ---------------- 使用指引 ---------------- */
function openLedgerGuide() {
  const steps = [
    ["上传建档", "上方「＋ 新增债权申报」上传申报材料（图片/PDF/Word，可多选），系统自动建一笔债权（PC-001…）并 AI 解析识别债权人信息。"],
    ["核对登记", "点该行「✎ 初审 / 编辑」核对字段（金额总额会自动按分项汇总）；保存后状态自动变为「已登记」，无需再单独点登记按钮。"],
    ["AI 审查", "点该行「🤖 AI 审查」（或直接点 AI 审查徽标）即可发起，无需跳页；审查中该行显示禁用的「⏳ 审查中」，完成后自动变成「✍️ 人工复核」。"],
    ["人工复核定稿", "点「✍️ 人工复核」填写审核金额与意见，定稿后状态变「已复核」，台账自动显示「核减金额」与核减比例。"],
    ["补材料 / 重审", "债权人后续补交材料：该行「⋯ → 📎 补充材料」，新材料与原件同页预览、自动解析，AI 审查结论会清空、状态退回「已登记」，重新审查即可。"],
    ["导出", "右上角「📊 导出台账 Excel」「📄 意见书合集 zip」导出全项目；勾选若干行后，用批量条「导出选中台账 / 选中意见书」只导出选中部分。"],
  ];
  openModal(`${modalHead("台账页使用指引")}
    <div class="modal-body">
      <div style="font-size:13px;color:var(--text-2);margin-bottom:6px">
        流程主线：上传建档 → 核对登记 → AI 审查 → 人工复核 → 导出。
      </div>
      ${steps.map(([t, d], i) =>
        `<div class="guide-step"><div class="n">${i + 1}</div>
          <div class="t"><b>${esc(t)}</b>：${esc(d)}</div></div>`).join("")}
      <div style="margin-top:10px;font-size:12.5px;color:var(--text-2);line-height:1.9">
        小抄：① 每行只显示「当前该做的一步」，其余操作在「⋯」里；② 点整行进入审查工作台；
        ③ 顶部统计卡可点击直接筛选（待登记/已登记/已复核）；④ 高级筛选支持单个条件移除（筛选标签上的 ✕）；
        ⑤ 操作列固定在右侧，横向滚动也能点到。
      </div>
    </div>
    <div class="modal-foot"><button class="btn btn-primary" onclick="closeModal()">知道了</button></div>`,
    { wide: true });
}
/* 状态筛选：统计卡片与分段按钮共用；只重绘列表与选中态，避免整页重渲染 */
function setLedgerStatus(s) {
  ledgerState.status = s;
  $$(".stat-card.clickable").forEach((el) => el.classList.remove("active"));
  $$("#statusSeg .seg-btn").forEach((b) => b.classList.remove("on"));
  const idx = { "": 0, pending: 1, registered: 2, reviewed: 3 }[s] ?? 0;
  const card = $$(".stat-card.clickable")[idx];
  if (card) card.classList.add("active");
  const btn = $$("#statusSeg .seg-btn")[idx];
  if (btn) btn.classList.add("on");
  renderLedgerList();
}

// 台账筛选（关键词/状态/种类/性质/审查状态/金额区间）；auditMap 可选（用于审查状态筛选）
function filterClaims(claims, auditMap) {
  const { keyword: kw, status: st, category: cat, nature, aiStatus,
          minAmt, maxAmt } = ledgerState;
  const NATURE_NORM = { "工程债权": "工程款优先权", "购房优先权": "购房者优先权",
                        "税收": "税收债权", "税款债权": "税收债权", "职工": "职工债权" };
  return claims.filter((c) => {
    if (kw && !((c.name || "").includes(kw) || (c.claim_no || "").includes(kw)
                || (c.credit_code || "").includes(kw))) return false;
    if (st && c.status !== st) return false;
    if (cat && c.claim_category !== cat) return false;
    if (nature) {
      const raw = String(c.claim_nature || "").trim();
      if ((NATURE_NORM[raw] || raw) !== nature) return false;
    }
    if (aiStatus) {
      const a = auditMap ? auditMap[c.id] : null;
      const s = a ? (a.ai_status || "none") : "none";
      if (s !== aiStatus) return false;
    }
    const amt = Number(c.claim_amount || 0);
    if (minAmt !== "" && minAmt !== undefined && amt < Number(minAmt)) return false;
    if (maxAmt !== "" && maxAmt !== undefined && amt > Number(maxAmt)) return false;
    return true;
  });
}

function resetLedgerFilter() {
  ledgerState.keyword = ""; ledgerState.status = "";
  ledgerState.category = ""; ledgerState.nature = "";
  ledgerState.aiStatus = ""; ledgerState.minAmt = ""; ledgerState.maxAmt = "";
  renderLedger(parseHash().params, $("#app"));
}

function renderLedgerList() {
  const { projectId } = ledgerState;
  api.get(`/api/claims?project_id=${projectId}`).then(async (claims) => {
    // 拉取各条审查状态（用于 AI 审查状态筛选与展示）
    const audits = await Promise.all(claims.map((c) => api.get(`/api/claims/${c.id}/audit`).catch(() => null)));
    const auditMap = {}; audits.forEach((a, i) => { if (a) auditMap[claims[i].id] = a; });
    const filtered = filterClaims(claims, auditMap);
    updateAdvDot();
    updateFilterChips();
    const body = $("#ledgerBody");
    if (!body) return;
    if (!filtered.length) {
      body.innerHTML = `<tr><td colspan="99" class="empty">${
        claims.length
          ? `<div class="icon">🔍</div>没有符合当前筛选条件的债权（本项目共 ${claims.length} 笔）<br>
             <button class="btn btn-sm" style="margin-top:10px" onclick="resetLedgerFilter()">↺ 清除筛选条件</button>`
          : `<div class="icon">📂</div>本项目还没有债权，三步上手：<br>
             <span style="font-size:13px;line-height:2">
               ① 上方「🆕 新增债权申报」上传申报材料（自动建档 PC-001…）→
               ② 点这一行的「✎ 初审 / 编辑」核对并保存（保存后自动登记为「已登记」）→
               ③ 点「AI 审查」生成审查意见，再「人工复核」定稿导出
             </span>
             <br><span style="font-size:12.5px;color:var(--text-2)">已有 Excel 台账可走「📥 导入台账」；让债权人自己填可走「🌐 在线申报」</span>`
      }</td></tr>`;
      updateBatchBar();
      return;
    }
    const visibleCols = getVisibleCols();
    // 序号（跨页/筛选按过滤后顺序）
    filtered.forEach((c, i) => { c.seq = i + 1; });
    body.innerHTML = filtered.map((c) => {
      const a = auditMap[c.id];
      const aiStatus = a ? (a.ai_status || "none") : "none";
      const checked = ledgerState.selected[c.id] ? "checked" : "";
      const cells = visibleCols.map((k) => {
        const col = LEDGER_COLS.find((x) => x.key === k);
        if (!col) return "";
        if (k === "claim_no") return `<td><span class="link" onclick="event.stopPropagation();openPreviewPage(${c.id})"><b>${esc(cellValue(c, col))}</b></span></td>`;
        if (k === "name") return `<td><span class="link" onclick="event.stopPropagation();openPreviewPage(${c.id})">${esc(cellValue(c, col))}</span></td>`;
        if (k === "status") return `<td>${statusBadge(c.status)}</td>`;
        if (k === "reduction") return `<td class="num">${reductionHtml(c)}</td>`;
        return `<td class="${col.money ? "num" : ""}">${esc(cellValue(c, col))}</td>`;
      }).join("");
      const act = nextAction(c, aiStatus);
      const aiCanClick = aiStatus === "none" || aiStatus === "failed";
      const aiCell = aiCanClick
        ? `<span class="link" title="${aiStatus === "failed" ? "审查失败，点击重试" : "点击发起 AI 审查"}"
             onclick="event.stopPropagation();aiAuditFromList(${c.id})">${aiBadge(aiStatus)}</span>`
        : aiBadge(aiStatus);
      // 解析状态提示：解析中/失败在操作列给一个小标识（避免"点了没反应"的困惑）
      const pst = c.parse_status || "pending";
      const parseFlag = pst === "parsing"
        ? `<span title="材料解析中（扫描件走云解析可能需要数分钟）" style="margin-right:4px">⏳</span>`
        : (pst === "failed"
           ? `<span class="link" title="${esc(c.parse_error || "材料解析失败，建议重新解析")}；点击重新解析"
                onclick="event.stopPropagation();reparseClaim(${c.id})" style="margin-right:4px">⚠</span>`
           : "");
      return `<tr data-id="${c.id}" data-status="${c.status || "pending"}" data-parse="${pst}" class="${checked ? "row-selected" : ""}" title="${esc(act.hint)}"
            onclick="onLedgerRowClick(event, ${c.id})">
        <td class="chk"><input type="checkbox" ${checked} onclick="event.stopPropagation();toggleSelect(${c.id}, this)"></td>
        ${cells}
        <td>${aiCell}</td>
        <td class="col-actions" style="white-space:nowrap">
          ${parseFlag}
          ${act.disabled
            ? `<button class="btn btn-sm" disabled>${act.label}</button>`
            : `<button class="btn btn-sm ${act.cls}" onclick="event.stopPropagation();${act.call}">${act.label}</button>`}
          <div class="row-menu">
            <button class="btn btn-sm" title="更多操作" onclick="toggleRowMenu(event, this)">⋯</button>
          </div>
        </td></tr>`;
    }).join("");
    updateBatchBar();
  }).catch((e) => toast(e.message, true));
}

/* ---------------- 行内“下一步”与更多菜单 ---------------- */
// 核减金额（申报总额 − 审核总额）；未复核时不显示
function reductionHtml(c) {
  const q = Number(c.claim_amount || 0), a = Number(c.audited_amount || 0);
  if (!a) return `<span style="color:var(--text-2)">—</span>`;
  const d = Math.round((q - a) * 100) / 100;
  const pct = q ? (d / q * 100) : 0;
  const cls = d > 0 ? "cut" : (d < 0 ? "raise" : "");
  return `<span class="${cls}" title="申报 ${fmtMoney(q)} − 审核 ${fmtMoney(a)}">${fmtMoney(d)}<span class="pct">${pct.toFixed(1)}%</span></span>`;
}
// 当前该做的一步（主按钮）
function nextAction(c, aiStatus) {
  const st = c.status || "pending";
  if (st === "pending") {
    // 初审/编辑保存后自动登记，不再单独放「登记」按钮
    return { label: "✎ 初审 / 编辑", cls: "btn-primary", call: `openEditClaim(${c.id})`,
             hint: "核对信息并保存后自动登记（状态变为已登记）" };
  }
  if (st === "registered") {
    if (aiStatus === "running") return { label: "⏳ 审查中", cls: "", disabled: true, hint: "AI 正在分析材料，请稍候" };
    if (aiStatus === "done") return { label: "✍️ 人工复核", cls: "btn-primary", call: `openManualAudit(${c.id})`, hint: "AI 已出意见，请复核并定稿" };
    return { label: "🤖 AI 审查", cls: "btn-primary", call: `aiAuditFromList(${c.id})`,
             hint: aiStatus === "failed" ? "上次审查失败，点击重试" : "点击对该债权发起 AI 审查" };
  }
  return { label: "📄 查看结果", cls: "", call: `location.hash='#/audit?claim=${c.id}'`, hint: "已复核，可查看意见并导出" };
}
function onLedgerRowClick(e, id) {
  if (e.target.closest && e.target.closest("button, a, input, .row-menu")) return;
  location.hash = `#/audit?claim=${id}`;
}
/* 行操作菜单：浮层挂在 body 上（position:fixed），
   避免被表格滚动容器（.ledger-scroll overflow:auto）裁切或压在别的行下面 */
function rowMenuHtml(id, status) {
  const items = [
    [`openEditClaim(${id})`, "✎ 初审 / 编辑"],
    [`location.hash = '#/audit?claim=${id}'`, "🤖 审查工作台"],
    [`openManualAudit(${id})`, "✍️ 人工复核"],
    [`openSupplement(${id})`, "📎 补充材料"],
    [`openPreviewPage(${id})`, "👁 材料预览"],
    [`reparseClaim(${id})`, "↻ 重新解析"],
  ];
  // 已登记/已复核才可取消登记
  if (status && status !== "pending") items.push([`unregisterClaim(${id})`, "↩ 取消登记"]);
  items.push([`deleteClaim(${id})`, "🗑 删除该债权", "danger"]);
  return items.map(([call, label, cls]) =>
    `<button ${cls ? `class="${cls}" ` : ""}onclick="rowMenuAction(() => { ${call}; })">${label}</button>`).join("");
}
/* 取消登记：已登记/已复核 → 待登记（材料与审查记录保留） */
async function unregisterClaim(id) {
  if (!confirm("确认取消该债权的登记？状态将回到「待登记」（申报材料、AI 审查与人工复核记录都会保留）。")) return;
  try {
    await api.post(`/api/claims/${id}/unregister`);
    toast("已取消登记，状态回到「待登记」");
    renderLedgerList();
    refreshLedgerStats();
  } catch (e) { toast(e.message, true); }
}
function rowMenuAction(fn) {
  closeAllRowMenus();
  fn();
}
function toggleRowMenu(ev, btn) {
  ev.stopPropagation();
  const tr = btn.closest("tr");
  const id = Number(tr && tr.getAttribute("data-id"));
  const wasOpen = window.__rowMenuId === id && !!document.getElementById("rowMenuPop");
  closeAllRowMenus();
  if (wasOpen || !id) return;

  const pop = document.createElement("div");
  pop.id = "rowMenuPop";
  pop.className = "row-menu-pop";
  // 关键样式内联：即使浏览器缓存了旧 CSS（样式类未生效），浮层也不会变成普通块而错乱
  Object.assign(pop.style, {
    position: "fixed", zIndex: "60", minWidth: "152px", padding: "4px",
    background: "#fff", border: "1px solid var(--border)",
    borderRadius: "10px", boxShadow: "0 10px 28px rgba(16, 42, 67, .2)",
  });
  pop.innerHTML = rowMenuHtml(id, tr ? (tr.getAttribute("data-status") || "") : "");
  document.body.appendChild(pop);

  // 定位：默认在按钮右下展开；下方/右侧空间不足时自动翻转到上方/左移
  const r = btn.getBoundingClientRect();
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  let top = r.bottom + 6;
  if (top + ph > window.innerHeight - 8) top = Math.max(8, r.top - ph - 6);
  let left = r.right - pw;
  if (left < 8) left = 8;
  if (left + pw > window.innerWidth - 8) left = Math.max(8, window.innerWidth - pw - 8);
  pop.style.top = `${Math.round(top)}px`;
  pop.style.left = `${Math.round(left)}px`;
  window.__rowMenuId = id;
}
function closeAllRowMenus() {
  const pop = document.getElementById("rowMenuPop");
  if (pop) pop.remove();
  window.__rowMenuId = null;
}
// 台账内直接发起 AI 审查（轮询完成后刷新列表）
async function aiAuditFromList(id) {
  window.__aiBusy = window.__aiBusy || {};
  if (window.__aiBusy[id]) { toast("该债权正在审查中…"); return; }
  window.__aiBusy[id] = true;
  try {
    await api.post(`/api/claims/${id}/ai-audit`, {});
    toast("AI 审查已启动，正在分析材料…");
    renderLedgerList();
    aiAuditFromListPoll(id);
  } catch (e) {
    window.__aiBusy[id] = false;
    toast(e.message, true);
  }
}
async function aiAuditFromListPoll(id) {
  const t0 = Date.now();
  while (Date.now() - t0 < 900000) {
    await new Promise((r) => setTimeout(r, 4000));
    let a = null;
    try { a = await api.get(`/api/claims/${id}/audit`); } catch (e) { continue; }
    if (!a || a.ai_status === "running") continue;
    window.__aiBusy[id] = false;
    if (a.ai_status === "done") toast("AI 审查完成，该行已变为「人工复核」");
    else toast("AI 审查失败：" + (a.ai_error || "未知错误"), true);
    renderLedgerList();
    refreshLedgerStats();
    return;
  }
  window.__aiBusy[id] = false;
}
// 重新解析材料（清空解析文本后重跑；带进度显示，解析中会被后端拒绝）
async function reparseClaim(id) {
  const row = $(`#ledgerBody tr[data-id="${id}"]`);
  if (row && row.getAttribute("data-parse") === "parsing") {
    toast("该债权正在解析中，请稍候（大文件扫描件走云解析可能需要数分钟）", true);
    return;
  }
  if (!confirm("重新解析该债权的全部材料？已解析文本将清空重跑（扫描件需 OCR，可能较慢）。")) return;
  const panel = $("#parsePanel");
  if (panel) {
    panel.style.display = "";
    panel.innerHTML = `<h4 style="margin-bottom:8px">↻ 重新解析</h4>
      <div style="color:var(--text-2);font-size:13px">正在提交解析任务…</div>`;
  }
  try {
    await api.post(`/api/claims/${id}/reparse`, {});
    toast("已开始重新解析，进度见上方的解析面板…");
    renderLedgerList();
    const d0 = await api.get(`/api/claims/${id}/detail`);
    updateParsePanel(d0.files);
    try {
      const d = await pollParse(id, (fl) => updateParsePanel(fl));
      updateParsePanel(d.files);
      toast("重新解析完成，提取信息已同步（已有字段按只补空策略保留）");
    } catch (e) {
      if (panel) {
        panel.innerHTML = `<h4 style="margin-bottom:8px">↻ 重新解析未完成</h4>
          <div style="color:var(--red);font-size:13px">${esc(e.message)}</div>
          <div style="font-size:12px;color:var(--text-2);margin-top:6px">
          可在该行「⋯ → ↻ 重新解析」再试一次；超大扫描件建议拆分后分次上传，识别更稳。</div>`;
      }
      toast(e.message, true);
    }
    renderLedgerList();
    refreshLedgerStats();
  } catch (e) { toast(e.message, true); }
}

// ---------- 列设置 ----------
function openColumnSettings() {
  const visible = getVisibleCols();
  const items = LEDGER_COLS.map((c) =>
    `<label style="display:flex;align-items:center;gap:8px;padding:6px 4px;cursor:pointer">
      <input type="checkbox" value="${c.key}" ${visible.includes(c.key) ? "checked" : ""}>
      <span style="font-size:13px">${esc(c.label)}</span>
    </label>`).join("");
  openModal(`${modalHead("列设置（勾选显示，取消隐藏）")}
    <div class="modal-body">
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0 20px">${items}</div>
    </div>
    <div class="modal-foot">
      <button class="btn" onclick="resetColumns()">恢复默认</button>
      <button class="btn btn-primary" onclick="applyColumnSettings()">保存</button>
    </div>`, { wide: true });
}
function applyColumnSettings() {
  const keys = $$("#modalRoot input[type=checkbox]:checked").map((i) => i.value);
  saveVisibleCols(keys);
  closeModal();
  // 整页重渲染：表头与数据列同步更新，避免表头/数据错位
  renderLedger(parseHash().params, $("#app"));
}
function resetColumns() {
  localStorage.removeItem(COLS_KEY);
  closeModal();
  renderLedger(parseHash().params, $("#app"));
}

// ---------- 批量选择与删除 ----------
function toggleSelect(id, el) {
  if (el.checked) ledgerState.selected[id] = true;
  else delete ledgerState.selected[id];
  el.closest("tr").classList.toggle("row-selected", el.checked);
  updateBatchBar();
}
function toggleSelectAll(el) {
  const boxes = $$("#ledgerBody input[type=checkbox]");
  ledgerState.selected = {};
  boxes.forEach((cb) => {
    cb.checked = el.checked;
    const tr = cb.closest("tr");
    tr.classList.toggle("row-selected", el.checked);
    if (el.checked) {
      const id = Number(tr.getAttribute("data-id"));
      if (id) ledgerState.selected[id] = true;
    }
  });
  updateBatchBar();
}
function updateBatchBar() {
  const n = Object.keys(ledgerState.selected).length;
  const btn = $("#btnBatchDel");
  const cnt = $("#selCount");
  // 旧的工具栏删除按钮（保持兼容），以及新的批量操作条
  if (btn) btn.style.display = n ? "" : "none";
  if (cnt) cnt.textContent = n;
  const bar = $("#batchBar");
  const bcnt = $("#batchCount");
  if (bar) bar.hidden = !n;
  if (bcnt) bcnt.textContent = n;
}
function clearSelection() {
  ledgerState.selected = {};
  $$("#ledgerBody input[type=checkbox]").forEach((cb) => {
    cb.checked = false;
    const tr = cb.closest("tr");
    if (tr) tr.classList.remove("row-selected");
  });
  const all = $("#chkAll");
  if (all) all.checked = false;
  updateBatchBar();
}
function selectedIds() {
  return Object.keys(ledgerState.selected).map(Number);
}
/* 批量登记：跳过未填名称的债权（登记要求名称必填） */
async function batchRegisterClaims() {
  const ids = selectedIds();
  if (!ids.length) return toast("请先勾选债权", true);
  if (!confirm(`确认将选中的 ${ids.length} 笔债权标记为「已登记」？\n（未填写债权人名称的会被跳过）`)) return;
  let done = 0, skipped = 0, failed = 0;
  for (const id of ids) {
    try {
      await api.post(`/api/claims/${id}/register`);
      done += 1;
    } catch (e) {
      if (/名称/.test(e.message)) skipped += 1; else failed += 1;
    }
  }
  toast(`批量登记完成：成功 ${done} 笔${skipped ? `，跳过 ${skipped} 笔（缺名称）` : ""}${failed ? `，失败 ${failed} 笔` : ""}`);
  clearSelection();
  renderLedgerList();
  refreshLedgerStats();
}
/* 批量 AI 审查：并发发起，统一轮询，完成后汇总提示 */
async function batchAiAudit() {
  const ids = selectedIds();
  if (!ids.length) return toast("请先勾选债权", true);
  const claims = await api.get(`/api/claims?project_id=${ledgerState.projectId}`).catch(() => []);
  const running = claims.filter((c) => ids.includes(c.id) && (c.parse_status === "pending" || c.parse_status === "parsing"));
  if (running.length) {
    toast(`有 ${running.length} 笔材料仍在解析中，已跳过（解析完成后再审查）`, true);
  }
  const targets = ids.filter((id) => !running.some((c) => c.id === id));
  if (!targets.length) return;
  if (!confirm(`确认对选中的 ${targets.length} 笔债权执行 AI 审查？\n（可稍等，完成后会自动刷新并提示结果）`)) return;
  window.__aiBusy = window.__aiBusy || {};
  let started = 0;
  for (const id of targets) {
    try {
      await api.post(`/api/claims/${id}/ai-audit`, {});
      window.__aiBusy[id] = true;
      started += 1;
    } catch (e) { /* 单笔失败不影响其它 */ }
  }
  toast(`已发起 ${started} 笔 AI 审查，正在分析材料…`);
  clearSelection();
  renderLedgerList();
  // 统一轮询：每 5 秒看一遍，直到全部结束
  const t0 = Date.now();
  while (Date.now() - t0 < 1800000) {
    await new Promise((r) => setTimeout(r, 5000));
    let pending = 0, done = 0, failed = 0;
    for (const id of targets) {
      let a = null;
      try { a = await api.get(`/api/claims/${id}/audit`); } catch (e) { pending += 1; continue; }
      const s = a ? a.ai_status : "none";
      if (s === "done") done += 1;
      else if (s === "failed") failed += 1;
      else pending += 1;
      if (s !== "running") window.__aiBusy[id] = false;
    }
    renderLedgerList();
    if (!pending) {
      toast(`批量 AI 审查完成：成功 ${done} 笔${failed ? `，失败 ${failed} 笔（可在行内点 AI 徽标重试）` : ""}`);
      refreshLedgerStats();
      return;
    }
  }
  toast("批量审查超时，请稍后在台账查看各笔状态", true);
}
function batchExportLedger() {
  const ids = selectedIds();
  if (!ids.length) return toast("请先勾选债权", true);
  window.open(`/api/export/ledger?project_id=${ledgerState.projectId}&ids=${ids.join(",")}`, "_blank");
}
function batchExportOpinions() {
  const ids = selectedIds();
  if (!ids.length) return toast("请先勾选债权", true);
  window.open(`/api/export/opinions?project_id=${ledgerState.projectId}&ids=${ids.join(",")}`, "_blank");
}
async function batchDeleteClaims() {
  const ids = Object.keys(ledgerState.selected).map(Number);
  if (!ids.length) return;
  if (!confirm(`确认删除选中的 ${ids.length} 笔债权？其申报材料与审查记录将一并删除。`)) return;
  try {
    const r = await api.post("/api/claims/batch-delete", { ids });
    ledgerState.selected = {};
    toast(`已删除 ${r.deleted} 笔债权`);
    renderLedgerList();
    refreshLedgerStats();
  } catch (e) { toast(e.message, true); }
}

// ---------- 上传 ----------
function parseStatusBadge(s) {
  const m = {
    pending: ["badge-running", "⏳ 待解析"],
    done: ["badge-done", "✅ 解析完成"],
    empty: ["badge-pending", "⚠️ 无文本"],
    failed: ["badge-failed", "❌ 解析失败"],
  };
  const [cls, txt] = m[s] || ["badge-none", s || "未知"];
  return `<span class="badge ${cls}">${txt}</span>`;
}

// 解析引擎徽标：MinerU 云端 / 本地
function parseEngineBadge(e) {
  if (e === "mineru") return `<span class="badge badge-mineru" title="MinerU 云端解析（表格/公式还原）">☁️ MinerU</span>`;
  if (e === "local") return `<span class="badge badge-local" title="本地解析 / RapidOCR">💻 本地</span>`;
  return "";
}

// 材料来源徽标：补充材料单独标注，便于与首次申报材料区分
function originBadge(o) {
  return o === "supplement"
    ? `<span class="badge badge-running" title="该材料为后续补充上传">📎 补充</span>` : "";
}

/* ---------------- 补充材料 ---------------- */
// 可补充的文件类型（与后端 parser.ALLOWED_EXT 一致）
const SUPPLEMENT_ACCEPT = ".pdf,.doc,.docx,.txt,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp";

async function openSupplement(claimId) {
  let d;
  try {
    d = await api.get(`/api/claims/${claimId}/detail`);
  } catch (e) { return toast(e.message, true); }
  const c = d.claim, files = d.files || [];
  const audit = d.audit || {};
  const resetTips = [];
  if (audit.ai_status && audit.ai_status !== "none") resetTips.push("清空原有 AI 审查结论（回到「未审查」）");
  if (audit.manual_status === "done") resetTips.push("人工复核标记为未完成（原意见与审核金额保留，下次复核会自动带出）");
  if (c.status === "reviewed") resetTips.push("流程状态由「已复核」退回「已登记」");

  openModal(`${modalHead(`补充材料 · ${c.claim_no}${c.name ? " · " + esc(c.name) : ""}`)}
    <div class="modal-body">
      <div class="audit-section" style="margin-bottom:14px">
        <h4>现有材料（共 ${files.length} 份）</h4>
        <div class="content" style="max-height:180px;overflow:auto">
          ${files.map((f) => `<div class="file-item" style="margin-bottom:4px">
            <span>📄</span><span class="fname">${esc(f.filename)}</span>${originBadge(f.origin)}${parseEngineBadge(f.parse_engine)}${parseStatusBadge(f.parse_status)}
          </div>`).join("") || `<span style="color:var(--text-2)">（暂无材料）</span>`}
        </div>
      </div>
      <div class="field">
        <label>选择要补充的材料（可多选：图片 / PDF / Word / 文本）</label>
        <input type="file" id="supFiles" multiple accept="${SUPPLEMENT_ACCEPT}">
      </div>
      <div class="audit-section">
        <h4>补充后系统将自动执行</h4>
        <div class="content" style="font-size:13px">
          1. 新材料与原有材料一并入库，可在<b>同一个材料预览页</b>中查看（标注「📎 补充」）；<br>
          2. 后台扫描解析新材料（扫描件走 OCR / MinerU）并<b>同步提取信息到台账</b>（仅填充空白字段，不覆盖已登记内容）；<br>
          3. ${resetTips.length ? "<b>" + resetTips.join("；") + "</b>，需重新执行 AI 审查与人工复核。" : "该债权当前无 AI 审查结论与复核结果，无需重置。"}
        </div>
      </div>
      <div id="supResult" style="margin-top:12px"></div>
    </div>
    <div class="modal-foot">
      <button class="btn" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" id="supBtn" onclick="submitSupplement(${claimId})">📎 上传补充材料</button>
    </div>`, { wide: true });
}

async function submitSupplement(claimId) {
  const input = $("#supFiles");
  const files = input && input.files ? [...input.files] : [];
  if (!files.length) return toast("请先选择要补充的材料", true);
  const btn = $("#supBtn"), box = $("#supResult");
  btn.disabled = true; btn.textContent = "上传中…";
  box.innerHTML = `<div style="color:var(--text-2);font-size:13px">正在上传 ${files.length} 份材料…</div>`;
  try {
    const r = await api.upload(`/api/claims/${claimId}/supplement`, files);
    const newIds = new Set((r.files || []).map((f) => f.id));
    const d0 = await api.get(`/api/claims/${claimId}/detail`);
    const renderNew = (all) => {
      const list = (all || []).filter((f) => newIds.has(f.id));
      box.innerHTML = `
        <div class="audit-section">
          <h4>新材料解析进度</h4>
          <div class="content">
            ${list.map((f) => `<div class="file-item" style="margin-bottom:4px">
              <span>📄</span><span class="fname">${esc(f.filename)}</span>${parseEngineBadge(f.parse_engine)}${parseStatusBadge(f.parse_status)}
            </div>`).join("")}
          </div>
        </div>`;
    };
    renderNew(d0.files);
    toast(`已补充 ${r.added} 份材料，正在解析并提取信息…`);
    const d = await pollParse(claimId, renderNew);
    renderNew(d.files);
    const c = await api.get(`/api/claims/${claimId}`);
    const resetNote = r.reset && r.reset.status_before === "reviewed"
      ? `流程状态已由「已复核」退回「已登记」` : `流程状态保持「${statusText(c.status)}」`;
    box.innerHTML += `
      <div class="audit-section" style="border-left:3px solid var(--green)">
        <h4>✅ 补充完成</h4>
        <div class="content" style="font-size:13px">
          已追加 ${r.added} 份材料并完成解析，提取信息已按「只补空」策略同步台账；<br>
          AI 审查已重置为「未审查」，${resetNote}，请重新执行 AI 审查与人工复核。<br>
          <div style="margin-top:8px;display:flex;gap:8px">
            <button class="btn btn-sm" onclick="openPreviewPage(${claimId})">👁 查看全部材料预览</button>
            <button class="btn btn-sm" onclick="location.hash='#/audit?claim=${claimId}';closeModal();">🤖 前往重新审查</button>
          </div>
        </div>
      </div>`;
    toast("补充材料解析完成：信息已同步，AI 审查已重置为未审查");
    // 刷新背后页面（台账列表 / 审查工作台），弹窗保持打开以便查看结果
    if ($("#ledgerBody")) renderLedgerList();
    else router();
  } catch (e) {
    toast(e.message, true);
    box.innerHTML = `<div style="color:var(--red);font-size:13px">补充失败：${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false; btn.textContent = "📎 上传补充材料";
  }
}

function statusText(s) {
  return { pending: "待登记", registered: "已登记", reviewed: "已复核" }[s] || s || "—";
}

function updateParsePanel(files) {
  const panel = $("#parsePanel");
  if (!panel || !files || !files.length) return;
  const total = files.length;
  const doneN = files.filter((f) => f.parse_status !== "pending").length;
  const pct = Math.round((doneN / total) * 100);
  const done = doneN === total;
  const mineruN = files.filter((f) => f.parse_engine === "mineru").length;
  panel.style.display = "";
  panel.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <h4 style="margin:0">📤 上传与解析进度</h4>
      <span style="font-size:13px;color:var(--text-2)">${doneN} / ${total} 个文件${mineruN ? `　·　☁️ MinerU ${mineruN} 份` : ""}</span>
    </div>
    <div class="bar-track" style="margin-bottom:10px">
      <div class="bar-fill ${done ? "bg-ok" : "bg-part"}" style="width:${pct}%"></div>
    </div>
    ${files.map((f) => `<div class="file-item" style="margin-bottom:4px">
      <span>📄</span><span class="fname">${esc(f.filename)}</span>${parseEngineBadge(f.parse_engine)}${parseStatusBadge(f.parse_status)}
    </div>`).join("")}
    ${done ? `<div style="color:var(--text-2);font-size:12px">✅ 全部文件解析完成</div>` : ""}`;
}

async function handleUpload(files) {
  if (!files.length) return;
  const { projectId } = ledgerState;
  // 上传锁：正在上传/解析时忽略新的选择，避免并发错乱
  if (window.__uploading) {
    toast("正在处理上一份上传，请稍候…", true);
    return;
  }
  window.__uploading = true;
  // 只改按钮文字，不重建 DOM（重建会丢失 fileInput 的 change 监听，导致无法连续上传）
  const btn = $("#quickUploadBtn");
  const oldLabel = btn ? btn.innerHTML : "";
  if (btn) { btn.disabled = true; btn.innerHTML = `正在上传 ${files.length} 个文件…`; }
  const panel = $("#parsePanel");
  if (panel) { panel.style.display = ""; panel.innerHTML = `<h4 style="margin-bottom:8px">📤 上传与解析进度</h4><div style="color:var(--text-2);font-size:13px">正在上传文件…</div>`; }
  let claimId = null;
  try {
    const claim = await api.upload(`/api/projects/${projectId}/upload`, files);
    claimId = claim.id;
    toast(`已生成债权 ${claim.claim_no}，正在解析材料（扫描件需 OCR，可能需 1-2 分钟）…`);
    // 先显示文件清单（待解析）
    const d0 = await api.get(`/api/claims/${claimId}/detail`);
    updateParsePanel(d0.files);
    // 轮询债权级解析状态（done = 解析+字段提取全部完成，信息已自动同步台账）
    const d = await pollParse(claimId, (fl) => updateParsePanel(fl));
    updateParsePanel(d.files);
    const c = await api.get(`/api/claims/${claimId}`);
    toast(`解析完成，信息已自动同步到台账：${c.name ? "债权人「" + c.name + "」" : "未识别出名称，请在编辑中补录"}`);
    renderLedgerList();
    refreshLedgerStats();
  } catch (e) {
    toast(e.message, true);
    if (panel) panel.innerHTML = `<div style="color:var(--red)">解析异常：${esc(e.message)}</div>`;
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = oldLabel; }
    $("#fileInput").value = "";
    window.__uploading = false;
  }
}

async function pollParse(claimId, onUpdate, timeoutMs = 600000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const d = await api.get(`/api/claims/${claimId}/detail`);
    const files = d.files || [];
    if (onUpdate) onUpdate(files);
    // 债权级解析完成（parse_status=done）＝ 文本解析 + 字段提取全部完成
    const ps = (d.claim || {}).parse_status;
    if (ps === "done") return d;
    if (ps === "failed") throw new Error("解析失败，请检查文件是否损坏或联系管理员");
    await new Promise((r) => setTimeout(r, 3000));
  }
  throw new Error("解析超时，请稍后在详情中查看");
}

// ---------- 台账操作 ----------
function exportLedger() {
  window.open(`/api/export/ledger?project_id=${ledgerState.projectId}`, "_blank");
}
function downloadTemplate() {
  window.open(`/api/import/template?project_id=${ledgerState.projectId}`, "_blank");
}
function importLedger() {
  // 隐藏文件选择，选择 .xlsx 后上传导入
  let input = $("#importFileInput");
  if (!input) {
    input = document.createElement("input");
    input.type = "file";
    input.id = "importFileInput";
    input.accept = ".xlsx,.xlsm";
    input.style.display = "none";
    document.body.appendChild(input);
    input.addEventListener("change", (e) => {
      const f = e.target.files[0];
      if (!f) return;
      doImportLedger(f);
      input.value = "";
    });
  }
  input.click();
}
async function doImportLedger(file) {
  const { projectId } = ledgerState;
  const fd = new FormData();
  fd.append("file", file);
  const toastEl = document.createElement("div");
  toastEl.className = "toast";
  toastEl.textContent = "正在导入台账…";
  document.body.appendChild(toastEl);
  setTimeout(() => toastEl.remove(), 4000);
  try {
    const r = await api.req(`/api/import/ledger?project_id=${projectId}`, {
      method: "POST", body: fd,
    });
    let html = `<div style="margin-bottom:10px">${esc(r.message || "导入完成")}</div>`;
    if (r.mapped_columns && r.mapped_columns.length) {
      html += `<div class="audit-section"><h4>📋 表头列识别（用于核对是否错位）</h4>
        <div class="content" style="max-height:120px;overflow:auto">${esc(r.mapped_columns.join(" ｜ "))}</div></div>`;
    }
    if (r.errors && r.errors.length) {
      html += `<table class="tbl"><thead><tr><th>行</th><th>原因</th></tr></thead><tbody>
        ${r.errors.map((e) => `<tr><td>${e.row}</td><td>${esc(e.reason)}</td></tr>`).join("")}
      </tbody></table>`;
    }
    openModal(`${modalHead("导入结果")}
      <div class="modal-body">${html}
        <div style="margin-top:12px;color:var(--text-2);font-size:13px">
          提示：文件含「债权编号」且编号已存在时更新该条；否则自动分配新编号。导入后请人工核对并完成登记/复核。
        </div>
      </div>
      <div class="modal-foot"><button class="btn btn-primary" onclick="closeModal()">确定</button></div>`);
    renderLedgerList();
  } catch (e) {
    toast(e.message, true);
  }
}
function exportOpinions() {
  window.open(`/api/export/opinions?project_id=${ledgerState.projectId}`, "_blank");
}

// ---------- 在线申报（云端申报地址 + 云端拉取 + 一键导入台账） ----------
async function refreshOnlineBadge() {
  const badge = $("#ocBadge");
  const hint = $("#ocHint");
  try {
    const rows = await api.get(`/api/projects/${ledgerState.projectId}/online-claims`);
    const n = rows.filter((r) => r.status === "new").length;
    if (badge) {
      if (n > 0) { badge.style.display = ""; badge.textContent = n; }
      else { badge.style.display = "none"; }
    }
    if (hint) {
      hint.innerHTML = n
        ? `当前有 <b>${n}</b> 条待导入申报，点上方按钮拉取并导入台账`
        : "暂无待导入申报；点上方按钮可复制申报链接发给债权人";
    }
  } catch (e) {
    if (hint) hint.textContent = "云端未配置或暂时不可用";
  }
}

async function openOnlineClaims() {
  const pid = ledgerState.projectId;
  // 并行加载：云端配置 / 项目信息 / 在线申报列表
  const [cfg, project, rows] = await Promise.all([
    api.get("/api/cloud-sync/config").catch(() => ({})),
    api.get(`/api/projects/${pid}`).catch(() => ({})),
    api.get(`/api/projects/${pid}/online-claims`).catch(() => []),
  ]);
  const news = rows.filter((r) => r.status === "new");
  const dones = rows.filter((r) => r.status === "imported");

  // 项目云端申报地址（云端校验 project 项目码，须与云端 CLOUD_PROJECT_CODES 一致）
  const cloudBase = (cfg.cloud_url || "").replace(/\/+$/, "");
  const cloudCode = project.cloud_code || "";
  const cloudLink = cloudBase
    ? `${cloudBase}/?project=${encodeURIComponent(cloudCode || pid)}`
        + `${project.case_no ? `&case=${encodeURIComponent(project.case_no)}` : ""}`
        + `${project.debtor ? `&debtor=${encodeURIComponent(project.debtor)}` : ""}`
        + `${project.manager ? `&manager=${encodeURIComponent(project.manager)}` : ""}`
    : "";

  const rowsHtml = (list, showStatus) => list.map((r) => `
    <tr>
      <td>${esc(r.submit_no)}</td>
      <td>${esc(r.name || "—")}</td>
      <td>¥${fmtMoney(r.claim_amount)}</td>
      <td>${r.files.length}</td>
      <td>${esc(r.created_at || "").slice(0, 16)}</td>
      ${showStatus ? `<td>已导入 → <a class="link" onclick="openPreviewPage(${r.imported_claim_id})">查看导入的债权</a></td>` : ""}
    </tr>`).join("") || `<tr><td colspan="${showStatus ? 6 : 5}" class="empty">暂无记录</td></tr>`;

  openModal(`${modalHead("在线申报债权")}
    <div class="modal-body">
      <div class="audit-section" style="margin-bottom:12px">
        <h4>🔗 本项目云端申报地址（发给债权人填写并上传资料）</h4>
        ${cloudLink ? `
          <div style="display:flex;gap:8px;align-items:center">
            <input id="ocLink" readonly value="${esc(cloudLink)}" style="flex:1" onclick="this.select()">
            <button class="btn" onclick="copyOnlineLink()">📋 复制链接</button>
            <a class="btn" href="${esc(cloudLink)}" target="_blank">🖥 打开页面</a>
          </div>
          <div style="color:var(--text-2);font-size:12px;margin-top:6px">
            债权人通过该链接在云端申报，提交后下方「云端拉取」可拉取到本系统，再一键导入台账。
            ${cloudCode ? "" : '<span style="color:var(--amber)">⚠️ 该项目未填写「云端项目码」，链接暂用项目 ID 代替；请到项目管理处补充云端项目码（须与云端 CLOUD_PROJECT_CODES 一致）。</span>'}
          </div>` : `
          <div style="color:var(--amber);font-size:13px">⚠️ 尚未配置云端地址。请先在下方「云端配置」填写云端地址并保存。</div>`}
      </div>
      <div class="audit-section" style="margin-bottom:12px">
        <h4 style="margin-bottom:10px">☁️ 云端配置与拉取（阿里云接收服务）</h4>
        <div class="grid-2">
          <div class="field"><label>云端地址</label>
            <input id="csUrl" placeholder="http://8.130.44.159:8080" value="${esc(cfg.cloud_url || "")}"></div>
          <div class="field"><label>管理员令牌</label>
            <input id="csToken" type="password" placeholder="${cfg.token_set ? "已配置（留空保持不变）" : "填写云端 .env 中的 CLOUD_ADMIN_TOKEN"}" value=""></div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn" onclick="saveCloudConfig()">💾 保存配置</button>
          <button class="btn" onclick="testCloudConn()">🔌 测试连接</button>
          <button class="btn btn-primary" onclick="pullCloudClaims(false)">⬇ 拉取云端申报</button>
          <button class="btn btn-primary" onclick="pullCloudClaims(true)">⬇ 拉取并导入台账</button>
        </div>
        <div id="csResult" style="margin-top:12px;font-size:13px"></div>
      </div>
      <h4 style="margin-bottom:8px">📥 待导入申报（${news.length}）</h4>
      <table class="tbl">
        <thead><tr><th>流水号</th><th>债权人名称</th><th>申报总额</th><th>材料</th><th>提交时间</th></tr></thead>
        <tbody>${rowsHtml(news, false)}</tbody>
      </table>
      <div style="margin-top:14px">
        <button class="btn btn-primary" ${news.length ? "" : "disabled"} onclick="importOnlineClaims()">🚀 更新在线申报（一键导入 ${news.length} 条）</button>
      </div>
      <h4 style="margin:18px 0 8px">✅ 已导入（${dones.length}）</h4>
      <table class="tbl">
        <thead><tr><th>流水号</th><th>债权人名称</th><th>申报总额</th><th>材料</th><th>提交时间</th><th>状态</th></tr></thead>
        <tbody>${rowsHtml(dones, true)}</tbody>
      </table>
      <div style="color:var(--text-2);font-size:12px;margin-top:10px">
        数据流：云端申报页（阿里云）→ 此处拉取 → 在线申报表 → 「更新在线申报」导入台账（自动编号 / 材料入库 / OCR 解析 / 同名查重）。
      </div>
    </div>`, { wide: true });
}

function copyOnlineLink() {
  const el = $("#ocLink");
  if (!el) return;
  el.select();
  try { document.execCommand("copy"); toast("链接已复制"); }
  catch (e) { toast("复制失败，请手动选择复制", true); }
}

async function importOnlineClaims() {
  const pid = ledgerState.projectId;
  try {
    const r = await api.post(`/api/projects/${pid}/online-claims/import`, { force: false });
    finishImport(r);
  } catch (e) {
    // 同名查重提示（409：detail 为 {"duplicates":[...],"msg":"..."} JSON）
    let dupMsg = null;
    try { const j = JSON.parse(e.message); if (j.msg) dupMsg = `${j.msg}：${(j.duplicates || []).join("、")}`; } catch (err) {}
    if (dupMsg) {
      if (confirm(`${dupMsg}。\n\n点「确定」继续导入（同名债权将并存），点「取消」返回核对。`)) {
        try {
          const r = await api.post(`/api/projects/${pid}/online-claims/import`, { force: true });
          finishImport(r);
        } catch (e2) { toast(e2.message, true); }
      }
    } else {
      toast(e.message, true);
    }
  }
}

function finishImport(r) {
  closeModal();
  const imported = (r.imported || []).length;
  const failed = (r.failed || []).length;
  let msg = `已导入 ${imported} 笔在线申报到台账`;
  if (failed) msg += `，失败 ${failed} 笔`;
  toast(msg, failed > 0);
  refreshOnlineBadge();
  renderLedgerList();
}

// ---------- 云端申报同步（阿里云接收暂存 → 本地拉取；UI 已并入「在线申报」弹窗） ----------
function csCollect() {
  // 拉取目标 = 当前台账项目（合并后无需单独填写项目 ID）
  return {
    cloud_url: $("#csUrl").value.trim(),
    admin_token: $("#csToken").value.trim(),
    project_id: ledgerState.projectId || 0,
  };
}
function csMsg(html, isErr) {
  const box = $("#csResult");
  if (box) box.innerHTML = `<div style="color:${isErr ? "var(--danger)" : "var(--ok)"}">${html}</div>`;
}
async function saveCloudConfig() {
  const body = csCollect();
  if (!body.cloud_url) return toast("请填写云端地址", true);
  const r = await api.put("/api/cloud-sync/config", body).catch((e) => { toast(e.message, true); return null; });
  if (r) toast("配置已保存");
}
async function testCloudConn() {
  const r = await api.post("/api/cloud-sync/test", csCollect()).catch((e) => { toast(e.message, true); return null; });
  if (!r) return;
  if (r.ok) csMsg(`✅ 连接正常，云端待处理申报 <b>${r.pending}</b> 条`);
  else csMsg(`❌ ${esc(r.error || "连接失败")}`, true);
}
async function pullCloudClaims(doImport) {
  const body = csCollect();
  if (!body.project_id) return toast("请填写项目 ID", true);
  const path = doImport ? "/api/cloud-sync/pull-and-import" : "/api/cloud-sync/pull";
  csMsg("正在拉取…");
  try {
    const r = await api.post(path, body);
    const pull = r.pull || r;
    const n = (pull.pulled || []).length;
    let html = `✅ 拉取完成：新增 <b>${n}</b> 条，跳过重复 <b>${pull.skipped || 0}</b> 条`;
    if (n) html += `<div style="font-size:12px;color:var(--text-2);margin-top:6px">${(pull.pulled || []).map((x) => `${esc(x.submit_no)} ${esc(x.name)} ¥${fmtMoney(x.amount)}`).join("<br>")}</div>`;
    if ((pull.errors || []).length) html += `<div style="color:var(--danger);margin-top:6px">失败 ${pull.errors.length} 条：${esc(pull.errors.map((e) => `${e.submit_no}:${e.error}`).join("；"))}</div>`;
    if (doImport && r.import) {
      html += `<div style="margin-top:6px">导入台账：成功 ${(r.import.imported || []).length} 条，失败 ${(r.import.failed || []).length} 条</div>`;
      refreshOnlineBadge();
      renderLedgerList();
    }
    csMsg(html);
    if (n) toast(`已拉取 ${n} 条云端申报`);
  } catch (e) {
    // 拉取并导入时的同名查重（409：detail 为 {"duplicates":[...],"msg":"..."} JSON）
    let dupMsg = null;
    try { const j = JSON.parse(e.message); if (j.msg) dupMsg = j.msg; } catch (err) {}
    if (dupMsg) {
      if (confirm(`${dupMsg}。\n\n点「确定」强制导入（同名债权并存），点「取消」返回。`)) {
        const r2 = await api.post(path, { ...body, force: true }).catch((e2) => { toast(e2.message, true); return null; });
        if (r2) {
          csMsg("✅ 已强制导入，详见台账");
          refreshOnlineBadge();
          renderLedgerList();
        }
      }
    } else {
      csMsg(`❌ ${esc(e.message)}`, true);
    }
  }
}

async function registerClaim(id) {
  try {
    await api.post(`/api/claims/${id}/register`);
    toast("已登记完成，下一步可以点「AI 审查」");
    renderLedgerList();
    refreshLedgerStats();
  } catch (e) { toast(e.message, true); }
}
async function deleteClaim(id) {
  if (!confirm("确认删除该债权记录及其材料文件？")) return;
  try {
    await api.del(`/api/claims/${id}`);
    toast("已删除");
    renderLedgerList();
    refreshLedgerStats();
  } catch (e) { toast(e.message, true); }
}
/* 只刷新统计卡片与分段按钮上的数字（登记/删除/审查后保持顶部计数准确） */
async function refreshLedgerStats() {
  const { projectId } = ledgerState;
  if (!projectId || !$("#ledgerBody")) return;
  try {
    const s = await api.get(`/api/projects/${projectId}/stats`);
    const nums = $$(".stat-card.clickable .num");
    if (nums.length >= 4) {
      nums[0].textContent = s.total; nums[1].textContent = s.pending;
      nums[2].textContent = s.registered; nums[3].textContent = s.reviewed;
    }
    const segs = $$("#statusSeg .seg-btn b");
    if (segs.length >= 4) {
      segs[0].textContent = s.total; segs[1].textContent = s.pending;
      segs[2].textContent = s.registered; segs[3].textContent = s.reviewed;
    }
    const cards = $$(".stats .stat-card");
    if (cards.length >= 6) {
      cards[4].innerHTML = statNum(s.sum_claimed, "申报总额");
      cards[5].innerHTML = statNum(s.sum_audited, "审核总额");
    }
  } catch (e) { /* 统计刷新失败不影响主流程 */ }
}

// ---------- 材料预览（独立页面，不阻塞主工具） ----------
function openPreviewPage(claimId) {
  window.open(`/preview.html?claim_id=${claimId}`, "_blank");
}

// ---------- 弹窗：材料预览（保留备用） ----------
async function openPreview(claimId) {
  const d = await api.get(`/api/claims/${claimId}/detail`);
  const c = d.claim;
  openModal(`${modalHead(`${c.claim_no} · ${c.name || "未命名"}`)}
    <div class="modal-body">
      <div class="preview-tabs" id="pvTabs"></div>
      <div id="pvFrame"></div>
      <div class="audit-section" style="margin-top:14px"><h4>📄 解析文本</h4>
        <div class="content" id="pvText" style="max-height:160px;overflow:auto">${esc(d.files.map((f) => f.ocr_text).join("\n---\n") || "（无解析文本：可能是图片扫描件，简单版暂不 OCR）")}</div>
      </div>
    </div>`, { wide: true });
  const tabs = $("#pvTabs"), frame = $("#pvFrame");
  if (!d.files.length) {
    tabs.innerHTML = `<span style="color:var(--text-2)">无材料文件</span>`;
    return;
  }
  tabs.innerHTML = d.files.map((f, i) =>
    `<button class="btn btn-sm ${i === 0 ? "btn-primary" : ""}" data-i="${i}" onclick="switchPreviewTab(${i})">${esc(f.filename)} ${parseStatusBadge(f.parse_status)}</button>
     <a class="btn btn-sm" href="/api/files/${f.id}/download" target="_blank">⬇ 下载</a>`).join("");
  window.__pvFiles = d.files;
  switchPreviewTab(0);
}
function switchPreviewTab(i) {
  const f = window.__pvFiles[i];
  $$("#pvTabs .btn[data-i]").forEach((b) => b.classList.remove("btn-primary"));
  const btn = $(`#pvTabs .btn[data-i="${i}"]`);
  if (btn) btn.classList.add("btn-primary");
  const frame = $("#pvFrame");
  const imgExt = ["png", "jpg", "jpeg", "bmp", "gif", "webp"];
  if (f.file_type === "pdf") {
    frame.innerHTML = `<iframe class="preview-frame" src="/api/files/${f.id}/preview"></iframe>`;
  } else if (imgExt.includes((f.filename.split(".").pop() || "").toLowerCase())) {
    frame.innerHTML = `<img src="/api/files/${f.id}/preview" style="max-width:100%;max-height:60vh;border-radius:8px">`;
  } else if (f.file_type === "text") {
    frame.innerHTML = `<div class="content" style="max-height:60vh;overflow:auto">${esc(f.ocr_text || "（空）")}</div>`;
  } else {
    frame.innerHTML = `<div class="empty"><div class="icon">📄</div><p>该文件类型不支持在线预览</p>
      <p><a class="link" href="/api/files/${f.id}/download">点击下载查看 →</a></p></div>`;
  }
}

// ---------- 弹窗：编辑台账 ----------
const FIELD_GROUPS = [
  ["债权人基本信息", [
    ["name", "债权人名称 *"], ["credit_code", "统一社会信用代码/身份证号码"], ["legal_rep", "法定代表人/负责人"],
    ["contact_info", "联系方式"], ["address", "联系地址"],
  ]],
  ["代理人信息", [
    ["agent_name", "代理人姓名"], ["agent_id_no", "代理人身份证号"], ["agent_contact", "代理人联系方式"], ["agent_address", "代理人地址"],
  ]],
  ["收款账户", [
    ["account_name", "开户名称"], ["bank_name", "开户行"], ["account_no", "账号"],
  ]],
  ["债权要素", [
    ["claim_category", "债权种类", ["金融", "购销", "借贷", "工程款", "职工", "税收", "其他"]],
    ["litigation_status", "涉诉涉执情况", ["是", "否"]],
    ["claim_nature", "申报债权性质", NATURE_OPTIONS],
    ["claim_date", "申报债权时间"], ["claim_type", "债权类型"], ["debt_nature", "确认债权性质", NATURE_OPTIONS],
  ]],
  ["申报金额", [
    ["principal", "申报本金"], ["interest", "申报利息"], ["others", "申报其他"], ["claim_amount", "申报总额"],
  ]],
  ["审核金额", [
    ["audited_principal", "审核本金"], ["audited_interest", "审核利息"], ["audited_others", "审核其他"], ["audited_amount", "审核总额"],
  ]],
];

const MONEY_KEYS = ["principal", "interest", "others", "claim_amount",
                    "audited_principal", "audited_interest", "audited_others",
                    "audited_amount"];

async function openEditClaim(claimId) {
  const d = await api.get(`/api/claims/${claimId}/detail`);
  const c = d.claim;
  // 总额自动汇总：申报总额 = 本金+利息+其他；审核总额 = 审核本金+利息+其他
  const sum3 = (p, i, o) => Math.round((Number(c[p] || 0) + Number(c[i] || 0) + Number(c[o] || 0)) * 100) / 100;
  const claimSum = sum3("principal", "interest", "others");
  const audSum = sum3("audited_principal", "audited_interest", "audited_others");
  let html = "";
  for (const [gname, fields] of FIELD_GROUPS) {
    html += `<h4 style="margin:14px 0 8px;color:var(--primary)">${gname}</h4><div class="grid-2">`;
    for (const [key, label, options] of fields) {
      const val = c[key] ?? "";
      let input;
      if (options) {
        input = `<select id="ef_${key}"><option value="">（未填写）</option>${options.map((o) => `<option ${String(val) === o ? "selected" : ""}>${o}</option>`).join("")}</select>`;
      } else if (key === "claim_amount" || key === "audited_amount") {
        // 总额：只读，随分项自动汇总
        const v = key === "claim_amount" ? claimSum : audSum;
        input = `<input id="ef_${key}" type="number" step="0.01" value="${v || ""}" readonly
                   style="background:#f6f8fb;cursor:not-allowed">
                 <div class="hint">自动汇总，无需填写${v ? "" : "（分项填写后自动生成）"}</div>`;
      } else if (MONEY_KEYS.includes(key)) {
        input = `<input id="ef_${key}" type="number" step="0.01" value="${val || ""}" placeholder="0.00">`;
      } else {
        input = `<input id="ef_${key}" value="${esc(val)}">`;
      }
      html += `<div class="field"><label>${label}</label>${input}</div>`;
    }
    html += `</div>`;
  }
  html += `<div class="field"><label>担保情况备注</label><textarea id="ef_guarantee_notes" rows="2">${esc(c.guarantee_notes || "")}</textarea></div>`;
  // 分项和与原总额不一致时给出提示（保存后会按分项重新汇总）
  let diffTip = "";
  if (Math.abs(claimSum - Number(c.claim_amount || 0)) > 0.01) {
    diffTip += `<div style="font-size:12.5px;color:var(--amber);margin-top:8px">
      ⚠ 申报总额原为 ${fmtMoney(c.claim_amount)} 元，与分项汇总（${fmtMoney(claimSum)} 元）不一致，保存后将按分项汇总。</div>`;
  }
  if (Math.abs(audSum - Number(c.audited_amount || 0)) > 0.01) {
    diffTip += `<div style="font-size:12.5px;color:var(--amber);margin-top:4px">
      ⚠ 审核总额原为 ${fmtMoney(c.audited_amount)} 元，与分项汇总（${fmtMoney(audSum)} 元）不一致，保存后将按分项汇总。</div>`;
  }
  const autoRegTip = (c.status || "pending") === "pending"
    ? `<div style="font-size:12.5px;color:var(--primary);margin-top:8px">💡 保存后该债权将自动登记为「已登记」（债权人名称为空时仍保持待登记）。</div>` : "";

  openModal(`${modalHead(`初审/编辑 · ${c.claim_no}`)}
    <div class="modal-body">${html}${diffTip}${autoRegTip}</div>
    <div class="modal-foot">
      <button class="btn" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="saveEditClaim(${claimId}, '${c.status || "pending"}')">保存</button>
    </div>`, { wide: true });

  // 分项输入 → 实时重算总额
  const recalc = (p, i, o, target) => {
    const n = (id) => {
      const el = $(`#ef_${id}`);
      if (!el) return 0;
      const v = parseFloat(el.value);
      return isNaN(v) ? 0 : v;
    };
    const sum = Math.round((n(p) + n(i) + n(o)) * 100) / 100;
    const t = $(`#ef_${target}`);
    if (t) t.value = sum ? String(sum) : "";
  };
  [["principal", "interest", "others", "claim_amount"],
   ["audited_principal", "audited_interest", "audited_others", "audited_amount"]]
    .forEach(([p, i, o, target]) => {
      [p, i, o].forEach((k) => {
        const el = $(`#ef_${k}`);
        if (el) el.addEventListener("input", () => recalc(p, i, o, target));
      });
    });
}
async function saveEditClaim(claimId, prevStatus) {
  const body = {};
  for (const [, fields] of FIELD_GROUPS) {
    for (const [key] of fields) {
      const el = $(`#ef_${key}`);
      if (!el) continue;
      if (MONEY_KEYS.includes(key)) {
        body[key] = el.value === "" ? 0 : Number(el.value);
      } else body[key] = el.value;
    }
  }
  body.guarantee_notes = $("#ef_guarantee_notes").value;
  if (!String(body.name || "").trim()) {
    toast("债权人名称为必填项；不填写将仍保持「待登记」", true);
  }
  try {
    const updated = await api.put(`/api/claims/${claimId}`, body);
    closeModal();
    if (updated && updated.status === "registered" && prevStatus !== "registered") {
      toast("已保存并自动登记，状态更新为「已登记」，下一步可点「AI 审查」");
    } else {
      toast("已保存");
    }
    renderLedgerList();
    refreshLedgerStats();
  } catch (e) { toast(e.message, true); }
}

// ---------- 视图：审查工作台 ----------
let auditPollTimer = null;

// 审查工作台列表筛选状态与数据（前端筛选，不重复请求）
let auditListState = { projectId: null, keyword: "", status: "", aiStatus: "",
                       result: "", nature: "" };
let auditListData = { claims: [], audits: [] };

// 从审查记录解析结论（confirmed/partial/rejected）
function auditResultOf(audit) {
  if (!audit || audit.ai_status !== "done" || !audit.ai_opinion) return "";
  try {
    return JSON.parse(audit.ai_opinion).review_result || "partial";
  } catch (e) { return "partial"; }
}

function resultBadge(rr) {
  const m = { confirmed: ["badge-done", "认可"],
              partial: ["badge-running", "部分认可"],
              rejected: ["badge-failed", "不认可"] };
  const it = m[rr];
  return it ? `<span class="badge ${it[0]}">${it[1]}</span>` : `<span class="badge badge-none">—</span>`;
}

function resetAuditListFilter() {
  auditListState.keyword = ""; auditListState.status = "";
  auditListState.aiStatus = ""; auditListState.result = "";
  auditListState.nature = "";
  // 恢复控件并重绘
  if ($("#alKw")) $("#alKw").value = "";
  if ($("#alSt")) $("#alSt").value = "";
  if ($("#alAi")) $("#alAi").value = "";
  if ($("#alRes")) $("#alRes").value = "";
  if ($("#alNat")) $("#alNat").value = "";
  renderAuditRows();
}

function renderAuditRows() {
  const body = $("#auditListBody");
  if (!body) return;
  const { keyword: kw, status: st, aiStatus, result, nature } = auditListState;
  const claims = auditListData.claims || [];
  const audits = auditListData.audits || [];
  const NATURE_NORM = { "工程债权": "工程款优先权", "购房优先权": "购房者优先权",
                        "税收": "税收债权", "税款债权": "税收债权", "职工": "职工债权" };
  const rows = [];
  claims.forEach((c, i) => {
    const a = audits[i];
    if (kw && !((c.name || "").includes(kw) || (c.claim_no || "").includes(kw)
                || (c.credit_code || "").includes(kw))) return;
    if (st && c.status !== st) return;
    if (aiStatus && (a ? (a.ai_status || "none") : "none") !== aiStatus) return;
    const rr = auditResultOf(a);
    if (result && rr !== result) return;
    if (nature) {
      const raw = String(c.claim_nature || "").trim();
      if ((NATURE_NORM[raw] || raw) !== nature) return;
    }
    rows.push({ c, a, rr });
  });
  const cnt = $("#alCount");
  if (cnt) cnt.textContent = `共 ${rows.length} / ${claims.length} 条`;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="9" class="empty">无匹配记录</td></tr>`;
    return;
  }
  body.innerHTML = rows.map(({ c, a, rr }) => `
    <tr>
      <td>${esc(c.claim_no)}</td>
      <td>${esc(c.name || "（未识别）")}</td>
      <td>${esc(c.claim_nature || "—")}</td>
      <td class="num">${fmtMoney(c.claim_amount)}</td>
      <td class="num">${fmtMoney(c.audited_amount)}</td>
      <td>${statusBadge(c.status)}</td>
      <td>${aiBadge(a ? a.ai_status : "none")}</td>
      <td>${resultBadge(rr)}</td>
      <td><button class="btn btn-sm btn-primary" onclick="location.hash='#/audit?claim=${c.id}'">进入审查 →</button></td>
    </tr>`).join("");
}

async function renderAudit(params, app) {
  const claimId = Number(params.claim);
  if (!claimId) {
    // 无指定债权：默认在当前项目内选择（没有当前项目则先选项目）
    let projectId = params.project ? Number(params.project) : null;
    if (!projectId) {
      const cur = getCurrentProject();
      if (cur && cur.id) projectId = cur.id;
    }
    if (!projectId) {
      renderProjectPicker(app, "审查工作台", "选择一个项目，进入后默认在该项目内进行债权审查");
      return;
    }
    const project = await api.get(`/api/projects/${projectId}`);
    setCurrentProject(project);
    const claims = await api.get(`/api/claims?project_id=${projectId}`);
    const audits = await Promise.all(claims.map((c) =>
      api.get(`/api/claims/${c.id}/audit`).catch(() => null)));
    // ---- 审查统计 ----
    const st = { done: { n: 0, amt: 0 }, confirmed: { n: 0, amt: 0 },
                 partial: { n: 0, amt: 0 }, rejected: { n: 0, amt: 0 } };
    claims.forEach((c, i) => {
      const a = audits[i];
      if (!a || a.ai_status !== "done" || !a.ai_opinion) return;
      let rr = "partial";
      try { rr = (JSON.parse(a.ai_opinion).review_result) || "partial"; } catch (e) {}
      const amt = Number(c.audited_amount || 0);
      st.done.n += 1; st.done.amt += amt;
      if (rr === "confirmed") { st.confirmed.n += 1; st.confirmed.amt += amt; }
      else if (rr === "rejected") { st.rejected.n += 1; st.rejected.amt += amt; }
      else { st.partial.n += 1; st.partial.amt += amt; }
    });
    const doneN = st.done.n || 1;
    const bars = [
      ["认可", st.confirmed.n, st.confirmed.amt, "bg-ok"],
      ["部分认可", st.partial.n, st.partial.amt, "bg-part"],
      ["不认可", st.rejected.n, st.rejected.amt, "bg-no"],
    ].map(([label, n, amt, cls]) =>
      `<div class="bar-row"><span class="bar-label">${label}</span>
        <div class="bar-track"><div class="bar-fill ${cls}" style="width:${Math.round(n / doneN * 100)}%"></div></div>
        <span class="bar-val" title="¥${fmtMoney(amt)}">${n} 笔 / ${fmtMoneySmart(amt)}</span></div>`).join("");
    app.innerHTML = `
      ${ledgerTabsHtml(projectId, "audit")}
      ${acceptDateWarningHtml(project)}
      <div class="page-head">
        <div><div class="page-title">债权审查</div>
        <div class="page-sub">${esc(project.name)} · 选一笔债权进入审查工作台；本页与「债权台账」可直接用上方 Tab 切换</div></div>
        <a class="btn" href="#/ledger?project=${projectId}">← 返回台账</a>
      </div>
      <div class="audit-stats">
        <div class="stat-card"><div class="num">${st.done.n}</div><div class="label">已审查笔数</div></div>
        <div class="stat-card">${statNum(st.done.amt, "已审查金额（审核确认）")}</div>
        <div class="stat-card sc-ok"><div class="num">${st.confirmed.n}</div><div class="label">认可笔数</div></div>
        <div class="stat-card sc-ok">${statNum(st.confirmed.amt, "认可金额")}</div>
        <div class="stat-card sc-part"><div class="num">${st.partial.n}</div><div class="label">部分认可笔数</div></div>
        <div class="stat-card sc-part">${statNum(st.partial.amt, "部分认可金额")}</div>
        <div class="stat-card sc-no"><div class="num">${st.rejected.n}</div><div class="label">不认可笔数</div></div>
        <div class="stat-card sc-no">${statNum(st.rejected.amt, "不认可金额")}</div>
      </div>
      <div class="card chart-card" style="margin-bottom:16px">
        <h3 style="margin-bottom:6px">📊 审查结论分布（按已审查笔数占比）</h3>
        ${st.done.n ? bars : `<div style="color:var(--text-2);font-size:13px">暂无已审查债权，请先对债权执行 AI 审查</div>`}
      </div>
      <div class="card">
        ${claims.length ? `
        <div class="filter-bar">
          <input id="alKw" placeholder="搜索 名称/编号/信用代码" style="min-width:220px"
            value="${esc(auditListState.keyword)}" oninput="auditListState.keyword=this.value;renderAuditRows()">
          <select id="alSt" onchange="auditListState.status=this.value;renderAuditRows()">
            <option value="">全部登记状态</option>
            <option value="pending" ${auditListState.status === "pending" ? "selected" : ""}>待登记</option>
            <option value="registered" ${auditListState.status === "registered" ? "selected" : ""}>已登记</option>
            <option value="reviewed" ${auditListState.status === "reviewed" ? "selected" : ""}>已复核</option>
          </select>
          <select id="alAi" onchange="auditListState.aiStatus=this.value;renderAuditRows()">
            <option value="">全部审查状态</option>
            <option value="none" ${auditListState.aiStatus === "none" ? "selected" : ""}>未审查</option>
            <option value="running" ${auditListState.aiStatus === "running" ? "selected" : ""}>审查中</option>
            <option value="done" ${auditListState.aiStatus === "done" ? "selected" : ""}>已审查</option>
            <option value="failed" ${auditListState.aiStatus === "failed" ? "selected" : ""}>审查失败</option>
          </select>
          <select id="alRes" onchange="auditListState.result=this.value;renderAuditRows()">
            <option value="">全部审查结论</option>
            <option value="confirmed" ${auditListState.result === "confirmed" ? "selected" : ""}>认可</option>
            <option value="partial" ${auditListState.result === "partial" ? "selected" : ""}>部分认可</option>
            <option value="rejected" ${auditListState.result === "rejected" ? "selected" : ""}>不认可</option>
          </select>
          <select id="alNat" onchange="auditListState.nature=this.value;renderAuditRows()">
            <option value="">全部债权性质</option>
            ${NATURE_OPTIONS.map((n) => `<option value="${n}" ${auditListState.nature === n ? "selected" : ""}>${n}</option>`).join("")}
          </select>
          <button class="btn btn-sm" onclick="resetAuditListFilter()">↺ 重置筛选</button>
          <span id="alCount" style="color:var(--text-2);font-size:12px"></span>
        </div>
        <table class="tbl"><thead><tr>
          <th>债权编号</th><th>债权人名称</th><th>债权性质</th><th>申报总额</th><th>审核总额</th>
          <th>状态</th><th>AI审查</th><th>审查结论</th><th></th>
        </tr></thead><tbody id="auditListBody"></tbody></table>`
        : `<div class="empty"><div class="icon">📂</div><p>该项目暂无债权，<a class="link" href="#/ledger?project=${projectId}">前往台账上传申报材料 →</a></p></div>`}
      </div>`;

    // 保存数据供筛选重绘
    auditListData.claims = claims;
    auditListData.audits = audits;
    auditListState.projectId = projectId;
    renderAuditRows();
    return;
  }
  const d = await api.get(`/api/claims/${claimId}/detail`);
  const c = d.claim, audit = d.audit;
  const project = await api.get(`/api/projects/${c.project_id}`);
  setCurrentProject(project); // 记住当前项目

  const ai = audit ? JSON.parse(audit.ai_opinion || "null") : null;
  const suggested = ai && ai.suggested_principal !== undefined
    ? { principal: ai.suggested_principal || 0, interest: ai.suggested_interest || 0, others: ai.suggested_others || 0 }
    : null;

  app.innerHTML = `
    ${ledgerTabsHtml(c.project_id, "audit")}
    ${acceptDateWarningHtml(project)}
    <div class="page-head">
      <div><div class="page-title">债权审查工作台</div>
      <div class="page-sub"><a class="link" href="#/ledger?project=${c.project_id}">← 返回台账</a>　${esc(project.name)}</div></div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" onclick="startAudit(${claimId})" id="btnAiAudit">🤖 AI 审查</button>
        <button class="btn" onclick="openManualAudit(${claimId})">✍️ 人工复核</button>
        <button class="btn" onclick="openOpinionEditor(${claimId})">📝 预览/编辑意见书</button>
        <button class="btn" onclick="window.open('/api/export/opinion/${claimId}','_blank')">📄 导出意见书</button>
      </div>
    </div>
    <div class="stats">
      <div class="stat-card"><div class="num">${esc(c.claim_no)}</div><div class="label">债权编号</div></div>
      <div class="stat-card"><div class="num" style="font-size:16px">${esc(c.name || "（未识别）")}</div><div class="label">债权人</div></div>
      <div class="stat-card">${statNum(c.claim_amount, "申报总额")}</div>
      <div class="stat-card">${statNum(c.audited_amount, "审核总额")}</div>
      <div class="stat-card"><div class="num">${statusBadge(c.status)}</div><div class="label">流程状态</div></div>
    </div>
    <div class="grid-2">
      <div class="card" style="align-self:start">
        <h3 style="margin-bottom:10px">📋 债权信息</h3>
        <table class="tbl">
          <tr><th style="width:130px">债权人名称</th><td>${esc(c.name || "—")}</td></tr>
          <tr><th>信用代码/身份证</th><td>${esc(c.credit_code || "—")}</td></tr>
          <tr><th>法定代表人</th><td>${esc(c.legal_rep || "—")}</td></tr>
          <tr><th>联系方式</th><td>${esc(c.contact_info || "—")}</td></tr>
          <tr><th>地址</th><td>${esc(c.address || "—")}</td></tr>
          <tr><th>代理人</th><td>${esc(c.agent_name || "—")}</td></tr>
          <tr><th>债权种类</th><td>${esc(c.claim_category || "—")}</td></tr>
          <tr><th>涉诉涉执</th><td>${esc(c.litigation_status || "—")}</td></tr>
          <tr><th>申报性质</th><td>${esc(c.claim_nature || "—")}</td></tr>
          <tr><th>申报时间</th><td>${esc(c.claim_date || "—")}</td></tr>
          <tr><th>申报本金</th><td class="num">${fmtMoney(c.principal)}</td></tr>
          <tr><th>申报利息</th><td class="num">${fmtMoney(c.interest)}</td></tr>
          <tr><th>申报其他</th><td class="num">${fmtMoney(c.others)}</td></tr>
          <tr><th>担保备注</th><td>${esc(c.guarantee_notes || "—")}</td></tr>
          <tr><th>台账数据</th><td>${c.verified_at
            ? `<span class="badge badge-done">已人工确认</span>
               <span style="font-size:12px;color:var(--text-2);margin-left:6px">${esc(String(c.verified_at).slice(0, 16).replace("T", " "))}　AI 审查以此为准，材料仅作核验</span>`
            : `<span class="badge badge-pending">系统解析预填</span>
               <span style="font-size:12px;color:var(--text-2);margin-left:6px">AI 审查以材料原文为准，建议先「初审 / 编辑」核对</span>`}</td></tr>
        </table>
        <div style="margin-top:10px">
          ${d.files.map((f) => `<div class="file-item"><span>📎</span><span class="fname">${esc(f.filename)}</span>${originBadge(f.origin)}
            <a class="btn btn-sm" href="/api/files/${f.id}/preview" target="_blank">预览</a>
            <a class="btn btn-sm" href="/api/files/${f.id}/download">下载</a></div>`).join("") || "<div style='color:var(--text-2)'>（无材料）</div>"}
          <button class="btn btn-sm" style="margin-top:8px" onclick="openSupplement(${claimId})">📎 补充材料</button>
        </div>
      </div>
      <div>
        <div class="card" id="aiPanel">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
            <h3>🤖 AI 审查意见 <span id="aiStatus">${aiBadge(audit ? audit.ai_status : "none")}</span></h3>
            ${audit && audit.prompt_version ? `<span style="font-size:11.5px;color:var(--text-2)"
               title="${esc((audit.injected_case_info || "案件信息未记录") + "\n提示词版本：" + audit.prompt_version + "；注入标准：" + (audit.injected_standards || "无"))}">
               提示词 ${esc(audit.prompt_version)}${audit.injected_standards ? ` · 标准：${esc(audit.injected_standards)}` : " · 未命中类型化标准"}${(ai && (ai.standard_refs || []).length) ? ` · 引用：${esc((ai.standard_refs || []).join("、"))}` : ""}</span>` : ""}
          </div>
          <div id="aiContent">${
            ai ? renderAIResult(ai, audit)
              : (audit && audit.ai_status === "failed"
                 ? `<div class="empty" style="padding:24px"><div class="icon">⚠️</div>
                    <p><b>AI 审查失败</b></p>
                    <p style="color:var(--red);font-size:13px;margin-top:6px">${esc(audit.ai_error || "未知错误")}</p>
                    <p style="font-size:13px;margin-top:10px">请到右上角「⚙️ AI 设置」检查模型配置（接口地址 / Key / 模型名），或重新点击「AI 审查」。</p></div>`
                 : (audit && audit.ai_status === "running"
                    ? `<div class="empty" style="padding:24px"><div class="icon">⏳</div><p>AI 审查进行中，请稍候…</p></div>`
                    : `<div class="empty" style="padding:24px"><div class="icon">🤖</div><p>尚未执行 AI 审查<br>点击右上角「AI 审查」开始</p></div>`))
          }</div>
        </div>
        <div class="card" id="manualPanel" style="margin-top:16px">
          <h3 style="margin-bottom:10px">✍️ 人工复核 ${audit && audit.manual_status === "done" ? `<span class="badge badge-done">已完成</span>` : `<span class="badge badge-pending">未完成</span>`}</h3>
          ${audit && audit.manual_status === "done" ? `
            <div class="audit-section"><div class="content">审查结论：<b>${esc(audit.audit_conclusion || "")}</b>\n\n${esc(audit.manual_opinion || "")}\n\n审查人：${esc(audit.auditor || "")}　时间：${audit.audited_at ? esc(audit.audited_at.slice(0, 16).replace("T", " ")) : ""}</div></div>
            <button class="btn" onclick="openManualAudit(${claimId})">修改复核意见</button>` : `
            <div class="empty" style="padding:20px"><p>人工复核未完成，点击右上角「人工复核」填写审核意见与金额</p></div>`}
        </div>
      </div>
    </div>`;

  if (audit && audit.ai_status === "running") startPolling(claimId);
}

function renderAIResult(ai, audit) {
  const concl = ai.conclusion || "";
  const reviewResult = ai.review_result || "";
  const rrBadge = reviewResult === "confirmed" ? "认可" :
                  reviewResult === "rejected" ? "不认可" :
                  reviewResult === "partial" ? "暂缓认定" : "";
  const process = Array.isArray(ai.review_process) ? ai.review_process : [];
  const legal = Array.isArray(ai.legal_basis) ? ai.legal_basis : [];
  const materialEv = Array.isArray(ai.material_evidence) ? ai.material_evidence : [];
  return `
    <div style="margin-bottom:12px"><span class="audit-conclusion concl-${esc(concl)}">审查结论：${esc(concl)}</span>
      ${rrBadge ? `<span class="badge ${reviewResult === "confirmed" ? "badge-done" : reviewResult === "rejected" ? "badge-failed" : "badge-running"}" style="margin-left:8px">${rrBadge}</span>` : ""}
      ${ai.summary ? `<div style="margin-top:8px;color:var(--text-2)">${esc(ai.summary)}</div>` : ""}</div>
    ${materialEv.length ? `<div class="audit-section"><h4>📎 材料关键证据</h4><div class="content">${materialEv.map((e) => `<div class="risk-item">• ${esc(e)}</div>`).join("")}</div></div>` : ""}
    ${process.length ? `<div class="audit-section"><h4>🔍 审查过程（决策树逐级）</h4><div class="content">${process.map((s) =>
      `<div class="risk-item" style="margin-top:2px"><b>第${esc(s.level || "?")}级【${esc(s.name || "")}】${esc(s.result || "")}</b>：${esc(s.detail || "")}</div>`
    ).join("")}</div></div>` : ""}
    <div class="audit-section"><h4>材料与信息核查</h4><div class="content">${esc(ai.info_check || "")}</div></div>
    <div class="audit-section"><h4>债权真实性</h4><div class="content">${esc(ai.authenticity || "")}</div></div>
    <div class="audit-section"><h4>债权合法性</h4><div class="content">${esc(ai.legality || "")}</div></div>
    <div class="audit-section"><h4>金额审查与核减建议</h4><div class="content">${esc(ai.amount_review || "")}
      ${ai.suggested_principal !== undefined ? `\n建议审核：本金 ¥${fmtMoney(ai.suggested_principal)}，利息 ¥${fmtMoney(ai.suggested_interest)}，其他 ¥${fmtMoney(ai.suggested_others)}` : ""}</div></div>
    <div class="audit-section"><h4>债权性质与清偿顺序</h4><div class="content">${esc(ai.nature_review || "")}</div></div>
    ${legal.length ? `<div class="audit-section"><h4>📚 法律依据</h4><div class="content">${legal.map((b) => `<div class="risk-item">• ${esc(b)}</div>`).join("")}</div></div>` : ""}
    <div class="audit-section"><h4>风险提示</h4><div class="content">${(ai.risks || []).map((r) => `<div class="risk-item">• ${esc(r)}</div>`).join("") || "（无）"}</div></div>
    ${audit && audit.ai_error ? `<div class="audit-section"><h4 style="color:var(--red)">错误</h4><div class="content" style="color:var(--red)">${esc(audit.ai_error)}</div></div>` : ""}
    ${audit && audit.ai_model ? `<div style="color:var(--text-2);font-size:12px">模型：${esc(audit.ai_model)}</div>` : ""}`;
}

// 恢复 AI 审查按钮状态（所有退出路径都必须调用，避免界面卡在"审查中"）
function restoreAuditBtn() {
  const btn = $("#btnAiAudit");
  if (btn) { btn.disabled = false; btn.textContent = "🤖 AI 审查"; }
}

async function startAudit(claimId) {
  const btn = $("#btnAiAudit");
  if (btn) { btn.disabled = true; btn.textContent = "审查启动中…"; }
  try {
    await api.post(`/api/claims/${claimId}/ai-audit`);
    toast("AI 审查已启动，正在分析材料…");
    startPolling(claimId);
  } catch (e) {
    toast("启动失败：" + e.message, true);
    restoreAuditBtn();
  }
}

const AUDIT_POLL_MS = 2000;      // 轮询间隔
const AUDIT_POLL_MAX = 150;      // 最长轮询次数（2s × 150 = 5 分钟）
const AUDIT_ERR_MAX = 5;         // 连续网络错误上限

function startPolling(claimId) {
  clearInterval(auditPollTimer);
  let ticks = 0;
  let errStreak = 0;
  const tick = async () => {
    ticks += 1;
    try {
      const audit = await api.get(`/api/claims/${claimId}/audit`);
      errStreak = 0;
      const st = $("#aiStatus");
      if (st) st.innerHTML = aiBadge(audit.ai_status);
      if (audit.ai_status === "running") {
        // 超时保护：避免后端异常导致界面永久停留在"审查中"
        if (ticks >= AUDIT_POLL_MAX) {
          clearInterval(auditPollTimer);
          restoreAuditBtn();
          if (st) st.innerHTML = aiBadge("failed");
          toast("审查超时（超过 5 分钟未返回），请稍后在审查结果中查看或重新审查", true);
        }
        return;
      }
      // 已结束（done / failed / none）：停止轮询并恢复按钮
      clearInterval(auditPollTimer);
      restoreAuditBtn();
      if (audit.ai_status === "done" && audit.ai_opinion) {
        let ai = null;
        try { ai = JSON.parse(audit.ai_opinion); } catch (e) {}
        const content = $("#aiContent");
        if (content && ai) content.innerHTML = renderAIResult(ai, audit);
        toast("AI 审查完成");
        renderLedgerList();
      } else if (audit.ai_status === "failed") {
        const content = $("#aiContent");
        if (content) {
          content.innerHTML = `<div class="empty" style="padding:24px">
            <div class="icon">⚠️</div>
            <p><b>AI 审查失败</b></p>
            <p style="color:var(--red);font-size:13px;margin-top:6px">${esc(audit.ai_error || "未知错误")}</p>
            <p style="font-size:13px;margin-top:10px">请到右上角「⚙️ AI 设置」检查模型配置（接口地址 / Key / 模型名），或重新点击「AI 审查」。</p>
          </div>`;
        }
        toast("AI 审查失败：" + (audit.ai_error || "未知错误"), true);
      }
    } catch (e) {
      errStreak += 1;
      if (errStreak >= AUDIT_ERR_MAX) {
        clearInterval(auditPollTimer);
        restoreAuditBtn();
        toast("无法获取审查状态（网络异常），请刷新页面查看", true);
      }
    }
  };
  auditPollTimer = setInterval(tick, AUDIT_POLL_MS);
  tick();  // 立即执行一次，避免首屏延迟
}

// ---------- 意见书：预览 / 编辑 / 保存 ----------
async function openOpinionEditor(claimId) {
  let data;
  try {
    data = await api.get(`/api/claims/${claimId}/opinion-preview`);
  } catch (e) {
    return toast(e.message, true);
  }
  const fmt = (v) => fmtMoney(v);
  const checksHtml = data.checks.map((c, i) => {
    const checked = c.includes("☑");
    return `<label style="display:block;margin:4px 0;cursor:pointer;font-size:14px">
      <input type="radio" name="oc_check" value="${i}" ${checked ? "checked" : ""}
        onchange="opinionCheckChange(${i})"> ${esc(c.replace(/[☑□]/g, "").trim())}
    </label>`;
  }).join("");

  openModal(`${modalHead(`预览 / 编辑意见书 · ${esc(data.claim_no)}`)}
    <div class="modal-body" style="max-height:74vh;overflow:auto">
      <div style="text-align:center;margin-bottom:10px">
        <div style="font-size:18px;font-weight:700">破产债权审查结果通知书</div>
        <div style="color:var(--text-2);font-size:12px">文号〔${new Date().getFullYear()}〕破管债审字第 ${String(data.claim_id).padStart(3, "0")} 号　·　${esc(data.has_draft ? "已保存编辑稿" : "未编辑（AI 生成默认稿）")}</div>
      </div>
      <div class="audit-section">
        <h4>致：${esc(data.name || "（债权人名称待补）")}　·　${esc(data.project_name || "")}</h4>
        <div style="color:var(--text-2);font-size:13px">在${esc(data.debtor || "【债务人】")}破产一案中，贵方于${esc(data.claim_date || "【日期】")}向管理人申报债权，审查结果如下：</div>
      </div>
      <div class="audit-section">
        <h4>一、申报情况</h4>
        <table class="tbl"><thead><tr>
          <th>债权性质</th><th>申报本金</th><th>申报利息</th><th>申报其他</th><th>申报总额</th>
        </tr></thead><tbody><tr>
          <td>${esc(data.claim_nature || "—")}</td><td class="num">¥${fmt(data.principal)}</td>
          <td class="num">¥${fmt(data.interest)}</td><td class="num">¥${fmt(data.others)}</td>
          <td class="num">¥${fmt(data.claim_amount)}</td>
        </tr></tbody></table>
      </div>
      <div class="audit-section">
        <h4>二、审查结果</h4>
        <table class="tbl"><thead><tr>
          <th>确认债权性质</th><th>确认本金</th><th>确认利息</th><th>确认其他</th><th>确认总额</th>
        </tr></thead><tbody><tr>
          <td>${esc(data.debt_nature || "—")}</td><td class="num">¥${fmt(data.audited_principal)}</td>
          <td class="num">¥${fmt(data.audited_interest)}</td><td class="num">¥${fmt(data.audited_others)}</td>
          <td class="num">¥${fmt(data.audited_amount)}</td>
        </tr></tbody></table>
      </div>
      <div class="audit-section">
        <h4>三、审查意见说明（可编辑）</h4>
        <div id="ocChecks">${checksHtml}</div>
        <div class="field" style="margin-top:8px">
          <label>意见说明文字</label>
          <textarea id="ocReason" rows="3" style="width:100%">${esc(data.reason || "")}</textarea>
        </div>
      </div>
      <div class="audit-section">
        <h4>材料关键证据（每行一条）</h4>
        <textarea id="ocEvidence" rows="4" style="width:100%">${esc((data.material_evidence || []).join("\n"))}</textarea>
      </div>
      <div class="audit-section">
        <h4>四、差额说明</h4>
        <table class="tbl"><thead><tr><th>申报总额</th><th>确认总额</th><th>差额</th><th>原因（可编辑）</th></tr></thead><tbody>
        <tr><td class="num">¥${fmt(data.claim_amount)}</td><td class="num">¥${fmt(data.audited_amount)}</td>
          <td class="num">¥${fmt(Number(data.claim_amount) - Number(data.audited_amount))}</td>
          <td><input id="ocDiffReason" value="${esc(data.diff_reason || "")}" style="width:100%"></td>
        </tr></tbody></table>
      </div>
      <div class="audit-section">
        <h4>五、法律依据（每行一条，可编辑）</h4>
        <textarea id="ocLegal" rows="4" style="width:100%">${esc((data.legal_basis || []).join("\n"))}</textarea>
      </div>
      <div class="audit-section">
        <h4>六、权利告知 / 落款（固定模板）</h4>
        <div style="font-size:13px;color:var(--text-2)">
          1. 贵方如对本审查结果有异议，应自收到本通知书之日起15日内向管理人提交书面异议及证据；<br>
          2. 管理人复核后出具《债权复核结果通知书》；3. 仍异议可依法向受理破产法院起诉（《企业破产法》第58条）。<br>
          管理人：${esc(data.manager || "")}　日期：____年__月__日
        </div>
      </div>
    </div>
    <div class="modal-foot">
      <button class="btn" onclick="closeModal()">取消</button>
      <button class="btn" onclick="window.open('/api/export/opinion/${claimId}','_blank')">📄 直接导出（用当前编辑稿）</button>
      <button class="btn btn-primary" onclick="saveOpinionDraft(${claimId})">💾 保存编辑稿</button>
    </div>`, { wide: true });
  window.__opinionData = data;
  window.__opinionClaimId = claimId;
}

function opinionCheckChange(i) {
  const data = window.__opinionData;
  if (!data) return;
  // 同步勾选到 reason 前缀
  const labels = ["", "", "", ""];
  const prefixes = { 0: "确认理由：", 1: "差额理由：", 2: "暂缓原因：", 3: "原因：" };
  const t = $("#ocReason");
  if (!t) return;
  let v = t.value;
  for (const p of Object.values(prefixes)) {
    if (v.startsWith(p)) { v = v.slice(p.length); break; }
  }
  t.value = (prefixes[i] || "") + v.trim();
  const box = $("#ocDiffReason");
  if (box && (i === 0 || i === 1)) {
    box.value = v.trim();
  }
}

async function saveOpinionDraft(claimId) {
  const data = window.__opinionData || {};
  // 收集勾选结果
  const checks = [];
  const radios = document.querySelectorAll('input[name="oc_check"]');
  radios.forEach((r) => {
    const idx = Number(r.value);
    const text = (data.checks[idx] || "").replace(/[☑□]/g, "").trim();
    checks.push((r.checked ? "☑ " : "□ ") + text);
  });
  if (checks.length !== 4) checks.push(...data.checks.slice(checks.length));
  const body = {
    checks,
    reason: $("#ocReason") ? $("#ocReason").value.trim() : "",
    material_evidence: ($("#ocEvidence") ? $("#ocEvidence").value : "")
      .split("\n").map((s) => s.trim()).filter(Boolean),
    diff_reason: $("#ocDiffReason") ? $("#ocDiffReason").value.trim() : "",
    legal_basis: ($("#ocLegal") ? $("#ocLegal").value : "")
      .split("\n").map((s) => s.trim()).filter(Boolean),
  };
  try {
    await api.post(`/api/claims/${claimId}/opinion-draft`, body);
    toast("意见书编辑稿已保存，导出将按此内容生成");
    closeModal();
  } catch (e) { toast(e.message, true); }
}

// ---------- 人工复核 ----------
async function openManualAudit(claimId) {
  const d = await api.get(`/api/claims/${claimId}/detail`);
  const c = d.claim, audit = d.audit;
  let ai = null;
  if (audit && audit.ai_opinion) { try { ai = JSON.parse(audit.ai_opinion); } catch (e) {} }
  openModal(`${modalHead(`人工复核 · ${c.claim_no}`)}
    <div class="modal-body">
      <div class="grid-4">
        <div class="field"><label>申报本金</label><input value="${fmtMoney(c.principal)}" disabled></div>
        <div class="field"><label>申报利息</label><input value="${fmtMoney(c.interest)}" disabled></div>
        <div class="field"><label>申报其他</label><input value="${fmtMoney(c.others)}" disabled></div>
        <div class="field"><label>申报总额</label><input value="${fmtMoney(c.claim_amount)}" disabled></div>
      </div>
      <div style="border-top:1px dashed var(--border);margin:12px 0"></div>
      <div class="grid-4">
        <div class="field"><label>审核本金</label><input id="ma_principal" type="number" step="0.01" value="${c.audited_principal || (ai ? ai.suggested_principal : "")}"></div>
        <div class="field"><label>审核利息</label><input id="ma_interest" type="number" step="0.01" value="${c.audited_interest || (ai ? ai.suggested_interest : "")}"></div>
        <div class="field"><label>审核其他</label><input id="ma_others" type="number" step="0.01" value="${c.audited_others || (ai ? ai.suggested_others : "")}"></div>
        <div class="field"><label>审核总额</label><input id="ma_amount" type="number" step="0.01" value="${c.audited_amount || ""}"><div style="font-size:11px;color:var(--text-2)">留空按分项自动求和</div></div>
      </div>
      <div class="field"><label>审查结论</label>
        <select id="ma_conclusion"><option value="">（请选择）</option>
          <option ${(audit && audit.audit_conclusion === "认可") ? "selected" : ""}>认可</option>
          <option ${(audit && audit.audit_conclusion === "部分认可") ? "selected" : ""}>部分认可</option>
          <option ${(audit && audit.audit_conclusion === "不认可") ? "selected" : ""}>不认可</option>
        </select></div>
      <div class="field"><label>确认债权性质</label>
        <select id="ma_nature"><option value="">（沿用申报性质：${esc(c.claim_nature || "未标注")}）</option>
          ${NATURE_OPTIONS.map((n) => `<option ${(c.debt_nature === n) ? "selected" : ""}>${n}</option>`).join("")}
        </select></div>
      <div class="field"><label>人工审查意见</label><textarea id="ma_opinion" rows="5" placeholder="填写审查过程、核减依据、优先权认定等">${esc(audit && audit.manual_opinion ? audit.manual_opinion : "")}</textarea></div>
      <div class="field"><label>审查人</label><input id="ma_auditor" value="${esc(audit && audit.auditor ? audit.auditor : "")}" placeholder="姓名"></div>
    </div>
    <div class="modal-foot">
      <button class="btn" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="submitManualAudit(${claimId})">保存复核结果</button>
    </div>`, { wide: true });
}
async function submitManualAudit(claimId) {
  const body = {
    audited_principal: Number($("#ma_principal").value || 0),
    audited_interest: Number($("#ma_interest").value || 0),
    audited_others: Number($("#ma_others").value || 0),
    audited_amount: $("#ma_amount").value === "" ? null : Number($("#ma_amount").value),
    audit_conclusion: $("#ma_conclusion").value,
    debt_nature: $("#ma_nature").value,
    manual_opinion: $("#ma_opinion").value,
    auditor: $("#ma_auditor").value,
  };
  if (!body.audit_conclusion) return toast("请选择审查结论", true);
  try {
    await api.post(`/api/claims/${claimId}/manual-audit`, body);
    closeModal();
    toast("人工复核已保存，债权状态更新为已复核");
    renderLedgerList();
    renderAudit(parseHash().params, $("#app"));
  } catch (e) { toast(e.message, true); }
}

// ---------- 视图：债权明细查询（类 Excel：筛选 + 排序 + 合计） ----------
let detailState = { projectId: null, q: "", sortKey: "claim_amount", sortDir: -1,
                    status: "", category: "", nature: "", minAmt: "", maxAmt: "" };

function detailSortIcon(key) {
  if (detailState.sortKey !== key) return "";
  return detailState.sortDir === 1 ? " ▲" : " ▼";
}

// 明细显示列（与台账列一致，金额可排序）
const DETAIL_COLS = LEDGER_COLS.filter((c) =>
  !["seq", "address", "agent_id_no", "agent_contact", "agent_address",
    "account_name", "bank_name", "account_no", "debt_nature",
    "guarantee_notes", "claim_type", "source_files", "created_at"].includes(c.key)
);

async function renderDetail(params, app) {
  let projectId = params.project ? Number(params.project) : null;
  if (!projectId) {
    const cur = getCurrentProject();
    if (cur && cur.id) projectId = cur.id;
  }
  if (!projectId) {
    renderProjectPicker(app, "债权明细查询", "选择一个项目，查询债权申报明细（类 Excel 筛选/排序）");
    return;
  }
  detailState.projectId = projectId;
  const [project, claims] = await Promise.all([
    api.get(`/api/projects/${projectId}`),
    api.get(`/api/claims?project_id=${projectId}`),
  ]);
  setCurrentProject(project);
  const cats = [...new Set(claims.map((c) => c.claim_category).filter(Boolean))];

  app.innerHTML = `
    <div class="page-head">
      <div><div class="page-title">📋 债权明细查询</div>
      <div class="page-sub">${esc(project.name)} · 自定义筛选 · 点击表头排序 · 支持合计</div></div>
      <div style="display:flex;gap:8px">
        <a class="btn btn-primary" href="#/dashboard?project=${projectId}">📊 汇总看板</a>
        <a class="btn" href="#/ledger?project=${projectId}">← 返回台账</a>
      </div>
    </div>
    <div class="card" style="margin-bottom:14px">
      <div class="filter-bar">
        <input id="dtQ" placeholder="搜索 债权人名称 / 信用代码 / 身份证" style="min-width:260px"
          value="${esc(detailState.q)}" oninput="detailState.q=this.value;renderDetailRows()">
        <select id="dtStatus" onchange="detailState.status=this.value;renderDetailRows()">
          <option value="">全部状态</option>
          <option value="pending" ${detailState.status === "pending" ? "selected" : ""}>待登记</option>
          <option value="registered" ${detailState.status === "registered" ? "selected" : ""}>已登记</option>
          <option value="reviewed" ${detailState.status === "reviewed" ? "selected" : ""}>已复核</option>
        </select>
        <select id="dtCat" onchange="detailState.category=this.value;renderDetailRows()">
          <option value="">全部债权种类</option>
          ${cats.map((c) => `<option ${detailState.category === c ? "selected" : ""}>${esc(c)}</option>`).join("")}
        </select>
        <select id="dtNature" onchange="detailState.nature=this.value;renderDetailRows()">
          <option value="">全部债权性质</option>
          ${NATURE_OPTIONS.map((n) => `<option ${detailState.nature === n ? "selected" : ""}>${n}</option>`).join("")}
        </select>
        <span style="font-size:12px;color:var(--text-2)">申报金额(元)</span>
        <input id="dtMin" type="number" placeholder="≥" style="width:110px" value="${detailState.minAmt}"
          oninput="detailState.minAmt=this.value;renderDetailRows()">
        <input id="dtMax" type="number" placeholder="≤" style="width:110px" value="${detailState.maxAmt}"
          oninput="detailState.maxAmt=this.value;renderDetailRows()">
        <button class="btn" onclick="resetDetailFilter()">↺ 重置</button>
      </div>
    </div>
    <div class="card">
      <div class="ledger-scroll" style="max-height:calc(100vh - 260px)">
        <table class="tbl nowrap" id="dtTable">
          <thead><tr id="dtHead"></tr></thead>
          <tbody id="dtBody"></tbody>
          <tfoot id="dtFoot"></tfoot>
        </table>
      </div>
    </div>`;

  const head = $("#dtHead");
  head.innerHTML = DETAIL_COLS.map((col) => `
    <th style="min-width:${col.w}px;cursor:pointer" onclick="detailSort('${col.key}')"
        title="点击排序">${esc(col.label)}${detailSortIcon(col.key)}</th>`).join("");
  renderDetailRows();
}

function detailSort(key) {
  if (detailState.sortKey === key) detailState.sortDir *= -1;
  else { detailState.sortKey = key; detailState.sortDir = -1; }
  renderDetailRows();
}

function resetDetailFilter() {
  detailState.q = ""; detailState.status = "";
  detailState.category = ""; detailState.nature = "";
  detailState.minAmt = ""; detailState.maxAmt = "";
  renderDetail(parseHash().params, $("#app"));
}

function renderDetailRows() {
  const { projectId, q, status, category, nature, minAmt, maxAmt } = detailState;
  if (!projectId) return;
  api.get(`/api/claims?project_id=${projectId}`).then((claims) => {
    const kw = (q || "").trim().toLowerCase();
    let rows = claims.filter((c) => {
      if (kw && !((c.name || "").toLowerCase().includes(kw)
                  || (c.credit_code || "").toLowerCase().includes(kw)
                  || (c.contact_info || "").toLowerCase().includes(kw))) return false;
      if (status && c.status !== status) return false;
      if (category && c.claim_category !== category) return false;
      // 债权性质筛选：与标准 7 类匹配（含同义归一）
      if (nature) {
        const raw = String(c.claim_nature || "").trim();
        const NORM = { "工程债权": "工程款优先权", "购房优先权": "购房者优先权",
                       "税收": "税收债权", "税款债权": "税收债权", "职工": "职工债权" };
        if (NORM[raw] !== nature && raw !== nature) return false;
      }
      const amt = Number(c.claim_amount || 0);
      if (minAmt !== "" && amt < Number(minAmt)) return false;
      if (maxAmt !== "" && amt > Number(maxAmt)) return false;
      return true;
    });
    // 排序
    const col = DETAIL_COLS.find((x) => x.key === detailState.sortKey);
    const dir = detailState.sortDir;
    rows.sort((a, b) => {
      let va = a[detailState.sortKey], vb = b[detailState.sortKey];
      if (col && col.money) { va = Number(va || 0); vb = Number(vb || 0); return (va - vb) * dir; }
      va = String(va ?? ""); vb = String(vb ?? "");
      return va.localeCompare(vb, "zh-CN") * dir;
    });
    rows.forEach((c, i) => { c.seq = i + 1; });

    const body = $("#dtBody");
    const foot = $("#dtFoot");
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="99" class="empty">无匹配记录</td></tr>`;
      foot.innerHTML = "";
      return;
    }
    body.innerHTML = rows.map((c) => {
      const cells = DETAIL_COLS.map((col) => {
        if (col.key === "claim_no" || col.key === "name") {
          return `<td><span class="link" onclick="openPreviewPage(${c.id})">${esc(cellValue(c, col))}</span></td>`;
        }
        if (col.key === "status") return `<td>${statusBadge(c.status)}</td>`;
        return `<td class="${col.money ? "num" : ""}">${esc(cellValue(c, col))}</td>`;
      }).join("");
      return `<tr>${cells}</tr>`;
    }).join("");
    // 合计行
    const sums = { principal: 0, interest: 0, others: 0, claim_amount: 0,
                   audited_principal: 0, audited_interest: 0, audited_others: 0, audited_amount: 0 };
    rows.forEach((c) => {
      Object.keys(sums).forEach((k) => { sums[k] += Number(c[k] || 0); });
    });
    const footCells = DETAIL_COLS.map((col) => {
      if (col.key === "seq") return `<td class="num" style="background:#f8f9fc;font-weight:700">合计 ${rows.length} 笔</td>`;
      if (col.money && sums[col.key] !== undefined) {
        return `<td class="num" style="background:#f8f9fc;font-weight:700">¥${fmtMoney(sums[col.key])}</td>`;
      }
      return `<td style="background:#f8f9fc"></td>`;
    }).join("");
    foot.innerHTML = `<tr>${footCells}</tr>`;
  }).catch((e) => toast(e.message, true));
}

// ---------- 视图：债权数据后台（Dashboard） ----------
let dashCharts = [];

function destroyDashCharts() {
  dashCharts.forEach((c) => { try { c.dispose(); } catch (e) {} });
  dashCharts = [];
}

async function renderDashboard(params, app) {
  // 项目来源：URL 参数 > 当前项目记忆；都没有则选项目
  let projectId = params.project ? Number(params.project) : null;
  if (!projectId) {
    const cur = getCurrentProject();
    if (cur && cur.id) projectId = cur.id;
  }
  if (!projectId) {
    renderProjectPicker(app, "债权数据后台", "选择一个项目查看债权数据统计与图表分析");
    return;
  }
  const natureParam = params.nature || "";
  const [project, data] = await Promise.all([
    api.get(`/api/projects/${projectId}`),
    api.get(`/api/projects/${projectId}/dashboard?nature=${encodeURIComponent(natureParam)}`),
  ]);
  setCurrentProject(project);

  const ov = data.overview || {};

  // 按性质行（申报侧 / 审核侧 / 各结论组）
  const natureLine = (list) => list
    .filter((x) => x.name !== "未标注")
    .map((x) => `<div class="sum-line"><span class="sum-label">${esc(x.name)}</span>
      <span class="sum-val">${x.count} 笔 · ${fmtWan(x.amount)} 万元</span></div>`).join("")
    + (list.some((x) => x.name === "未标注" && x.count > 0)
       ? `<div class="sum-line"><span class="sum-label">未标注性质</span>
          <span class="sum-val">${list.find((x) => x.name === "未标注").count} 笔 · ${fmtWan(list.find((x) => x.name === "未标注").amount)} 万元</span></div>` : "");

  const natureClaimed = data.nature_claimed || [];
  const groups = data.audit_groups || {};
  const gc = groups.confirmed || {}, gp = groups.partial || {}, gr = groups.rejected || {};

  // 结论组明细（笔数 + 金额 + 本金/利息/其他；已确认组附按性质明细）
  const groupBlock = (g, icon, cls, withNature) => {
    const nat = (g.nature || []).filter((n) => n.count > 0);
    return `
      <div class="dash-group ${cls}">
        <div class="sum-line main"><span class="sum-label">${icon} ${esc(g.label || "")}</span>
          <span class="sum-val" title="申报 ${fmtWan(g.claimed_amount)} 万元 / 审核 ${fmtWan(g.audited_amount)} 万元">
            ${g.count || 0} 笔 · ${fmtWan(g.amount)} 万元</span></div>
        <div class="sum-line sub"><span class="sum-label">其中：本金</span><span class="sum-val">${fmtWan(g.principal)} 万元</span></div>
        <div class="sum-line sub"><span class="sum-label">其中：利息</span><span class="sum-val">${fmtWan(g.interest)} 万元</span></div>
        <div class="sum-line sub"><span class="sum-label">其中：其他</span><span class="sum-val">${fmtWan(g.others)} 万元</span></div>
        ${withNature && nat.length ? `<div class="dash-sep" style="margin:8px 0"></div>${natureLine(nat)}` : ""}
      </div>`;
  };

  // 汇总左右分栏
  const colStyle = "min-width:0;border:1px solid var(--border);border-radius:10px;padding:14px 16px";
  const summaryHtml = `
    <div class="dash-cols">
      <div class="dash-col" style="${colStyle}">
        <div class="dash-col-head"><span class="dash-sec">📥 申报汇总</span></div>
        <div class="sum-line main"><span class="sum-label">申报笔数</span><span class="sum-val">${ov.count || 0} 笔</span></div>
        <div class="sum-line main"><span class="sum-label">申报债权总额</span><span class="sum-val">${fmtWan(ov.sum_claimed)} 万元</span></div>
        <div class="sum-line sub"><span class="sum-label">其中：本金</span><span class="sum-val">${fmtWan(ov.sum_principal)} 万元</span></div>
        <div class="sum-line sub"><span class="sum-label">其中：利息</span><span class="sum-val">${fmtWan(ov.sum_interest)} 万元</span></div>
        <div class="sum-line sub"><span class="sum-label">其中：其他</span><span class="sum-val">${fmtWan(ov.sum_others)} 万元</span></div>
        <div class="dash-sep" style="margin:10px 0"></div>
        ${natureLine(natureClaimed)}
      </div>
      <div class="dash-col" style="${colStyle}">
        <div class="dash-col-head"><span class="dash-sec dash-sec-ok">📤 审核汇总</span>
          <span class="dash-note">金额口径：该笔已录审核金额取审核额，否则取申报额</span></div>
        ${groupBlock(gc, "✅", "g-ok", true)}
        ${groupBlock(gp, "⏸", "g-part", false)}
        ${groupBlock(gr, "⛔", "g-no", false)}
        <div class="sum-line sub" style="margin-top:6px"><span class="sum-label">尚未出审查结论</span>
          <span class="sum-val">${groups.no_conclusion || 0} 笔（不计入以上三组）</span></div>
      </div>
    </div>`;

  app.innerHTML = `
    <div class="page-head">
      <div><div class="page-title">📊 债权数据后台</div>
      <div class="page-sub">${esc(project.name)} · 台账数据多维统计与图表分析（金额单位：万元）</div></div>
      <div style="display:flex;gap:8px">
        <a class="btn btn-primary" href="#/detail?project=${projectId}">📋 债权明细查询</a>
        <a class="btn" href="#/ledger?project=${projectId}">← 返回台账</a>
      </div>
    </div>
    <div class="filter-bar">
      <span style="font-size:13px;color:var(--text-2)">按债权性质筛选：</span>
      <select id="dashNature" onchange="dashNatureChange(this.value)">
        <option value="">全部性质</option>
        ${NATURE_OPTIONS.map((n) => `<option value="${n}" ${natureParam === n ? "selected" : ""}>${n}</option>`).join("")}
      </select>
      ${natureParam ? `<a class="btn btn-sm" href="#/dashboard?project=${projectId}">✕ 清除筛选</a>` : ""}
      <span style="color:var(--text-2);font-size:12px">${natureParam ? `当前仅统计：${esc(natureParam)}` : ""}</span>
    </div>
    <div class="card" style="margin-bottom:16px">
      <h3 style="margin-bottom:14px">📌 汇总概览</h3>
      ${summaryHtml}
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px" class="dash-grid">
      <div class="card"><h3 style="margin-bottom:8px">💰 申报债权金额构成（本金/利息/其他）</h3><div id="dashPieAmt" style="height:300px"></div></div>
      <div class="card"><h3 style="margin-bottom:8px">🏷️ 申报债权性质构成（按性质金额占比）</h3><div id="dashPieNature" style="height:300px"></div></div>
      <div class="card"><h3 style="margin-bottom:8px">✅ 已确认债权金额构成（本金/利息/其他）</h3><div id="dashPieConfAmt" style="height:300px"></div></div>
      <div class="card"><h3 style="margin-bottom:8px">✅ 已确认债权性质构成（按性质金额占比）</h3><div id="dashPieConfNature" style="height:300px"></div></div>
      <div class="card"><h3 style="margin-bottom:8px">📋 登记状态</h3>
        <div class="ledger-scroll" style="max-height:280px"><table class="tbl"><thead><tr>
          <th>状态</th><th>笔数</th><th>说明</th></tr></thead><tbody>
          <tr><td>${statusBadge("pending")}</td><td class="num">${(data.by_status || {}).pending || 0}</td><td style="color:var(--text-2)">未登记/处理中</td></tr>
          <tr><td>${statusBadge("registered")}</td><td class="num">${(data.by_status || {}).registered || 0}</td><td style="color:var(--text-2)">已登记待复核</td></tr>
          <tr><td>${statusBadge("reviewed")}</td><td class="num">${(data.by_status || {}).reviewed || 0}</td><td style="color:var(--text-2)">已复核定稿</td></tr>
        </tbody></table></div>
      </div>
      <div class="card"><h3 style="margin-bottom:8px">🤖 AI 审查结论</h3>
        <div id="dashPieAudit" style="height:200px"></div>
        <table class="tbl" style="margin-top:6px"><thead><tr>
          <th>结论</th><th>笔数</th><th>审核金额(万)</th></tr></thead><tbody>
          ${(data.audit && data.audit.by_result || []).map((x) => `<tr><td>${esc(x.name)}</td><td class="num">${x.count}</td>
            <td class="num">${fmtWan(x.amount)}</td></tr>`).join("") || `<tr><td colspan="3" class="empty">暂无审查</td></tr>`}
        </tbody></table>
      </div>
    </div>`;

  // 渲染图表
  renderDashCharts(data);
}

function dashNatureChange(nature) {
  const pid = ledgerState.projectId || (parseHash().params.project || "");
  location.hash = `#/dashboard?project=${pid}${nature ? "&nature=" + encodeURIComponent(nature) : ""}`;
}

function echartsSafe(elId) {
  const el = document.getElementById(elId);
  if (!el || typeof echarts === "undefined") return null;
  const c = echarts.init(el);
  dashCharts.push(c);
  return c;
}

/* 统一绘制构成饼图：无数据时在中间显示提示文字 */
function dashPie(containerId, items, emptyText, unit) {
  const chart = echartsSafe(containerId);
  if (!chart) return;
  const data = (items || []).filter((x) => Number(x.value) > 0);
  if (!data.length) {
    chart.setOption({
      graphic: [{ type: "text", left: "center", top: "middle",
                  style: { text: emptyText || "暂无数据", fill: "#9ca3af", fontSize: 14 } }],
    }, true);
    return;
  }
  chart.setOption({
    tooltip: { trigger: "item", formatter: `{b}: ${unit || ""}{c} ({d}%)` },
    legend: { bottom: 0, type: "scroll" },
    series: [{
      type: "pie", radius: ["38%", "68%"], center: ["50%", "45%"],
      label: { formatter: "{b}\n{d}%" },
      data,
    }],
  }, true);
}

function renderDashCharts(data) {
  destroyDashCharts();
  const ov = data.overview || {};
  const gc = (data.audit_groups || {}).confirmed || {};

  // 1. 申报债权金额构成（本金/利息/其他）
  dashPie("dashPieAmt", [
    { name: "本金", value: ov.sum_principal },
    { name: "利息", value: ov.sum_interest },
    { name: "其他", value: ov.sum_others },
  ], "暂无申报金额", "¥");

  // 2. 申报债权性质构成（按性质金额占比）
  dashPie("dashPieNature", (data.nature_claimed || []).map((x) => ({
    name: x.name, value: x.amount,
  })), "暂无已标注性质的申报债权", "¥");

  // 3. 已确认债权金额构成（本金/利息/其他）
  dashPie("dashPieConfAmt", [
    { name: "本金", value: gc.principal },
    { name: "利息", value: gc.interest },
    { name: "其他", value: gc.others },
  ], "暂无已审查确认的债权", "¥");

  // 4. 已确认债权性质构成（按性质金额占比）
  dashPie("dashPieConfNature", (gc.nature || []).map((x) => ({
    name: x.name, value: x.amount,
  })), "暂无已审查确认的债权", "¥");

  // 5. AI 审查结论饼图（下方已有明细表）
  const pieAudit = echartsSafe("dashPieAudit");
  if (pieAudit) {
    const br = data.audit && data.audit.by_result ? data.audit.by_result : [];
    if (!br.some((x) => x.count > 0)) {
      pieAudit.setOption({
        graphic: [{
          type: "text", left: "center", top: "middle",
          style: { text: "暂无已完成的 AI 审查", fill: "#9ca3af", fontSize: 14 },
        }],
      }, true);
    } else {
      pieAudit.setOption({
        tooltip: { trigger: "item", formatter: "{b}: {c} 笔 ({d}%)" },
        legend: { bottom: 0 },
        series: [{
          type: "pie", radius: ["35%", "62%"], center: ["50%", "42%"],
          label: { formatter: "{b} {c}笔" },
          data: br.map((x, i) => ({
            name: x.name, value: x.count,
            itemStyle: { color: ["#52c41a", "#faad14", "#ff4d4f"][i] },
          })),
        }],
      }, true);
    }
  }
}

// ---------- 启动 ----------
router();

