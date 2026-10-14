// Page-side scripts for PlaywrightAdapter. Loaded once by playwright_adapter.py.
// Exposed as a single object literal so both functions travel in one file.
({
  snapshot: (args) => {
  const REF = args.refAttr, MAX = args.maxElements;
  const out = { url: location.href, title: document.title, text: "", elements: [] };
  const body = document.body;
  out.text = body ? (body.innerText || "").slice(0, args.maxText) : "";
  let counter = Number(document.documentElement.getAttribute(REF + "-counter") || 0);
  const refOf = (el) => {
    let ref = el.getAttribute(REF);
    if (!ref) { counter += 1; ref = "e" + counter; el.setAttribute(REF, ref); }
    return ref;
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return false;
    const s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "none";
  };
  const label = (el) => {
    const aria = el.getAttribute("aria-label");
    if (aria) return aria.trim();
    if (el.labels && el.labels.length) return (el.labels[0].innerText || "").trim();
    const ph = el.getAttribute("placeholder");
    if (ph) return ph.trim();
    const t = (el.innerText || el.value || el.getAttribute("title") || "").trim();
    return t.slice(0, 200);
  };
  const roleOf = (el) => {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === "a") return "link";
    if (tag === "button") return "button";
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    if (tag === "input") {
      const type = (el.getAttribute("type") || "text").toLowerCase();
      if (type === "checkbox" || type === "radio" || type === "submit" || type === "button") return type;
      return "textbox";
    }
    return tag;
  };
  const rowIndexOf = (el) => {
    const tr = el.closest("tr,[role='row']");
    if (!tr) return null;
    const tbl = tr.closest("table,[role='grid'],[role='table'],[role='treegrid']");
    if (!tbl) return null;
    const rows = Array.from(tbl.querySelectorAll("tr,[role='row']")).filter(r => r.closest("table,[role='grid'],[role='table'],[role='treegrid']") === tbl);
    const dataRows = rows.filter(r => !r.querySelector("th,[role='columnheader']"));
    const i = dataRows.indexOf(tr);
    return i >= 0 ? i + 1 : null;
  };

  const disabled = (el) => el.disabled === true || el.getAttribute("aria-disabled") === "true" || !!el.closest("[aria-disabled='true'],.disabled,.ant-pagination-disabled,.is-disabled");
  const seen = new Set();
  const pushElement = (item) => {
    if (out.elements.length >= MAX) return;
    if (seen.has(item.ref)) return;
    seen.add(item.ref);
    out.elements.push(item);
  };
  const collectInteractive = (root, frameIndex) => {
    const interactive = root.querySelectorAll(
      "a[href],button,input,select,textarea,[role='button'],[role='link'],[role='tab'],[role='menuitem'],[role='option'],[role='checkbox'],[onclick],[contenteditable='true']"
    );
    for (const el of interactive) {
      if (out.elements.length >= MAX) break;
      if (!visible(el) || disabled(el)) continue;
      const item = { ref: "@" + refOf(el), role: roleOf(el), text: label(el) };
      if (frameIndex) item.frame_index = frameIndex;
      const name = el.getAttribute("name"); if (name) item.name = name;
      const title = el.getAttribute("title"); if (title) item.title = title;
      const aria = el.getAttribute("aria-label"); if (aria) item.aria_label = aria;
      if (el.tagName.toLowerCase() === "a") item.href = el.href;
      if ("value" in el && typeof el.value === "string" && el.type !== "password") item.value = el.value.slice(0, 200);
      const dl = el.getAttribute("download"); if (dl !== null) item.filename = dl || (item.href || "").split("/").pop();
      const row = rowIndexOf(el); if (row !== null) item.row_index = row;
      pushElement(item);
    }
    const extraDownload = root.querySelectorAll(
      "[download], a[href*='.pdf' i], a[href*='download' i], span[role='button'], div[role='button']"
    );
    for (const el of extraDownload) {
      if (out.elements.length >= MAX) break;
      if (!visible(el) || disabled(el)) continue;
      const ref = "@" + refOf(el);
      if (seen.has(ref)) continue;
      const item = { ref, role: roleOf(el), text: label(el) };
      if (frameIndex) item.frame_index = frameIndex;
      const title = el.getAttribute("title"); if (title) item.title = title;
      const aria = el.getAttribute("aria-label"); if (aria) item.aria_label = aria;
      if (el.tagName.toLowerCase() === "a") item.href = el.href;
      const dl = el.getAttribute("download");
      if (dl !== null) item.filename = dl || (item.href || "").split("/").pop();
      pushElement(item);
    }
  };
  const collectStamped = (root, frameIndex) => {
    const stamped = root.querySelectorAll("[" + REF + "]");
    for (const el of stamped) {
      if (out.elements.length >= MAX) break;
      if (!visible(el)) continue;
      const attr = el.getAttribute(REF);
      if (!attr) continue;
      const item = { ref: "@" + attr, role: roleOf(el), text: label(el) };
      if (frameIndex) item.frame_index = frameIndex;
      if ("value" in el && typeof el.value === "string" && el.type !== "password") {
        item.value = el.value.slice(0, 200);
      }
      pushElement(item);
    }
  };
  collectInteractive(document, 0);
  collectStamped(document, 0);
  let frameIndex = 1;
  for (const iframe of document.querySelectorAll("iframe")) {
    if (!visible(iframe)) continue;
    let doc = null;
    try { doc = iframe.contentDocument; } catch (_e) { doc = null; }
    if (doc && doc.body) {
      collectInteractive(doc, frameIndex);
      collectStamped(doc, frameIndex);
      frameIndex += 1;
    }
    const rawSrc = (iframe.getAttribute("src") || iframe.src || "").trim();
    if (!rawSrc || rawSrc === "about:blank") continue;
    let abs = rawSrc;
    try { abs = new URL(rawSrc, location.href).href; } catch (_e) { continue; }
    const title = (iframe.getAttribute("title") || iframe.getAttribute("aria-label") || "PDF预览").trim();
    const pdfLike = /\.pdf(\?|#|$)/i.test(abs) || /pdf/i.test(title) || /pdf/i.test(rawSrc);
    if (!pdfLike) continue;
    const stub = document.createElement("a");
    stub.href = abs;
    stub.setAttribute("download", "");
    stub.style.cssText = "position:fixed;left:-9999px;width:1px;height:1px;opacity:0;pointer-events:none";
    document.body.appendChild(stub);
    const item = {
      ref: "@" + refOf(stub),
      role: "link",
      text: title.slice(0, 200) || "PDF预览",
      href: abs,
      filename: abs.split("/").pop().split("?")[0] || "preview.pdf",
      iframe_preview: true,
    };
    pushElement(item);
  }

  const TABLE_SEL = "table,[role='grid'],[role='table'],[role='treegrid']";
  const cellText = (c) => (c.innerText || "").trim().replace(/\s+/g, " ");
  const isHeaderCell = (c) => c.tagName.toLowerCase() === "th" || c.getAttribute("role") === "columnheader";
  // Read one table into { headers, rows }. Nested tables belong to their own element.
  const readTable = (tbl) => {
    const rows = Array.from(tbl.querySelectorAll("tr,[role='row']")).filter(r => r.closest(TABLE_SEL) === tbl);
    const headers = [];
    const data = [];
    for (const tr of rows) {
      const cells = Array.from(tr.children).filter(c => /^(td|th)$/i.test(c.tagName) || ["cell","gridcell","columnheader","rowheader"].includes(c.getAttribute("role")));
      if (!cells.length) continue;
      const texts = cells.map(cellText);
      if (cells.every(isHeaderCell) || (tr.closest("thead") && !tr.closest("tbody"))) {
        if (!headers.length) headers.push(...texts.map(t => t.slice(0, 200)));
        continue;
      }
      if (data.length >= args.maxRows) break;
      data.push(texts.map(t => t.slice(0, 500)));
    }
    return { headers, rows: data };
  };
  // Caption or the nearest heading-like text above the table, so the user can tell tables apart.
  const tableTitle = (tbl) => {
    const cap = tbl.querySelector("caption");
    if (cap && cellText(cap)) return cellText(cap).slice(0, 100);
    let node = tbl;
    for (let hops = 0; node && hops < 6; hops += 1) {
      let sib = node.previousElementSibling;
      for (let n = 0; sib && n < 4; n += 1) {
        if (!sib.matches(TABLE_SEL) && !sib.querySelector(TABLE_SEL)) {
          const h = sib.matches("h1,h2,h3,h4,h5,h6,legend,[class*='title'],[class*='header']") ? sib : sib.querySelector("h1,h2,h3,h4,h5,h6,legend,[class*='title'],[class*='header']");
          const t = h ? cellText(h) : (sib.children.length <= 2 ? cellText(sib) : "");
          if (t && t.length <= 60) return t;
        }
        sib = sib.previousElementSibling;
      }
      node = node.parentElement;
    }
    return "";
  };
  const allTables = Array.from(document.querySelectorAll(TABLE_SEL)).filter(t => visible(t) && !t.parentElement.closest(TABLE_SEL));
  out.tables = [];
  let pending = null;  // header-only table waiting for its body table (element-ui / antd split tables)
  for (const tbl of allTables) {
    if (out.tables.length >= args.maxTables) break;
    const read = readTable(tbl);
    let title = "";
    if (pending && !read.headers.length && read.rows.length) {
      read.headers = pending.headers;
      title = pending.title;
      pending = null;
    } else if (read.headers.length && !read.rows.length) {
      pending = { headers: read.headers, title: tableTitle(tbl) };
      continue;
    }
    if (!read.rows.length) continue;
    const width = Math.max(read.headers.length, ...read.rows.map(r => r.length));
    if (width < 2) continue;
    out.tables.push({ index: out.tables.length, title: title || tableTitle(tbl), headers: read.headers, rows: read.rows });
  }
  // Legacy: the first table also goes out as columnheader/cell elements for list-mode templates.
  const first = out.tables[0];
  if (first) {
    first.headers.forEach((text, col) => { if (out.elements.length < MAX) out.elements.push({ role: "columnheader", column_index: col, text: text, table_index: 0 }); });
    first.rows.forEach((row, r) => row.forEach((text, col) => { if (out.elements.length < MAX) out.elements.push({ role: "cell", row_index: r + 1, column_index: col, text: text, table_index: 0 }); }));
  }
  let crossOriginIframes = 0;
  for (const iframe of document.querySelectorAll("iframe")) {
    try {
      if (!iframe.contentDocument || !iframe.contentDocument.body) crossOriginIframes += 1;
    } catch (_e) { crossOriginIframes += 1; }
  }
  out.meta = { cross_origin_iframes: crossOriginIframes };
  document.documentElement.setAttribute(REF + "-counter", String(counter));
  return out;
},
  find: (args) => {
  const REF = args.refAttr;
  let counter = Number(document.documentElement.getAttribute(REF + "-counter") || 0);
  let ref = args.el.getAttribute(REF);
  if (!ref) { counter += 1; ref = "e" + counter; args.el.setAttribute(REF, ref);
              document.documentElement.setAttribute(REF + "-counter", String(counter)); }
  const el = args.el;
  const disabled = el.disabled === true || el.getAttribute("aria-disabled") === "true" || !!el.closest("[aria-disabled='true'],.disabled,.ant-pagination-disabled,.is-disabled");
  return { ref: "@" + ref, text: (el.innerText || el.value || "").trim().slice(0, 200), tag: el.tagName.toLowerCase(), disabled: disabled };
},
  startExpandClickRecording: () => {
  window.__ubsRecordedClicks = [];
  const docs = [document];
  for (const iframe of document.querySelectorAll("iframe")) {
    try {
      if (iframe.contentDocument) docs.push(iframe.contentDocument);
    } catch (_e) { /* cross-origin */ }
  }
  const handler = (e) => {
    const el = e.target && e.target.closest
      ? e.target.closest("button,a,[role='button'],[role='tab'],[role='link'],[role='menuitem']")
      : null;
    if (!el) return;
    const label = (el.getAttribute("aria-label") || el.innerText || el.getAttribute("title") || "")
      .trim().replace(/\s+/g, " ").slice(0, 60);
    if (!label) return;
    const folded = label.toLowerCase();
    const list = window.__ubsRecordedClicks;
    const last = list[list.length - 1];
    if (last && last.toLowerCase() === folded) return;
    list.push(label);
  };
  window.__ubsExpandClickHandler = handler;
  window.__ubsExpandClickDocs = docs;
  for (const doc of docs) doc.addEventListener("click", handler, true);
  return { started: true, frames: docs.length };
},
  stopExpandClickRecording: () => {
  const handler = window.__ubsExpandClickHandler;
  const docs = window.__ubsExpandClickDocs || [document];
  if (handler) {
    for (const doc of docs) {
      try { doc.removeEventListener("click", handler, true); } catch (_e) {}
    }
  }
  window.__ubsExpandClickHandler = null;
  window.__ubsExpandClickDocs = null;
  const clicks = Array.isArray(window.__ubsRecordedClicks) ? window.__ubsRecordedClicks.slice() : [];
  window.__ubsRecordedClicks = [];
  return { clicks };
},
  startFieldPickRecording: (args) => {
  const REF = args.refAttr;
  let counter = Number(document.documentElement.getAttribute(REF + "-counter") || 0);
  const refOf = (el) => {
    let ref = el.getAttribute(REF);
    if (!ref) {
      counter += 1;
      ref = "e" + counter;
      el.setAttribute(REF, ref);
      document.documentElement.setAttribute(REF + "-counter", String(counter));
    }
    return ref;
  };
  const guessLabel = (el) => {
    const td = el.closest("td,[role='cell']");
    if (td) {
      const row = td.closest("tr,[role='row']");
      if (row) {
        const cells = Array.from(row.children);
        const idx = cells.indexOf(td);
        if (idx > 0) {
          const prev = cells[idx - 1];
          const t = (prev.innerText || "").trim().replace(/\s+/g, " ");
          if (t && t.length <= 40 && !/^\d+$/.test(t)) return t.replace(/[:：]\s*$/, "");
        }
      }
    }
    const dd = el.closest("dd");
    if (dd && dd.previousElementSibling) {
      const dt = dd.previousElementSibling;
      if (dt.tagName && dt.tagName.toLowerCase() === "dt") {
        return (dt.innerText || "").trim().replace(/[:：]\s*$/, "");
      }
    }
    const labelled = el.getAttribute("aria-labelledby");
    if (labelled) {
      const lab = document.getElementById(labelled);
      if (lab) return (lab.innerText || "").trim().replace(/[:：]\s*$/, "");
    }
    return "";
  };
  const valueText = (el) => {
    const raw = (el.innerText || el.value || el.getAttribute("value") || "").trim().replace(/\s+/g, " ");
    return raw.slice(0, 200);
  };
  const pickTarget = (target) => {
    if (!target || target.nodeType !== 1) return null;
    const skip = target.closest("button,a,[role='button'],[role='tab'],script,style");
    if (skip && skip !== target) {
      const t = valueText(skip);
      if (t.length <= 24) return pickTarget(skip.parentElement);
    }
    const el = target.closest("td,dd,span,div,p,li,label,[role='cell'],[data-testid]") || target;
    const text = valueText(el);
    if (!text || text.length < 1) return null;
    return el;
  };
  window.__ubsFieldPicks = [];
  const docFrames = [{ doc: document, frameIndex: 0 }];
  let nextFrame = 1;
  for (const iframe of document.querySelectorAll("iframe")) {
    try {
      if (iframe.contentDocument) {
        docFrames.push({ doc: iframe.contentDocument, frameIndex: nextFrame });
        nextFrame += 1;
      }
    } catch (_e) { /* cross-origin */ }
  }
  const frameIndexFor = (el) => {
    const owner = el && el.ownerDocument;
    for (const entry of docFrames) {
      if (entry.doc === owner) return entry.frameIndex;
    }
    return 0;
  };
  const handler = (e) => {
    const el = pickTarget(e.target);
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    const ref = "@" + refOf(el);
    const text = valueText(el);
    const label = guessLabel(el);
    const frame_index = frameIndexFor(el);
    const list = window.__ubsFieldPicks;
    const last = list[list.length - 1];
    if (last && last.ref === ref && last.text === text) return;
    list.push({ ref, text, label, frame_index });
    try {
      el.style.outline = "2px solid #6366f1";
      setTimeout(() => { el.style.outline = ""; }, 600);
    } catch (_e) { /* ignore */ }
  };
  window.__ubsFieldPickHandler = handler;
  window.__ubsFieldPickDocs = docFrames.map((entry) => entry.doc);
  for (const entry of docFrames) entry.doc.addEventListener("click", handler, true);
  try {
    document.body.style.cursor = "crosshair";
  } catch (_e) { /* ignore */ }
  return { started: true, frames: docFrames.length };
},
  stopFieldPickRecording: () => {
  const handler = window.__ubsFieldPickHandler;
  const docs = window.__ubsFieldPickDocs || [document];
  if (handler) {
    for (const doc of docs) {
      try { doc.removeEventListener("click", handler, true); } catch (_e) {}
    }
  }
  window.__ubsFieldPickHandler = null;
  window.__ubsFieldPickDocs = null;
  try {
    document.body.style.cursor = "";
  } catch (_e) { /* ignore */ }
  const picks = Array.isArray(window.__ubsFieldPicks) ? window.__ubsFieldPicks.slice() : [];
  window.__ubsFieldPicks = [];
  return { picks };
},
  startListNavRecording: (args) => {
  const REF = args.refAttr;
  let counter = Number(document.documentElement.getAttribute(REF + "-counter") || 0);
  const refOf = (el) => {
    let ref = el.getAttribute(REF);
    if (!ref) {
      counter += 1;
      ref = "e" + counter;
      el.setAttribute(REF, ref);
      document.documentElement.setAttribute(REF + "-counter", String(counter));
    }
    return ref;
  };
  const labelOf = (el) => {
    const aria = el.getAttribute("aria-label");
    if (aria) return aria.trim().slice(0, 60);
    const ph = el.getAttribute("placeholder");
    if (ph) return ph.trim().slice(0, 60);
    const name = el.getAttribute("name");
    if (name) return name.trim().slice(0, 60);
    return (el.innerText || "").trim().replace(/\s+/g, " ").slice(0, 60);
  };
  const kindOf = (el) => {
    const tag = el.tagName ? el.tagName.toLowerCase() : "";
    if (tag === "input" || tag === "textarea" || tag === "select") return "input";
    if (el.getAttribute("contenteditable") === "true") return "input";
    if (el.getAttribute("role") === "textbox" || el.getAttribute("role") === "combobox") return "input";
    const text = labelOf(el).toLowerCase();
    if (/详情|查看|明细|进入/.test(text)) return "row";
    return "action";
  };
  window.__ubsListNavSteps = [];
  const handler = (e) => {
    const el = e.target && e.target.closest
      ? e.target.closest("input,textarea,select,button,a,[role='button'],[role='link'],[contenteditable='true'],[role='textbox']")
      : null;
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    const label = labelOf(el);
    if (!label) return;
    const step = { kind: kindOf(el), label, ref: "@" + refOf(el) };
    const list = window.__ubsListNavSteps;
    const last = list[list.length - 1];
    if (last && last.label === step.label && last.kind === step.kind) return;
    list.push(step);
  };
  window.__ubsListNavHandler = handler;
  document.addEventListener("click", handler, true);
  try { document.body.style.cursor = "crosshair"; } catch (_e) { /* ignore */ }
  return { started: true };
},
  stopListNavRecording: () => {
  const handler = window.__ubsListNavHandler;
  if (handler) {
    try { document.removeEventListener("click", handler, true); } catch (_e) { /* ignore */ }
  }
  window.__ubsListNavHandler = null;
  try { document.body.style.cursor = ""; } catch (_e) { /* ignore */ }
  const steps = Array.isArray(window.__ubsListNavSteps) ? window.__ubsListNavSteps.slice() : [];
  window.__ubsListNavSteps = [];
  return { steps };
}
})
