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

  const tables = Array.from(document.querySelectorAll("table,[role='grid'],[role='table'],[role='treegrid']")).filter(visible).slice(0, args.maxTables);
  tables.forEach((tbl, tableIndex) => {
    const rows = Array.from(tbl.querySelectorAll("tr,[role='row']")).filter(r => r.closest("table,[role='grid'],[role='table'],[role='treegrid']") === tbl);
    let dataRow = 0;
    for (const tr of rows) {
      const cells = Array.from(tr.children).filter(c => /^(td|th)$/i.test(c.tagName) || ["cell","gridcell","columnheader","rowheader"].includes(c.getAttribute("role")));
      if (!cells.length) continue;
      const isHeader = cells.every(c => c.tagName.toLowerCase() === "th" || c.getAttribute("role") === "columnheader");
      if (isHeader) {
        if (tableIndex > 0) continue;  // only the first table maps headers -> template fields
        cells.forEach((c, col) => {
          if (out.elements.length >= MAX) return;
          out.elements.push({ role: "columnheader", column_index: col, text: (c.innerText || "").trim().slice(0, 200), table_index: tableIndex });
        });
        continue;
      }
      if (tableIndex > 0) continue;
      dataRow += 1;
      cells.forEach((c, col) => {
        if (out.elements.length >= MAX) return;
        out.elements.push({ role: "cell", row_index: dataRow, column_index: col, text: (c.innerText || "").trim().slice(0, 500), table_index: tableIndex });
      });
    }
  });
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
