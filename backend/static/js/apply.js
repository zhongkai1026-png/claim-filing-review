/* 债权在线申报公开页逻辑 */
"use strict";

const $ = (sel) => document.querySelector(sel);

const selectedFiles = [];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function init() {
  const params = new URLSearchParams(location.search);
  const projectId = params.get("project");
  if (!projectId) return;
  try {
    const r = await fetch(`/api/projects/${projectId}`);
    if (r.ok) {
      const p = await r.json();
      document.title = `${p.name} · 债权在线申报`;
      $("#projName").textContent = p.name;
    }
  } catch (e) { /* 保持默认标题 */ }
  $("#fileInput").addEventListener("change", (ev) => {
    [...ev.target.files].forEach((f) => {
      if (selectedFiles.some((x) => x.name === f.name && x.size === f.size)) return;
      selectedFiles.push(f);
    });
    renderFileList();
    ev.target.value = "";
  });
  // 必填项输入后自动清除高亮
  ["#f_name", "#f_credit_code", "#f_contact"].forEach((sel) => {
    const el = $(sel);
    if (el) el.addEventListener("input", () => {
      if (el.value.trim()) el.classList.remove("missing");
    });
  });
}

function renderFileList() {
  const box = $("#fileList");
  if (!selectedFiles.length) { box.innerHTML = ""; return; }
  box.innerHTML = selectedFiles.map((f, i) => {
    const mb = (f.size / 1024 / 1024).toFixed(1);
    return `<div class="file-item"><span>📄 ${esc(f.name)} <span style="color:var(--text-2)">（${mb}MB）</span></span>
      <span class="del" onclick="removeFile(${i})">✕ 移除</span></div>`;
  }).join("");
}
function removeFile(i) {
  selectedFiles.splice(i, 1);
  renderFileList();
}

function numVal(id) {
  const v = $(id).value.trim().replace(/[,，\s]/g, "");
  if (!v) return "";
  if (v.endsWith("万")) {
    const n = parseFloat(v);
    return isNaN(n) ? "" : String(Math.round(n * 10000 * 100) / 100);
  }
  return v;
}

// 必填校验：缺失时高亮并聚焦，返回是否通过
function requireField(sel, msg) {
  const el = $(sel);
  if (!el) return true;
  const v = el.value.trim();
  if (v) { el.classList.remove("missing"); return true; }
  el.classList.add("missing");
  el.focus();
  toast(msg, true);
  return false;
}

async function submitApply() {
  const projectId = new URLSearchParams(location.search).get("project");
  if (!projectId) return alert("链接缺少项目参数，请联系管理人获取正确链接");
  // 三项必填：债权人名称、统一社会信用代码/身份证号、联系方式
  if (!requireField("#f_name", "请填写债权人名称")) return;
  if (!requireField("#f_credit_code", "请填写统一社会信用代码 / 身份证号码")) return;
  if (!requireField("#f_contact", "请填写联系方式")) return;
  const name = $("#f_name").value.trim();
  const creditCode = $("#f_credit_code").value.trim();
  const contact = $("#f_contact").value.trim();

  const amount = numVal("#f_amount");
  if (!amount) return toast("请填写申报总额，或填写本金/利息/其他自动计算", true);

  const btn = $("#submitBtn");
  btn.disabled = true;
  btn.textContent = "提交中…";
  try {
    const fd = new FormData();
    fd.append("project_id", projectId);
    fd.append("name", name);
    fd.append("credit_code", creditCode);
    fd.append("legal_rep", $("#f_legal_rep").value.trim());
    fd.append("contact_info", contact);
    fd.append("address", $("#f_address").value.trim());
    fd.append("claim_category", $("#f_category").value);
    fd.append("claim_nature", $("#f_nature").value);
    fd.append("claim_date", $("#f_date").value);
    fd.append("principal", numVal("#f_principal") || "0");
    fd.append("interest", numVal("#f_interest") || "0");
    fd.append("others", numVal("#f_others") || "0");
    fd.append("claim_amount", amount);
    fd.append("remark", $("#f_remark").value.trim());
    selectedFiles.forEach((f) => fd.append("files", f));

    const r = await fetch("/api/online-apply", { method: "POST", body: fd });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || `提交失败 (${r.status})`);

    $("#doneNo").textContent = j.submit_no;
    $("#applyCard").style.display = "none";
    $("#doneCard").style.display = "block";
    window.scrollTo(0, 0);
  } catch (e) {
    toast(e.message, true);
    btn.disabled = false;
    btn.textContent = "提交申报";
  }
}

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
  while (root.children.length > 4) {
    try { root.removeChild(root.firstChild); } catch (e) { break; }
  }
}

init();
