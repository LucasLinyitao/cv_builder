// ====================== Init ======================
const RAW_DATA = window.__BOOT.data;
let editData = JSON.parse(JSON.stringify(RAW_DATA));

// ---- Build state ----
let eduChecked = {};
let expItems = [];
let projItems = [];
let skillsChecked = true;

function initBuildState() {
  (RAW_DATA.education || []).forEach(e => { eduChecked[e.id] = true; });
  Object.entries(RAW_DATA.experiences || {}).forEach(([id, exp]) => {
    const vs = Object.keys(exp.variants || {});
    expItems.push({ id, checked: true, variant: vs[0] });
  });
  Object.entries(RAW_DATA.projects || {}).forEach(([id, proj]) => {
    const vs = Object.keys(proj.variants || {});
    projItems.push({ id, checked: true, variant: vs[0] });
  });
}

function buildProfile() {
  return {
    education: (RAW_DATA.education || []).map(e => e.id).filter(id => eduChecked[id]),
    experiences: expItems.filter(it => it.checked).map(it => `${it.id}:${it.variant}`),
    projects: projItems.filter(it => it.checked).map(it => `${it.id}:${it.variant}`),
    include_skills: skillsChecked
  };
}

// ====================== Tab switch ======================
function switchTab(tab) {
  document.getElementById("tabBuild").classList.toggle("active", tab === "build");
  document.getElementById("tabData").classList.toggle("active", tab === "data");
  document.getElementById("buildPanel").style.display = tab === "build" ? "flex" : "none";
  document.getElementById("dataPanel").style.display = tab === "data" ? "block" : "none";
  document.getElementById("headerBuildBtns").style.display = tab === "build" ? "" : "none";
  document.getElementById("headerDataBtns").style.display = tab === "data" ? "" : "none";
  if (tab === "data") renderDataTab();
}

// ====================== Build tab render ======================
function variantOptions(variants, selected) {
  return Object.keys(variants).map(v =>
    `<option value="${v}" ${v === selected ? "selected" : ""}>${v}</option>`
  ).join("");
}

function renderBuild() {
  const left = document.getElementById("leftContent");
  let html = "<div class='section-title'>Education</div><div class='group'>";
  (RAW_DATA.education || []).forEach(e => {
    html += `<div class="item">
      <input type="checkbox" ${eduChecked[e.id] ? "checked" : ""}
        onchange="eduChecked['${e.id}']=this.checked; refreshPreview()">
      <label>${e.institution} <span class="meta">${e.degree}</span></label>
    </div>`;
  });
  html += "</div><div class='section-title'>Professional Experience</div><div class='group'>";
  expItems.forEach((it, i) => {
    const exp = RAW_DATA.experiences[it.id];
    if (!exp) return;
    html += `<div class="item" data-list="exp" data-idx="${i}">
      <input type="checkbox" ${it.checked ? "checked" : ""}
        onchange="expItems[${i}].checked=this.checked; refreshPreview()">
      <label>${exp.company} <span class="meta">${exp.role}</span></label>
      <select onchange="expItems[${i}].variant=this.value; refreshPreview()">
        ${variantOptions(exp.variants, it.variant)}
      </select>
      ${grip("exp", i)}
    </div>`;
  });
  html += "</div><div class='section-title'>Projects &amp; Competitions</div><div class='group'>";
  projItems.forEach((it, i) => {
    const proj = RAW_DATA.projects[it.id];
    if (!proj) return;
    html += `<div class="item" data-list="proj" data-idx="${i}">
      <input type="checkbox" ${it.checked ? "checked" : ""}
        onchange="projItems[${i}].checked=this.checked; refreshPreview()">
      <label>${proj.title}</label>
      <select onchange="projItems[${i}].variant=this.value; refreshPreview()">
        ${variantOptions(proj.variants, it.variant)}
      </select>
      ${grip("proj", i)}
    </div>`;
  });
  html += `</div><div class="section-title">Skills</div><div class="group">
    <div class="item">
      <input type="checkbox" ${skillsChecked?"checked":""} onchange="skillsChecked=this.checked;refreshPreview()">
      <label>Include Skills &amp; Languages section</label>
    </div></div>`;
  left.innerHTML = html;
}

let previewTimer = null;
let autoRefresh = (window.__BOOT.settings || {}).auto_refresh !== false;
let previewStale = false;

// Called whenever the selection changes. Auto mode recompiles shortly after the last change;
// manual mode only marks the preview as out of date until the user presses Refresh.
function refreshPreview() {
  clearTimeout(previewTimer);
  if (!autoRefresh && pdfDoc) { markStale(); return; }
  previewTimer = setTimeout(manualRefresh, 500);
}
function manualRefresh() {
  clearTimeout(previewTimer);
  previewStale = false;
  document.getElementById("btnRefresh").classList.remove("attn");
  if (rightView === "tex") updatePreview();
  updatePdfPreview();
}
function markStale() {
  previewStale = true;
  setBadge("Out of date", "warn");
  document.getElementById("btnRefresh").classList.add("attn");
}
function setAutoRefresh(on) {
  autoRefresh = on;
  fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ auto_refresh: on }) }).catch(() => {});
  if (on && previewStale) manualRefresh();
}
document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); manualRefresh(); }
});

// ====================== Live PDF preview (PDF.js) ======================
pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/pdfjs/pdf.worker.min.js";
let rightView = "pdf";
let pdfDoc = null, pdfZoom = 0;        // pdfZoom 0 = fit width, else a scale multiplier
let pdfSeq = 0, pdfAbort = null, renderSeq = 0;

function setRightView(v) {
  rightView = v;
  document.getElementById("segPdf").classList.toggle("on", v === "pdf");
  document.getElementById("segTex").classList.toggle("on", v === "tex");
  document.getElementById("pdfView").style.display = v === "pdf" ? "" : "none";
  document.getElementById("pdfErr").style.display = "none";
  document.getElementById("texWrap").style.display = v === "tex" ? "block" : "none";
  document.getElementById("zoomCtl").style.display = v === "pdf" ? "" : "none";
  if (v === "tex") updatePreview(); else if (pdfErrMsg) showPdfErr(pdfErrMsg);
}

function setBadge(text, cls) {
  const b = document.getElementById("pdfBadge");
  b.textContent = text; b.className = "badge " + (cls || "");
}
let pdfErrMsg = "";
function showPdfErr(msg) {
  pdfErrMsg = msg || "";
  const el = document.getElementById("pdfErr");
  el.textContent = pdfErrMsg;
  el.style.display = pdfErrMsg && rightView === "pdf" ? "block" : "none";
}

function updatePdfPreview() {
  const seq = ++pdfSeq;
  if (pdfAbort) pdfAbort.abort();
  pdfAbort = new AbortController();
  const ctl = pdfAbort;
  let timedOut = false;
  const guard = setTimeout(() => { timedOut = true; ctl.abort(); }, 100000);   // server gives up at 60 s
  setBadge("Compiling…", "busy");
  fetch("/api/preview_pdf", {
    method: "POST", signal: pdfAbort.signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildProfile())
  }).then(async r => {
    clearTimeout(guard);
    if (seq !== pdfSeq) return;                       // superseded by a newer request
    if (r.status === 409) return;                     // server skipped it: a newer one is coming
    if (!r.ok) {
      let msg = "HTTP " + r.status;
      try { const j = await r.json(); if (j.error) msg = j.error; } catch {}
      showPdfErr(msg + (pdfDoc ? "(下方仍显示上一次成功的预览)" : ""));
      setBadge("Error", "warn");
      if (!pdfDoc) document.getElementById("pdfEmpty").textContent = "No preview yet";
      return;
    }
    const buf = await r.arrayBuffer();
    if (seq !== pdfSeq) return;
    await loadPdf(buf);
    const pages = pdfDoc.numPages;
    showPdfErr("");
    if (pages > 1) setBadge(pages + " pages · over 1 page", "warn");
    else setBadge("1 page", "ok");
  }).catch(e => {
    clearTimeout(guard);
    if (e.name === "AbortError" && !timedOut) return;
    setBadge(timedOut ? "Timed out" : "Error", "warn");
    showPdfErr(timedOut ? "预览编译超时,已放弃。请检查 LaTeX 环境后点 Refresh 重试。" : "Preview failed: " + e);
  });
}

async function loadPdf(buf) {
  const doc = await pdfjsLib.getDocument({ data: buf }).promise;
  const old = pdfDoc;
  pdfDoc = doc;
  await renderPdf();
  if (old) old.destroy();
}

// Render every page off-screen first, then swap in one go, so the view never flashes
// blank and the scroll position is preserved across refreshes.
async function renderPdf() {
  if (!pdfDoc) return;
  const my = ++renderSeq;
  const view = document.getElementById("pdfView");
  const avail = view.clientWidth - 32;
  const dpr = window.devicePixelRatio || 1;
  const frag = document.createDocumentFragment();
  let cssW = 0;
  for (let n = 1; n <= pdfDoc.numPages; n++) {
    const page = await pdfDoc.getPage(n);
    if (my !== renderSeq) return;
    const base = page.getViewport({ scale: 1 });
    const fit = avail / base.width;
    const scale = pdfZoom ? fit * pdfZoom : fit;
    const vp = page.getViewport({ scale: scale * dpr });
    const c = document.createElement("canvas");
    c.width = Math.floor(vp.width); c.height = Math.floor(vp.height);
    c.style.width = Math.floor(vp.width / dpr) + "px";
    c.style.height = Math.floor(vp.height / dpr) + "px";
    await page.render({ canvasContext: c.getContext("2d"), viewport: vp }).promise;
    if (my !== renderSeq) return;
    cssW = Math.max(cssW, vp.width / dpr);
    frag.appendChild(c);
  }
  const top = view.scrollTop, left = view.scrollLeft;
  const host = document.getElementById("pdfPages");
  host.replaceChildren(frag);
  host.style.width = cssW + "px";
  view.scrollTop = top; view.scrollLeft = left;
  document.getElementById("pdfEmpty").style.display = "none";
}

function zoomBy(d) {
  pdfZoom = d === 0 ? 0 : Math.min(3, Math.max(0.4, (pdfZoom || 1) + d));
  renderPdf();
}
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (!pdfZoom) renderPdf(); }, 200);
});

function updatePreview() {
  const profile = buildProfile();
  fetch("/api/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile)
  }).then(r => r.text().then(tex => ({ ok: r.ok, status: r.status, tex })))
    .then(({ ok, status, tex }) => {
      const el = document.getElementById("texPreview");
      if (!ok) {
        let extra = "";
        try { const j = JSON.parse(tex); if (j && j.error) extra = "\n\n" + j.error; } catch {}
        el.textContent = `Preview failed (HTTP ${status}).${extra}`;
        return;
      }
      el.textContent = tex;
    })
    .catch(e => { document.getElementById("texPreview").textContent = "Error: " + e; });
}

// In the desktop app (pywebview) exports go through a native "Save As" dialog.
function nativeApi() { return window.pywebview && window.pywebview.api ? window.pywebview.api : null; }
function nativeSave(method, label) {
  toast("Preparing " + label + "…");
  nativeApi()[method](buildProfile(), "cv").then(r => {
    if (r && r.ok) toast("Saved " + r.path);
    else if (r && r.cancelled) toast("Cancelled");
    else toast("Export failed — " + ((r && r.error) || "unknown error"));
  }).catch(e => toast("Export failed — " + e));
}

function downloadTex() {
  if (nativeApi()) { nativeSave("save_tex", ".tex"); return; }
  const name = "cv";
  fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile: buildProfile(), name })
  }).then(r => r.json()).then(data => {
    const blob = new Blob([data.tex], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name + ".tex"; a.click();
    toast("Downloaded " + name + ".tex");
  });
}

function downloadPdf() {
  if (nativeApi()) { nativeSave("save_pdf", "PDF"); return; }
  toast("Preparing PDF…");
  fetch("/api/compile", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile: buildProfile(), name: "cv" })
  }).then(r => r.json()).then(resp => {
    if (!resp.ok) throw new Error(resp.error || "compile failed");
    return fetch("/api/download_pdf?name=cv");
  }).then(r => { if (!r.ok) throw new Error("PDF not found"); return r.blob(); })
    .then(blob => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "cv.pdf";
      document.body.appendChild(a); a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    })
    .catch(e => toast("Download failed — " + e.message));
}

function showSaveModal() {
  document.getElementById("saveModal").classList.remove("hidden");
  document.getElementById("saveModalInput").value = "";
  document.getElementById("saveModalInput").focus();
}

function hideSaveModal() {
  document.getElementById("saveModal").classList.add("hidden");
}

function submitSaveProfile() {
  const name = document.getElementById("saveModalInput").value.trim();
  if (!name) { toast("Enter a profile name"); return; }
  fetch("/api/save_profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, profile: buildProfile() })
  }).then(r => r.json()).then(data => {
    populateProfiles(data.profiles);
    document.getElementById("profileSelect").value = "cv_profile_" + name + ".yaml";
    syncProfileButtons();
    hideSaveModal();
    toast("Saved cv_profile_" + name + ".yaml");
  });
}

function loadProfile() {
  const sel = document.getElementById("profileSelect").value;
  if (!sel) return;
  fetch("/api/load_profile/" + encodeURIComponent(sel))
    .then(r => r.json()).then(p => applyProfile(p));
}

function quitApp() {
  if (!confirm("确定要退出程序吗？未保存的修改会丢失。")) return;
  fetch("/api/shutdown", { method: "POST" }).then(() => {
    document.body.innerHTML = "<div style='padding:40px;font-size:16px;font-family:sans-serif;'>程序已退出，可以关闭此浏览器标签页了。</div>";
  }).catch(() => {
    document.body.innerHTML = "<div style='padding:40px;font-size:16px;font-family:sans-serif;'>程序已退出，可以关闭此浏览器标签页了。</div>";
  });
}

function deleteProfile() {
  const selEl = document.getElementById("profileSelect");
  const sel = selEl.value;
  if (!sel) { toast("Select a profile first"); return; }
  if (!confirm(`Delete profile "${sel.replace(/^cv_profile_/, "").replace(/\.yaml$/, "")}"? This cannot be undone.`)) return;
  fetch("/api/delete_profile/" + encodeURIComponent(sel), { method: "DELETE" })
    .then(r => r.json()).then(data => {
      populateProfiles(data.profiles);
      selEl.value = "";
      syncProfileButtons();
      toast("Deleted " + sel);
    });
}

function syncProfileButtons() {
  const b = document.getElementById("btnDelProfile");
  if (b) b.disabled = !document.getElementById("profileSelect").value;
}

function applyProfile(p) {
  eduChecked = {};
  (RAW_DATA.education || []).forEach(e => { eduChecked[e.id] = false; });
  (p.education || []).forEach(id => { eduChecked[id] = true; });
  expItems = (p.experiences || []).map(entry => {
    const [id, v] = entry.split(":");
    return { id, checked: true, variant: v || firstVariantBuild(id, "experiences") };
  });
  projItems = (p.projects || []).map(entry => {
    const [id, v] = entry.split(":");
    return { id, checked: true, variant: v || firstVariantBuild(id, "projects") };
  });
  skillsChecked = p.include_skills !== false;
  renderBuild();
  refreshPreview();
  toast("Profile loaded");
}

function firstVariantBuild(id, kind) {
  const obj = RAW_DATA[kind][id];
  return obj ? Object.keys(obj.variants)[0] : "v1";
}

function populateProfiles(profiles) {
  const sel = document.getElementById("profileSelect");
  sel.innerHTML = '<option value="">Custom selection</option>' +
    profiles.map(p => `<option value="${p}">${p.replace(/^cv_profile_/, "").replace(/\.yaml$/, "")}</option>`).join("");
  syncProfileButtons();
}

// ====================== Data tab ======================
function getOrder(kind) {
  if (!editData._order) editData._order = { experiences: [], projects: [] };
  const order = editData._order[kind];
  const section = editData[kind] || {};
  // Ensure all existing keys in order, add new ones at end
  const sectionIds = Object.keys(section);
  sectionIds.forEach(id => { if (!order.includes(id)) order.push(id); });
  // Remove stale entries
  for (let i = order.length - 1; i >= 0; i--) {
    if (!section[order[i]]) order.splice(i, 1);
  }
  return order;
}

function renderDataTab() {
  const el = document.getElementById("dataContent");
  const openIds = new Set([...el.querySelectorAll(".data-card.open[id]")].map(c => c.id));
  let html = "";

  // Personal info
  const p = editData.personal || {};
  html += `<div class="section-title">Personal Info</div>`;
  html += `<div class="data-card open"><div class="data-card-body">`;
  html += `<div class="row">`;
  html += `<div style="flex:1"><label class="field">Name</label>`;
  html += `<input type="text" value="${escAttr(p.name||'')}" data-personal-field="name" style="width:100%"></div>`;
  html += `<div style="flex:1"><label class="field">Email</label>`;
  html += `<input type="text" value="${escAttr(p.email||'')}" data-personal-field="email" style="width:100%"></div>`;
  html += `</div>`;
  html += `<div class="row">`;
  html += `<div style="flex:1"><label class="field">Phone</label>`;
  html += `<input type="text" value="${escAttr(p.phone||'')}" data-personal-field="phone" style="width:100%"></div>`;
  html += `<div style="flex:1"><label class="field">Location</label>`;
  html += `<input type="text" value="${escAttr(p.location||'')}" data-personal-field="location" style="width:100%"></div>`;
  html += `</div>`;
  html += `</div></div>`;

  // Education
  html += sectionHead("Education", "educations");
  const eduList = editData.education || [];
  eduList.forEach((edu, i) => {
    html += renderEduCard(i, eduList.length, edu);
  });

  // Experiences
  html += sectionHead("Professional Experience", "experiences");
  const expOrder = getOrder("experiences");
  const exps = editData.experiences || {};
  expOrder.forEach(id => {
    html += renderExpCard(id, expOrder, exps[id]);
  });

  // Projects
  html += sectionHead("Projects &amp; Competitions", "projects");
  const projOrder = getOrder("projects");
  const projs = editData.projects || {};
  projOrder.forEach(id => {
    html += renderProjCard(id, projOrder, projs[id]);
  });

  // Skills
  html += `<div class="section-title">Skills &amp; Languages</div>`;
  html += `<div class="data-card open"><div class="data-card-body">`;
  const skills = editData.skills || {};
  const skillKeys = Object.keys(skills);
  skillKeys.forEach((key, i) => {
    html += `<div class="row" style="margin-bottom:6px;align-items:center">
      <input type="text" value="${escAttr(key)}" data-skill-key="${i}" style="width:140px;flex-shrink:0;margin-bottom:0"
        placeholder="skill category">
      <input type="text" value="${escAttr(skills[key]||'')}" data-skill-val="${i}" style="flex:1;margin-bottom:0"
        placeholder="content">
      <button class="btn-sm danger" onclick="removeSkill(${i})">−</button>
    </div>`;
  });
  html += `<button class="btn-sm accent" onclick="addSkill()" style="margin-top:4px">+ Skill row</button>`;
  html += `</div></div>`;

  el.innerHTML = html;
  openIds.forEach(id => { const c = document.getElementById(id); if (c) c.classList.add("open"); });
  autosizeAll();
}

function renderExpCard(id, order, exp) {
  if (!exp) return "";
  const vs = exp.variants || {};
  const vNames = Object.keys(vs);
  const idx = order.indexOf(id);
  const total = order.length;
  return `<div class="data-card" id="card_experiences_${id}" data-list="experiences" data-idx="${idx}">
    <div class="data-card-header" onclick="toggleCard(this)">
      <span class="chevron">▸</span>
      <span class="title">${esc(exp.company || '(untitled)')}</span>
      <span class="sub">${esc(exp.role || '')}</span>
      <span class="sub">${esc(periodText(exp))}</span>
      ${grip("experiences", idx)}
    </div>
    <div class="data-card-body">
      <label class="field">Company</label>
      <input type="text" value="${escAttr(exp.company||'')}" data-field="company" data-kind="experiences" data-id="${id}">
      <div class="row">
        <div style="flex:1"><label class="field">Role</label>
          <input type="text" class="half" style="width:100%" value="${escAttr(exp.role||'')}" data-field="role" data-kind="experiences" data-id="${id}">
        </div>
        <div style="flex:1"><label class="field">Location</label>
          <input type="text" class="half" style="width:100%" value="${escAttr(exp.location||'')}" data-field="location" data-kind="experiences" data-id="${id}">
        </div>
      </div>
      ${periodEditor("experiences", id, exp)}

      <label class="field">Variants</label>
      ${vNames.map(vn => renderVariantBlock("experiences", id, vn, vs[vn] || [])).join("")}
      <button class="btn-sm accent" onclick="addVariant('experiences','${id}')" style="margin-top:4px">+ Variant</button>

      <div class="card-actions">
        <span></span>
        <button class="btn-sm danger" onclick="deleteCard('experiences','${id}')">Delete this experience</button>
      </div>
    </div>
  </div>`;
}

function renderProjCard(id, order, proj) {
  if (!proj) return "";
  const vs = proj.variants || {};
  const vNames = Object.keys(vs);
  const idx = order.indexOf(id);
  const total = order.length;
  return `<div class="data-card" id="card_projects_${id}" data-list="projects" data-idx="${idx}">
    <div class="data-card-header" onclick="toggleCard(this)">
      <span class="chevron">▸</span>
      <span class="title">${esc(proj.title || '(untitled)')}</span>
      <span class="sub">${esc(periodText(proj))}</span>
      ${grip("projects", idx)}
    </div>
    <div class="data-card-body">
      <label class="field">Title</label>
      <input type="text" value="${escAttr(proj.title||'')}" data-field="title" data-kind="projects" data-id="${id}">
      ${periodEditor("projects", id, proj)}

      <label class="field">Variants</label>
      ${vNames.map(vn => renderVariantBlock("projects", id, vn, vs[vn] || [])).join("")}
      <button class="btn-sm accent" onclick="addVariant('projects','${id}')" style="margin-top:4px">+ Variant</button>

      <div class="card-actions">
        <span></span>
        <button class="btn-sm danger" onclick="deleteCard('projects','${id}')">Delete this project</button>
      </div>
    </div>
  </div>`;
}

function renderEduCard(idx, total, edu) {
  if (!edu) return "";
  return `<div class="data-card" id="card_education_${idx}" data-list="education" data-idx="${idx}">
    <div class="data-card-header" onclick="toggleCard(this)">
      <span class="chevron">▸</span>
      <span class="title">${esc(edu.institution || '(untitled)')}</span>
      <span class="sub">${esc(edu.degree || '')}</span>
      <span class="sub">${esc(periodText(edu))}</span>
      ${grip("education", idx)}
    </div>
    <div class="data-card-body">
      <label class="field">Institution</label>
      <input type="text" value="${escAttr(edu.institution||'')}" data-edu-idx="${idx}" data-edu-field="institution">
      <label class="field">Degree</label>
      <input type="text" value="${escAttr(edu.degree||'')}" data-edu-idx="${idx}" data-edu-field="degree">
      ${periodEditor("education", idx, edu)}
      <label class="field">CGA</label>
      <input type="text" value="${escAttr(edu.cgpa||'')}" data-edu-idx="${idx}" data-edu-field="cgpa">
      <label class="field">Key Courses</label>
      <input type="text" value="${escAttr(edu.courses||'')}" data-edu-idx="${idx}" data-edu-field="courses">
      <label class="field">Awards &amp; Scholarships</label>
      <input type="text" value="${escAttr(edu.awards||'')}" data-edu-idx="${idx}" data-edu-field="awards">

      <div class="card-actions">
        <span></span>
        <button class="btn-sm danger" onclick="deleteEdu(${idx})">Delete this education</button>
      </div>
    </div>
  </div>`;
}

function bulletListKey(kind, id, v) { return ["bul", kind, id, encodeURIComponent(v)].join("|"); }

function renderVariantBlock(kind, id, vName, bullets) {
  const key = bulletListKey(kind, id, vName);
  const rows = (bullets.length ? bullets : [""]).map((text, i) => `
    <div class="bullet-row" data-list="${escAttr(key)}" data-idx="${i}">
      ${grip(key, i)}
      <span class="dot">•</span>
      <textarea class="bullet" rows="1" data-bk="${kind}" data-bid="${escAttr(id)}" data-bv="${escAttr(vName)}" data-bi="${i}"
        placeholder="One achievement per bullet">${esc(text)}</textarea>
      <button class="btn-sm danger" data-act="del-bullet" data-bk="${kind}" data-bid="${escAttr(id)}" data-bv="${escAttr(vName)}" data-bi="${i}"
        title="Delete bullet">−</button>
    </div>`).join("");
  return `<div class="variant-block">
    <div class="vr-head">
      <input type="text" value="${escAttr(vName)}" data-var-name="${escAttr(vName)}" data-kind="${kind}" data-id="${id}" placeholder="variant name">
      <button class="btn-sm danger" onclick="removeVariant('${kind}','${id}','${vName}')" ${Object.keys(editData[kind][id].variants).length<=1?"disabled":""}>Remove variant</button>
    </div>
    <div class="bullets">${rows}</div>
    <button class="btn-sm accent" data-act="add-bullet" data-bk="${kind}" data-bid="${escAttr(id)}" data-bv="${escAttr(vName)}" style="margin-top:6px">+ Bullet</button>
  </div>`;
}

function bulletsOf(kind, id, v) {
  const variants = editData[kind][id].variants;
  if (!Array.isArray(variants[v])) variants[v] = [];
  return variants[v];
}

function focusBullet(kind, id, v, i) {
  setTimeout(() => {
    const el = [...document.querySelectorAll("textarea.bullet")]
      .find(x => x.dataset.bk === kind && x.dataset.bid === id && x.dataset.bv === v && +x.dataset.bi === i);
    if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
  }, 0);
}
function addBullet(kind, id, v, at, text) {
  const arr = bulletsOf(kind, id, v);
  const i = at === undefined ? arr.length : at;
  arr.splice(i, 0, text || "");
  renderDataTab();
  focusBullet(kind, id, v, i);
}
function removeBullet(kind, id, v, i) {
  const arr = bulletsOf(kind, id, v);
  arr.splice(i, 1);
  renderDataTab();
  if (arr.length) focusBullet(kind, id, v, Math.max(0, i - 1));
}

// ---- Period editor: month + year pickers instead of free text ----
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
function parseYM(s) {
  const m = /^(\d{4})-(\d{2})$/.exec(String(s || ""));
  return m ? { y: +m[1], m: +m[2] } : null;
}
const toYM = (y, m) => `${String(y).padStart(4, "0")}-${String(m).padStart(2, "0")}`;
function periodText(it) {
  const s = parseYM(it.start);
  if (!s) return it.period || "";
  const e = it.end === "present" ? "Present" : (parseYM(it.end) ? `${MONTHS[parseYM(it.end).m - 1]} ${parseYM(it.end).y}` : "");
  return `${MONTHS[s.m - 1]} ${s.y}` + (e ? ` – ${e}` : "");
}
function periodEditor(scope, key, it) {
  const s = parseYM(it.start);
  const present = it.end === "present";
  const e = present ? null : parseYM(it.end);
  const nowY = new Date().getFullYear();
  const mSel = (part, v, dis) => `<select data-pe="${scope}|${key}|${part}-m" ${dis ? "disabled" : ""} aria-label="${part} month">
      <option value="" disabled ${v ? "" : "selected"}>Month</option>${MONTHS.map((n, i) => `<option value="${i + 1}" ${v && v.m === i + 1 ? "selected" : ""}>${n}</option>`).join("")}</select>`;
  const ySel = (part, v, dis) => {
    const hi = Math.max(nowY + 6, v ? v.y : 0), lo = Math.min(2005, v ? v.y : 9999);
    let o = `<option value="" disabled ${v ? "" : "selected"}>Year</option>`;
    for (let y = hi; y >= lo; y--) o += `<option value="${y}" ${v && v.y === y ? "selected" : ""}>${y}</option>`;
    return `<select data-pe="${scope}|${key}|${part}-y" ${dis ? "disabled" : ""} aria-label="${part} year">${o}</select>`;
  };
  let note = "";
  if (!s && it.period) note = `<div class="pe-note">Couldn't read the old text "${esc(it.period)}" — pick the dates to replace it.</div>`;
  else if (s && e && toYM(e.y, e.m) < toYM(s.y, s.m)) note = `<div class="pe-note warn">End date is before the start date.</div>`;
  return `<label class="field">Period</label>
    <div class="period-row">
      <span class="pe-tag">From</span>${mSel("start", s)}${ySel("start", s)}
      <span class="pe-tag">To</span>${mSel("end", e, present)}${ySel("end", e, present)}
      <label class="pe-present"><input type="checkbox" class="switch" data-pe="${scope}|${key}|present" ${present ? "checked" : ""}> Present</label>
      <span class="pe-preview">${esc(periodText(it)) || "—"}</span>
    </div>${note}`;
}

function esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function escAttr(s) {
  return String(s).replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// ---- Data tab events (delegated from dataContent) ----
document.getElementById("dataContent").addEventListener("input", function(e) {
  const t = e.target;
  if (t.dataset.personalField) {
    if (!editData.personal) editData.personal = {};
    editData.personal[t.dataset.personalField] = t.value;
  }
  if (t.dataset.field) {
      editData[t.dataset.kind][t.dataset.id][t.dataset.field] = t.value;
  }
  if (t.dataset.eduIdx !== undefined) {
    const idx = parseInt(t.dataset.eduIdx);
    const field = t.dataset.eduField;
    if (editData.education[idx]) editData.education[idx][field] = t.value;
  }
  if (t.dataset.skillKey !== undefined) {
    const idx = parseInt(t.dataset.skillKey);
    const entries = Object.entries(editData.skills || {});
    if (idx >= 0 && idx < entries.length) {
      entries[idx][0] = t.value.trim() || entries[idx][0];
      editData.skills = Object.fromEntries(entries);
    }
  }
  if (t.dataset.skillVal !== undefined) {
    const idx = parseInt(t.dataset.skillVal);
    const entries = Object.entries(editData.skills || {});
    if (idx >= 0 && idx < entries.length) {
      entries[idx][1] = t.value;
      editData.skills = Object.fromEntries(entries);
    }
  }
  if (t.dataset.varName) {
    // variant name change
    const section = editData[t.dataset.kind][t.dataset.id];
    const oldName = t.dataset.varName;
    const newName = t.value.trim();
    if (newName && newName !== oldName && section.variants[oldName] !== undefined) {
      section.variants[newName] = section.variants[oldName];
      delete section.variants[oldName];
      t.dataset.varName = newName;
    }
  }
  if (t.classList.contains("bullet")) {
    bulletsOf(t.dataset.bk, t.dataset.bid, t.dataset.bv)[+t.dataset.bi] = t.value;
    autosize(t);
  }
});

function toggleCard(header) {
  header.parentElement.classList.toggle("open");
  autosizeAll();
}

function autosize(el) { el.style.height = "auto"; el.style.height = el.scrollHeight + 2 + "px"; }
function autosizeAll() { document.querySelectorAll("#dataContent textarea.bullet").forEach(autosize); }

const dataEl = document.getElementById("dataContent");

dataEl.addEventListener("change", e => {
  const t = e.target;
  if (t.dataset.varName !== undefined) { renderDataTab(); return; }   // variant renamed: refresh bullet keys
  const pe = t.dataset.pe;
  if (!pe) return;
  const [scope, key, part] = pe.split("|");
  const it = scope === "education" ? editData.education[+key] : editData[scope][key];
  if (!it) return;
  const now = new Date();
  if (part === "present") {
    it.end = t.checked ? "present" : (it.start || toYM(now.getFullYear(), now.getMonth() + 1));
  } else {
    const [which, field] = part.split("-");
    const cur = (which === "end" && it.end === "present") ? null : parseYM(it[which]);
    if (!t.value) { delete it[which]; }
    else {
      const v = cur || { m: 1, y: now.getFullYear() };
      if (field === "m") { v.m = +t.value; if (!cur) v.y = now.getFullYear(); }
      else { v.y = +t.value; if (!cur) v.m = 1; }
      it[which] = toYM(v.y, v.m);
    }
  }
  renderDataTab();
});

dataEl.addEventListener("click", e => {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  const { bk, bid, bv, bi } = b.dataset;
  if (b.dataset.act === "add-bullet") addBullet(bk, bid, bv);
  if (b.dataset.act === "del-bullet") removeBullet(bk, bid, bv, +bi);
});

// Enter = next bullet, Backspace on an empty bullet = delete it, pasted lines = separate bullets.
dataEl.addEventListener("keydown", e => {
  const t = e.target;
  if (!t.classList || !t.classList.contains("bullet")) return;
  const { bk, bid, bv } = t.dataset, i = +t.dataset.bi;
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    const pos = t.selectionStart, rest = t.value.slice(pos);
    bulletsOf(bk, bid, bv)[i] = t.value.slice(0, pos);
    addBullet(bk, bid, bv, i + 1, rest);
  } else if (e.key === "Backspace" && t.value === "" && bulletsOf(bk, bid, bv).length > 1) {
    e.preventDefault();
    removeBullet(bk, bid, bv, i);
  }
});
dataEl.addEventListener("paste", e => {
  const t = e.target;
  if (!t.classList || !t.classList.contains("bullet")) return;
  const text = (e.clipboardData || window.clipboardData).getData("text");
  if (!/\r?\n/.test(text.trim())) return;
  e.preventDefault();
  const lines = text.split(/\r?\n/).map(l => l.replace(/^\s*(?:[-•*·]|\d+[.)])\s*/, "").trim()).filter(Boolean);
  const { bk, bid, bv } = t.dataset, i = +t.dataset.bi;
  const arr = bulletsOf(bk, bid, bv);
  const before = t.value.slice(0, t.selectionStart), after = t.value.slice(t.selectionEnd);
  lines[0] = before + lines[0];
  lines[lines.length - 1] += after;
  arr.splice(i, 1, ...lines);
  renderDataTab();
  focusBullet(bk, bid, bv, i + lines.length - 1);
  toast(`Split into ${lines.length} bullets`);
});

function addVariant(kind, id) {
  const section = editData[kind][id];
  let n = Object.keys(section.variants).length + 1;
  let name = `v${n}`;
  while (section.variants[name] !== undefined) { n++; name = `v${n}`; }
  section.variants[name] = [];
  renderDataTab();
  // Reopen the card
  const card = document.getElementById(`card_${kind}_${id}`);
  if (card) card.classList.add("open");
}

function removeVariant(kind, id, vName) {
  const section = editData[kind][id];
  if (Object.keys(section.variants).length <= 1) {
    toast("Cannot remove the last variant");
    return;
  }
  delete section.variants[vName];
  renderDataTab();
  const card = document.getElementById(`card_${kind}_${id}`);
  if (card) card.classList.add("open");
}

function deleteCard(kind, id) {
  const section = editData[kind][id];
  const name = section ? (section.company || section.title || id) : id;
  if (!confirm(`Delete "${name}"? This will also remove it from all saved profiles.`)) return;
  delete editData[kind][id];
  const order = getOrder(kind);
  const idx = order.indexOf(id);
  if (idx >= 0) order.splice(idx, 1);
  renderDataTab();
}

function deleteEdu(idx) {
  const edu = editData.education[idx];
  const name = edu ? (edu.institution || 'untitled') : 'untitled';
  if (!confirm(`Delete education "${name}"?`)) return;
  editData.education.splice(idx, 1);
  renderDataTab();
}

function addSkill() {
  if (!editData.skills) editData.skills = {};
  let n = Object.keys(editData.skills).length + 1;
  let key = `category_${n}`;
  while (editData.skills[key] !== undefined) { n++; key = `category_${n}`; }
  editData.skills[key] = "";
  renderDataTab();
}

function removeSkill(idx) {
  const entries = Object.entries(editData.skills || {});
  if (idx < 0 || idx >= entries.length) return;
  entries.splice(idx, 1);
  editData.skills = Object.fromEntries(entries);
  renderDataTab();
}

function addNew(kind) {
  if (kind === "educations") {
    if (!editData.education) editData.education = [];
    const suffix = Date.now().toString(36).slice(-4);
    editData.education.push({
      id: `new_edu_${suffix}`,
      institution: "", period: "", degree: "", cgpa: "", courses: "", awards: ""
    });
    renderDataTab();
    setTimeout(() => {
      const card = document.getElementById(`card_education_${editData.education.length - 1}`);
      if (card) { card.classList.add("open"); card.scrollIntoView({ behavior: "smooth", block: "center" }); }
    }, 100);
    return;
  }
  const id = "_" + Date.now().toString(36);
  if (kind === "experiences") {
    editData.experiences[id] = {
      company: "", role: "", location: "", period: "", variants: { v1: [] }
    };
  } else {
    editData.projects[id] = {
      title: "", period: "", variants: { v1: [] }
    };
  }
  editData._order[kind].push(id);
  renderDataTab();
  setTimeout(() => {
    const card = document.getElementById(`card_${kind}_${id}`);
    if (card) { card.classList.add("open"); card.scrollIntoView({ behavior: "smooth", block: "center" }); }
  }, 100);
}

function cleanForSave(d) {
  const out = JSON.parse(JSON.stringify(d));
  const tidy = it => {
    if (it.start) delete it.period;                 // structured dates replace legacy text
    if (it.variants) Object.keys(it.variants).forEach(v => {
      it.variants[v] = (it.variants[v] || []).map(s => s.trim()).filter(Boolean);
    });
  };
  (out.education || []).forEach(tidy);
  Object.values(out.experiences || {}).forEach(tidy);
  Object.values(out.projects || {}).forEach(tidy);
  return out;
}

function saveData() {
  const clean = cleanForSave(editData);
  const payload = {
    education: clean.education || [],
    experiences: clean.experiences || {},
    projects: clean.projects || {},
    skills: clean.skills || {},
    personal: clean.personal || {},
    order: { experiences: getOrder("experiences").slice(), projects: getOrder("projects").slice() }
  };
  toast("Saving…");
  fetch("/api/save_data", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  }).then(r => r.json())
    .then(resp => {
      if (resp.ok) {
        toast("Saved to cv_data.yaml. Reloading…");
        setTimeout(() => location.reload(), 600);
      } else {
        toast("Save failed");
      }
    }).catch(() => toast("Save failed"));
}

// ====================== Shared ======================
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 1800);
}

// ====================== Boot ======================
initBuildState();
renderBuild();
refreshPreview();
populateProfiles(window.__BOOT.profiles);


// ====================== Drag to reorder ======================
// Rows/cards opt in with data-list + data-idx and contain a .grip handle.
// Only the grip arms dragging, so text selection inside inputs keeps working.
function gripSvg() {
  return '<svg width="10" height="16" viewBox="0 0 10 16" aria-hidden="true">' +
    [3,8,13].map(y => `<circle cx="2.5" cy="${y}" r="1.3"/><circle cx="7.5" cy="${y}" r="1.3"/>`).join("") + '</svg>';
}

function grip(list, idx) {
  return `<button class="grip" type="button" title="拖动调整顺序(也可聚焦后按 ↑/↓)" aria-label="Reorder"
    data-grip="${list}" data-gidx="${idx}" onclick="event.stopPropagation()">${gripSvg()}</button>`;
}

function sectionHead(title, addKind) {
  return `<div class="section-head"><div class="section-title">${title}</div>` +
    (addKind ? `<button class="btn-sm accent" onclick="addNew('${addKind}')">+ Add</button>` : "") + `</div>`;
}

function reorder(list, from, to) {
  if (from === to || from < 0 || to < 0) return;
  const move = arr => { const [x] = arr.splice(from, 1); arr.splice(to, 0, x); };
  if (list === "exp") { move(expItems); renderBuild(); refreshPreview(); }
  else if (list === "proj") { move(projItems); renderBuild(); refreshPreview(); }
  else if (list === "education") { move(editData.education); renderDataTab(); }
  else if (list.startsWith("bul|")) {
    const [, kind, id, v] = list.split("|");
    move(bulletsOf(kind, id, decodeURIComponent(v))); renderDataTab();
  }
  else { move(getOrder(list)); renderDataTab(); }
}
function listLength(list) {
  if (list === "exp") return expItems.length;
  if (list === "proj") return projItems.length;
  if (list === "education") return (editData.education || []).length;
  if (list.startsWith("bul|")) { const [, kind, id, v] = list.split("|"); return bulletsOf(kind, id, decodeURIComponent(v)).length; }
  return getOrder(list).length;
}

let drag = null;   // { list, from, to }
function clearDropMarks() {
  document.querySelectorAll(".drop-before, .drop-after").forEach(el => el.classList.remove("drop-before", "drop-after"));
}

document.addEventListener("pointerdown", e => {
  const g = e.target.closest(".grip");
  const row = g && g.closest("[data-list]");
  if (row) row.draggable = true;
});
document.addEventListener("pointerup", () => {
  document.querySelectorAll("[data-list][draggable=true]").forEach(r => { if (!drag) r.draggable = false; });
});
document.addEventListener("dragstart", e => {
  const row = e.target.closest && e.target.closest("[data-list]");
  if (!row || !row.draggable) return;
  drag = { list: row.dataset.list, from: parseInt(row.dataset.idx, 10), to: -1 };
  row.classList.add("dragging");
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", "cv-row");
  const handle = row.querySelector(".data-card-header");   // small ghost for tall cards
  if (handle) e.dataTransfer.setDragImage(handle, 24, 20);
});
document.addEventListener("dragover", e => {
  if (!drag) return;
  const row = e.target.closest && e.target.closest(`[data-list="${drag.list}"]`);
  if (!row) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "move";
  const rect = (row.querySelector(".data-card-header") || row).getBoundingClientRect();
  const after = e.clientY > rect.top + rect.height / 2;
  clearDropMarks();
  row.classList.add(after ? "drop-after" : "drop-before");
  let to = parseInt(row.dataset.idx, 10) + (after ? 1 : 0);
  if (drag.from < to) to--;
  drag.to = to;
});
document.addEventListener("drop", e => {
  if (!drag) return;
  e.preventDefault();
  const { list, from, to } = drag;
  endDrag();
  reorder(list, from, to);
});
document.addEventListener("dragend", endDrag);
function endDrag() {
  clearDropMarks();
  document.querySelectorAll(".dragging").forEach(el => el.classList.remove("dragging"));
  document.querySelectorAll("[data-list][draggable=true]").forEach(r => { r.draggable = false; });
  drag = null;
}

// Keyboard: focus a grip, then ↑/↓ moves the row.
document.addEventListener("keydown", e => {
  const g = e.target.closest && e.target.closest(".grip");
  if (!g || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
  e.preventDefault();
  const list = g.dataset.grip, from = parseInt(g.dataset.gidx, 10);
  const to = from + (e.key === "ArrowUp" ? -1 : 1);
  if (to < 0 || to >= listLength(list)) return;
  reorder(list, from, to);
  const again = document.querySelector(`[data-list="${list}"][data-idx="${to}"] .grip`);
  if (again) again.focus();
});

// Inside the desktop window the OS close button quits the app, so hide the in-page Quit button.
window.addEventListener("pywebviewready", () => {
  const q = document.getElementById("btnQuit");
  if (q) q.style.display = "none";
});


// Native title bar follows the app theme (Windows desktop window only).
function syncTitlebar() {
  const api = nativeApi();
  if (!api || !api.set_titlebar) return;
  const cs = getComputedStyle(document.documentElement);
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  api.set_titlebar(dark, cs.getPropertyValue("--bar").trim(), cs.getPropertyValue("--label").trim()).catch(() => {});
}
window.addEventListener("pywebviewready", syncTitlebar);
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", syncTitlebar);

document.getElementById("autoToggle").checked = autoRefresh;


// ====================== Apple-style pop-up menu for <select> ======================
// The native option list ignores our theme (unreadable in dark mode), so every <select> opens this
// menu instead. The real <select> stays in the DOM and receives the value + a "change" event,
// so all existing handlers keep working.
(function () {
  let menu = null, owner = null, items = [], active = -1, typed = "", typedTimer = null;

  function highlight(i, scroll) {
    items.forEach((el, k) => el.classList.toggle("active", k === i));
    active = i;
    if (scroll && items[i]) items[i].scrollIntoView({ block: "nearest" });
  }
  function closeMenu(refocus) {
    if (!menu) return;
    menu.remove();
    const o = owner;
    menu = owner = null; items = []; active = -1;
    if (o) o.classList.remove("open");
    window.removeEventListener("resize", onDismiss);
    document.removeEventListener("scroll", onScroll, true);
    window.removeEventListener("blur", onDismiss);
    if (refocus && o && document.contains(o)) o.focus();
  }
  function onDismiss() { closeMenu(false); }
  function onScroll(e) { if (menu && !menu.contains(e.target)) closeMenu(false); }

  function choose(i) {
    const sel = owner;
    if (!sel || !sel.options[i] || sel.options[i].disabled) return;
    const changed = sel.selectedIndex !== i;
    closeMenu(true);
    if (changed) {
      sel.selectedIndex = i;
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  function openMenu(sel) {
    if (sel.disabled) return;
    closeMenu(false);
    owner = sel;
    sel.classList.add("open");
    menu = document.createElement("div");
    menu.className = "menu";
    menu.setAttribute("role", "listbox");
    [...sel.options].forEach((opt, i) => {
      const el = document.createElement("div");
      el.className = "menu-item" + (opt.disabled ? " disabled" : "") + (i === sel.selectedIndex ? " selected" : "");
      el.setAttribute("role", "option");
      el.dataset.i = i;
      el.innerHTML = '<span class="chk">✓</span><span class="lbl"></span>';
      el.lastChild.textContent = opt.textContent;
      menu.appendChild(el);
      items.push(el);
    });
    document.body.appendChild(menu);

    const r = sel.getBoundingClientRect();
    menu.style.minWidth = Math.max(r.width, 120) + "px";
    let mh = menu.offsetHeight;
    const mw = menu.offsetWidth;
    const room = window.innerHeight - r.bottom - 12;
    let top;
    if (mh <= room || room >= r.top - 12) {           // fits below (or below has more space)
      top = r.bottom + 4;
      if (mh > room) { menu.style.maxHeight = Math.max(120, room) + "px"; }
    } else {                                          // flip above
      const above = r.top - 12;
      if (mh > above) { menu.style.maxHeight = Math.max(120, above) + "px"; mh = menu.offsetHeight; }
      top = r.top - mh - 4;
      menu.style.transformOrigin = "bottom left";
    }
    const left = Math.max(8, Math.min(r.left, window.innerWidth - mw - 8));
    menu.style.top = top + "px";
    menu.style.left = left + "px";

    highlight(sel.selectedIndex, true);
    menu.addEventListener("mousemove", e => {
      const el = e.target.closest(".menu-item");
      if (el && !el.classList.contains("disabled")) highlight(+el.dataset.i, false);
    });
    menu.addEventListener("mousedown", e => e.preventDefault());
    menu.addEventListener("click", e => {
      const el = e.target.closest(".menu-item");
      if (el) choose(+el.dataset.i);
    });
    window.addEventListener("resize", onDismiss);
    window.addEventListener("blur", onDismiss);
    document.addEventListener("scroll", onScroll, true);
  }

  // Open on mouse press (capture, so we win over the native popup).
  document.addEventListener("mousedown", e => {
    const sel = e.target.closest && e.target.closest("select");
    if (sel) {
      e.preventDefault();
      sel.focus();
      if (menu && owner === sel) closeMenu(false); else openMenu(sel);
      return;
    }
    if (menu && !menu.contains(e.target)) closeMenu(false);
  }, true);

  document.addEventListener("keydown", e => {
    if (menu) {                                        // navigating the open menu
      const n = items.length;
      const step = dir => {
        let i = active;
        for (let k = 0; k < n; k++) {
          i = (i + dir + n) % n;
          if (!items[i].classList.contains("disabled")) return i;
        }
        return active;
      };
      if (e.key === "ArrowDown") { e.preventDefault(); highlight(step(1), true); }
      else if (e.key === "ArrowUp") { e.preventDefault(); highlight(step(-1), true); }
      else if (e.key === "Home") { e.preventDefault(); highlight(0, true); }
      else if (e.key === "End") { e.preventDefault(); highlight(n - 1, true); }
      else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(active); }
      else if (e.key === "Escape") { e.preventDefault(); closeMenu(true); }
      else if (e.key === "Tab") { closeMenu(false); }
      else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {   // type-ahead
        typed += e.key.toLowerCase();
        clearTimeout(typedTimer); typedTimer = setTimeout(() => { typed = ""; }, 700);
        const hit = items.findIndex(el => el.textContent.replace("✓", "").trim().toLowerCase().startsWith(typed));
        if (hit >= 0) highlight(hit, true);
      }
      e.stopPropagation();
      return;
    }
    const sel = e.target.closest && e.target.closest("select");
    if (sel && !sel.disabled && ["ArrowDown", "ArrowUp", "Enter", " ", "F4"].includes(e.key)) {
      e.preventDefault();
      openMenu(sel);
    }
  }, true);
})();
