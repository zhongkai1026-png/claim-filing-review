/* 债权申报材料独立预览页逻辑（不阻塞主工具） */
"use strict";

const $ = (sel) => document.querySelector(sel);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
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
function parseEngineBadge(e) {
  if (e === "mineru") return `<span class="badge badge-mineru" title="MinerU 云端解析">☁️ MinerU</span>`;
  if (e === "local") return `<span class="badge badge-local" title="本地解析">💻 本地</span>`;
  return "";
}
// 补充材料标识：与首次申报材料区分
function originBadge(o) {
  return o === "supplement"
    ? `<span class="badge badge-running" title="后续补充上传的材料">📎 补充</span>` : "";
}

let files = [];

async function load() {
  const params = new URLSearchParams(location.search);
  const claimId = params.get("claim_id");
  const app = $("#app");
  if (!claimId) {
    app.innerHTML = `<div class="empty"><div class="icon">⚠️</div><p>缺少债权参数，请从工具台账进入</p></div>`;
    return;
  }
  let d;
  try {
    const r = await fetch(`/api/claims/${claimId}/detail`);
    if (!r.ok) throw new Error(`请求失败 (${r.status})`);
    d = await r.json();
  } catch (e) {
    app.innerHTML = `<div class="empty"><div class="icon">⚠️</div><p>加载失败：${esc(e.message)}</p></div>`;
    return;
  }
  const c = d.claim;
  files = d.files || [];
  $("#claimSub").textContent = `${c.claim_no} · ${c.name || "（未识别）"}`;
  const tool = $("#btnTool");
  if (tool) tool.href = `/index.html#/ledger?project=${c.project_id}`;

  app.innerHTML = `
    <div class="card" style="margin-bottom:14px">
      <h3 style="margin-bottom:10px">📎 申报材料（共 ${files.length} 份）</h3>
      <div class="preview-toolbar" id="fileTabs"></div>
      <div id="fileFrame">
        ${files.length ? `<iframe class="preview-frame" src="/api/files/${files[0].id}/preview"></iframe>` : `<div class="empty"><div class="icon">📄</div><p>无申报材料</p></div>`}
      </div>
    </div>
    <div class="card">
      <h3 style="margin-bottom:8px">📄 解析文本</h3>
      <div class="content" style="max-height:200px;overflow:auto;white-space:pre-wrap">${esc(files.map((f) => f.ocr_text).join("\n\n---\n\n") || "（无解析文本：可能是图片/扫描件未识别或内容为空）")}</div>
    </div>`;

  // 文件 tab
  const tabs = $("#fileTabs");
  if (files.length) {
    tabs.innerHTML = files.map((f, i) =>
      `<button class="btn ${i === 0 ? "active-file" : ""}" data-i="${i}" onclick="switchFile(${i})">${esc(f.filename)} ${originBadge(f.origin)}${parseEngineBadge(f.parse_engine)}${parseStatusBadge(f.parse_status)}</button>
       <a class="btn" href="/api/files/${f.id}/download" target="_blank">⬇ 下载</a>`).join("");
  } else {
    tabs.innerHTML = `<span style="color:var(--text-2)">无材料文件</span>`;
  }
}

function switchFile(i) {
  const f = files[i];
  document.querySelectorAll("#fileTabs .btn[data-i]").forEach((b) => b.classList.remove("active-file"));
  const btn = document.querySelector(`#fileTabs .btn[data-i="${i}"]`);
  if (btn) btn.classList.add("active-file");
  const frame = $("#fileFrame");
  const imgExt = ["png", "jpg", "jpeg", "bmp", "gif", "webp"];
  if (f.file_type === "pdf") {
    frame.innerHTML = `<iframe class="preview-frame" src="/api/files/${f.id}/preview"></iframe>`;
  } else if (imgExt.includes((f.filename.split(".").pop() || "").toLowerCase())) {
    frame.innerHTML = `<img src="/api/files/${f.id}/preview" style="max-width:100%;max-height:90vh;border-radius:8px">`;
  } else if (f.file_type === "text") {
    frame.innerHTML = `<div class="content" style="max-height:90vh;overflow:auto;white-space:pre-wrap">${esc(f.ocr_text || "（空）")}</div>`;
  } else {
    frame.innerHTML = `<div class="empty"><div class="icon">📄</div><p>该文件类型不支持在线预览，请下载查看</p>
      <p><a class="link" href="/api/files/${f.id}/download">点击下载 →</a></p></div>`;
  }
}

load();
