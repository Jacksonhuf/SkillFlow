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

  const interactive = document.querySelectorAll(
    "a[href],button,input,select,textarea,[role='button'],[role='link'],[role='tab'],[role='menuitem'],[role='option'],[role='checkbox'],[onclick],[contenteditable='true']"
  );
  const disabled = (el) => el.disabled === true || el.getAttribute("aria-disabled") === "true" || !!el.closest("[aria-disabled='true'],.disabled,.ant-pagination-disabled,.is-disabled");
  for (const el of interactive) {
    if (out.elements.length >= MAX) break;
    if (!visible(el) || disabled(el)) continue;  // disabled controls cannot be acted on
    const item = { ref: "@" + refOf(el), role: roleOf(el), text: label(el) };
    const name = el.getAttribute("name"); if (name) item.name = name;
    const title = el.getAttribute("title"); if (title) item.title = title;
    const aria = el.getAttribute("aria-label"); if (aria) item.aria_label = aria;
    if (el.tagName.toLowerCase() === "a") item.href = el.href;
    if ("value" in el && typeof el.value === "string" && el.type !== "password") item.value = el.value.slice(0, 200);
    const dl = el.getAttribute("download"); if (dl !== null) item.filename = dl || (item.href || "").split("/").pop();
    const row = rowIndexOf(el); if (row !== null) item.row_index = row;
    out.elements.push(item);
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
}
})
