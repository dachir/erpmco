frappe.ui.form.on("Purchase Order", {
  onload_post_render(frm) {
    add_item_overview_button(frm);
  },

  refresh(frm) {
    add_item_overview_button(frm);
  }
});

function add_item_overview_button(frm) {
  const grid = frm.get_field("items").grid;
  if (grid.__item_360_patched) return;
  grid.__item_360_patched = true;

  grid.add_custom_button(__("Item Overview"), () => {
    const row = get_selected_po_item_row(grid);

    if (!row) {
      frappe.msgprint(__("Please select one item row in the Items table."));
      return;
    }
    if (!row.item_code) {
      frappe.msgprint(__("Please set Item Code in the selected row."));
      return;
    }

    const branch = frm.doc.branch || frm.doc.custom_branch || null;

    frappe.call({
      method: "erpmco.item_360.get_item_360_for_po",
      args: {
        company: frm.doc.company,
        branch: branch,
        item_code: row.item_code,
        supplier: frm.doc.supplier || null,
        warehouse: row.warehouse || frm.doc.set_warehouse || null,

        consumption_days: 180,
        history_limit: 5,
        lead_time_receipts: 5,

        po_name: frm.doc.name || null,
        po_base_rate: row.base_rate,              // IMPORTANT: base rate
        po_uom: row.uom,
        po_conversion_factor: row.conversion_factor
      },
      callback: (r) => {
        if (!r.message) return;
        show_item_360_dialog(row.item_code, r.message);
      }
    });
  });

  // Add this inside add_item_overview_button(frm) after Item Overview button,
// or create a new function add_exception_items_button(frm)

grid.add_custom_button(__("Exception Items"), () => {
  if (!frm.doc.name) {
    frappe.msgprint(__("Please save the Purchase Order first."));
    return;
  }

  frappe.call({
    method: "erpmco.item_360.get_po_exception_items",
    args: {
      po_name: frm.doc.name,
      consumption_days: 180,
      price_var_thresh_pct: 10,
      cover_overstock_days: 90
    },
    callback: (r) => {
      const rows = r.message || [];
      show_exception_items_dialog(frm, rows);
    }
  });
});

function show_exception_items_dialog(frm, rows) {
  const d = new frappe.ui.Dialog({
    title: __("PO Exception Items"),
    size: "large",
    fields: [{ fieldtype: "HTML", fieldname: "html" }]
  });

  const body = (rows || []).map(x => `
    <tr>
      <td><a href="#" class="open-item" data-po-detail="${frappe.utils.escape_html(x.po_detail)}">${frappe.utils.escape_html(x.item_code)}</a></td>
      <td>${frappe.utils.escape_html(x.item_name || "")}</td>
      <td>${frappe.utils.escape_html(x.warehouse || "-")}</td>
      <td class="text-right">${frappe.format(x.qty || 0, {fieldtype:"Float"})}</td>
      <td class="text-right">${frappe.format(x.total_stock || 0, {fieldtype:"Float"})}</td>
      <td class="text-right">${frappe.format(x.open_po_qty || 0, {fieldtype:"Float"})}</td>
      <td class="text-right">${(x.cover_post_days != null) ? Number(x.cover_post_days).toFixed(1) : "-"}</td>
      <td class="text-right">${(x.price_variance_pct != null) ? Number(x.price_variance_pct).toFixed(2) + "%" : "-"}</td>
      <td>
        ${x.price_exception ? '<span class="indicator-pill red">Price</span>' : ''}
        ${x.cover_exception ? '<span class="indicator-pill orange">Cover</span>' : ''}
        ${(x.supplier_disabled || x.supplier_on_hold) ? '<span class="indicator-pill orange">Supplier</span>' : ''}
      </td>
    </tr>
  `).join("");

  const html = `
    <style>
      .indicator-pill { padding:2px 8px; border-radius:999px; font-size:12px; border:1px solid #ddd; margin-right:6px; display:inline-block; }
      .indicator-pill.red { background:#fdeaea; color:#a11d1d; border-color:#f5bcbc; }
      .indicator-pill.orange { background:#fff4e5; color:#8a5a00; border-color:#ffd59e; }
      .muted { color: var(--text-muted); }
      .table-sm td, .table-sm th { padding:6px 8px; }
    </style>

    <div class="muted" style="margin-bottom:8px;">
      Click an Item Code to open the full Item Overview dialog for that PO line.
    </div>

    <table class="table table-bordered table-sm">
      <thead>
        <tr>
          <th>Item</th><th>Item Name</th><th>Warehouse</th>
          <th class="text-right">PO Qty</th>
          <th class="text-right">Stock</th>
          <th class="text-right">Open PO</th>
          <th class="text-right">Cover Post (days)</th>
          <th class="text-right">Price Var</th>
          <th>Exceptions</th>
        </tr>
      </thead>
      <tbody>
        ${body || `<tr><td colspan="9" class="muted">No exception items found.</td></tr>`}
      </tbody>
    </table>
  `;

  d.fields_dict.html.$wrapper.html(html);

  // Click handler: open the existing Item Overview for that selected PO line
  d.$wrapper.on("click", "a.open-item", function (e) {
    e.preventDefault();

    const po_detail = $(this).attr("data-po-detail");
    const line = (frm.doc.items || []).find(i => i.name === po_detail);
    if (!line) {
      frappe.msgprint(__("Unable to locate the PO line."));
      return;
    }

    const branch = frm.doc.branch || frm.doc.custom_branch || null;

    frappe.call({
      method: "erpmco.item_360.get_item_360_for_po",
      args: {
        company: frm.doc.company,
        branch: branch,
        item_code: line.item_code,
        supplier: frm.doc.supplier || null,
        warehouse: line.warehouse || frm.doc.set_warehouse || null,

        consumption_days: 180,
        history_limit: 5,
        lead_time_receipts: 5,

        po_name: frm.doc.name || null,
        po_base_rate: line.base_rate,
        po_uom: line.uom,
        po_conversion_factor: line.conversion_factor
      },
      callback: (r) => {
        if (!r.message) return;
        // reuse existing dialog renderer from your file
        show_item_360_dialog(line.item_code, r.message);
      }
    });
  });

  d.show();
}

}

function get_selected_po_item_row(grid) {
  // Works well in v15 grid. If not available, fallback to current row in form.
  if (grid.get_selected_children) {
    const selected = grid.get_selected_children();
    if (selected && selected.length) return selected[0];
  }
  // fallback: try grid's row
  if (grid.grid_rows && grid.grid_rows.length) {
    const row = grid.grid_rows.find(gr => gr.doc && gr.doc.item_code);
    return row ? row.doc : null;
  }
  return null;
}

function fmtFloat(v) {
  return frappe.format(v || 0, { fieldtype: "Float" });
}
function fmtCurrency(v) {
  return frappe.format(v || 0, { fieldtype: "Currency" });
}
function fmtDate(v) {
  return v ? frappe.datetime.str_to_user(v) : "-";
}
function esc(s) {
  return frappe.utils.escape_html(s || "");
}

function badge(text, kind) {
  // kind: "green"|"orange"|"red"|"gray"
  const cls = {
    green: "indicator-pill green",
    orange: "indicator-pill orange",
    red: "indicator-pill red",
    gray: "indicator-pill gray"
  }[kind || "gray"];
  return `<span class="${cls}" style="margin-left:6px;">${esc(text)}</span>`;
}

function show_item_360_dialog(item_code, data) {
  const d = new frappe.ui.Dialog({
    title: __("Item Overview: {0}", [item_code]),
    size: "large",
    fields: [
      { fieldtype: "HTML", fieldname: "html" }
    ]
  });

  const k = data.kpis || {};
  const scope = data.scope || {};
  const flags = data.flags || {};
  const purchases = (data.purchases && data.purchases.history) ? data.purchases.history : [];
  const trends = (data.purchases && data.purchases.trends) ? data.purchases.trends : {};
  const supplier_last = (data.purchases && data.purchases.supplier_last_rates) ? data.purchases.supplier_last_rates : [];
  const quotations = (data.purchases && data.purchases.quotations) ? data.purchases.quotations : [];
  const reorder = (data.replenishment && data.replenishment.reorder) ? data.replenishment.reorder : [];
  const open_pos = k.open_pos || [];

  const priceVar = (flags.price_variance_pct !== null && flags.price_variance_pct !== undefined)
    ? `${flags.price_variance_pct.toFixed(2)}%` : "-";

  const coverCur = (k.cover_current_days != null) ? k.cover_current_days.toFixed(1) : "-";
  const coverPost = (k.cover_post_days != null) ? k.cover_post_days.toFixed(1) : "-";

  const supplierBadges = []
  if (flags.supplier_disabled) supplierBadges.push(badge("Supplier Disabled", "red"));
  if (flags.supplier_on_hold) supplierBadges.push(badge("Supplier On Hold", "orange"));

  const exceptionBadges = []
  if (flags.price_exception) exceptionBadges.push(badge("Price Exception", "red"));
  if (flags.cover_exception) exceptionBadges.push(badge("Overstock Risk", "orange"));
  if (!flags.price_exception && !flags.cover_exception && !flags.supplier_exception) exceptionBadges.push(badge("No Exceptions", "green"));

  const lastPurchase = k.last_purchase || {};
  const lead = k.lead_time || {};
  const supplierInfo = k.supplier_info || {};

  // KPI cards
  const htmlKpis = `
    <style>
      .kpi-grid { display:grid; grid-template-columns:repeat(3, 1fr); gap:12px; margin-bottom:14px; }
      .kpi { border:1px solid var(--border-color); border-radius:10px; padding:10px 12px; background:var(--card-bg); }
      .kpi .label { color:var(--text-muted); font-size:12px; margin-bottom:4px; }
      .kpi .value { font-size:18px; font-weight:600; }
      .kpi .sub { color:var(--text-muted); font-size:12px; margin-top:4px; }
      .tabs { margin-top:10px; }
      .tab-head { display:flex; gap:8px; margin-bottom:10px; }
      .tab-head .btn { padding:6px 10px; }
      .tab { display:none; }
      .tab.active { display:block; }
      .indicator-pill { padding:2px 8px; border-radius:999px; font-size:12px; border:1px solid var(--border-color); }
      .indicator-pill.green { background:#eaf7ee; color:#1e7e34; border-color:#bfe7c9; }
      .indicator-pill.orange { background:#fff4e5; color:#8a5a00; border-color:#ffd59e; }
      .indicator-pill.red { background:#fdeaea; color:#a11d1d; border-color:#f5bcbc; }
      .indicator-pill.gray { background:#f2f2f2; color:#555; border-color:#ddd; }
      .table-sm td, .table-sm th { padding:6px 8px; }
      .muted { color: var(--text-muted); }
    </style>

    <div class="muted" style="margin-bottom:8px;">
      Scope: Company <b>${esc(scope.company)}</b>
      ${scope.branch ? ` | Branch <b>${esc(scope.branch)}</b>` : ""}
      ${scope.warehouse ? ` | Warehouse <b>${esc(scope.warehouse)}</b>` : ""}
    </div>

    <div class="kpi-grid">
      <div class="kpi">
        <div class="label">Stock</div>
        <div class="value">${fmtFloat(k.total_stock)}</div>
        <div class="sub">Total (scoped)</div>
      </div>

      <div class="kpi">
        <div class="label">Open PO Qty</div>
        <div class="value">${fmtFloat(k.open_po_qty)}</div>
        <div class="sub">Pending receipts</div>
      </div>

      <div class="kpi">
        <div class="label">Consumption (Avg/Day)</div>
        <div class="value">${fmtFloat(k.avg_per_day)}</div>
        <div class="sub">${esc(k.consumption_days)} days window</div>
      </div>

      <div class="kpi">
        <div class="label">Days of Cover</div>
        <div class="value">${esc(coverCur)}</div>
        <div class="sub">Current</div>
      </div>

      <div class="kpi">
        <div class="label">Cover (Post Supply)</div>
        <div class="value">${esc(coverPost)}</div>
        <div class="sub">Stock + Open POs</div>
      </div>

      <div class="kpi">
        <div class="label">Price Variance vs Last</div>
        <div class="value">${esc(priceVar)}</div>
        <div class="sub">
          ${exceptionBadges.join(" ")}
          ${supplierBadges.join(" ")}
        </div>
      </div>
    </div>
  `;

  const htmlTabs = `
    <div class="tabs">
      <div class="tab-head">
        <button class="btn btn-default btn-xs" data-tab="t1">Purchases & Pricing</button>
        <button class="btn btn-default btn-xs" data-tab="t2">Stock & Replenishment</button>
        <button class="btn btn-default btn-xs" data-tab="t3">Open POs</button>
        <button class="btn btn-default btn-xs" data-tab="t4">Notes/Exceptions</button>
      </div>

      <div class="tab active" id="t1">
        ${render_purchases_section(purchases, trends, supplier_last, quotations, lastPurchase, supplierInfo)}
      </div>

      <div class="tab" id="t2">
        ${render_stock_replenishment_section(k, reorder, lead)}
      </div>

      <div class="tab" id="t3">
        ${render_open_po_section(open_pos)}
      </div>

      <div class="tab" id="t4">
        ${render_notes_section(flags)}
      </div>
    </div>
  `;

  d.fields_dict.html.$wrapper.html(htmlKpis + htmlTabs);

  // tab switching
  d.$wrapper.on("click", "[data-tab]", function () {
    const tabId = $(this).attr("data-tab");
    d.$wrapper.find(".tab").removeClass("active");
    d.$wrapper.find(`#${tabId}`).addClass("active");
  });

  d.show();
}

function render_purchases_section(purchases, trends, supplier_last, quotations, lastPurchase, supplierInfo) {
  const lastRows = (purchases || []).map(r => `
    <tr>
      <td>${fmtDate(r.date)}</td>
      <td>${esc(r.supplier || "-")}</td>
      <td class="text-right">${fmtFloat(r.qty)}</td>
      <td>${esc(r.uom || "-")}</td>
      <td class="text-right">${fmtCurrency(r.base_rate)}</td>
      <td class="text-right">${fmtCurrency(r.base_rate_per_stock_uom)}</td>
      <td>${r.ref ? `<a href="/app/${slug(r.ref_doctype)}/${r.ref}">${esc(r.ref_doctype)} ${esc(r.ref)}</a>` : "-"}</td>
    </tr>
  `).join("");

  const trendRow = (key, t) => `
    <tr>
      <td>${esc(key)}</td>
      <td class="text-right">${fmtCurrency(t.min_rate)}</td>
      <td class="text-right">${fmtCurrency(t.avg_rate)}</td>
      <td class="text-right">${fmtCurrency(t.max_rate)}</td>
      <td class="text-right">${esc(t.n || 0)}</td>
    </tr>
  `;

  const trendRows = [
    trendRow("Last 3 months", trends.m3 || {}),
    trendRow("Last 6 months", trends.m6 || {}),
    trendRow("Last 12 months", trends.m12 || {})
  ].join("");

  const supRows = (supplier_last || []).map(r => `
    <tr>
      <td>${esc(r.supplier || "-")}</td>
      <td>${fmtDate(r.date)}</td>
      <td class="text-right">${fmtCurrency(r.base_rate_per_stock_uom)}</td>
      <td>${r.ref ? `<a href="/app/${slug(r.ref_doctype)}/${r.ref}">${esc(r.ref_doctype)} ${esc(r.ref)}</a>` : "-"}</td>
    </tr>
  `).join("");

  const qRows = (quotations || []).map(r => `
    <tr>
      <td>${esc(r.supplier || "-")}</td>
      <td class="text-right">${fmtFloat(r.qty)}</td>
      <td>${esc(r.uom || "-")}</td>
      <td class="text-right">${fmtCurrency(r.base_rate || 0)}</td>
      <td>${fmtDate(r.valid_till)}</td>
      <td>${r.quotation ? `<a href="/app/supplier-quotation/${r.quotation}">${esc(r.quotation)}</a>` : "-"}</td>
      <td>${esc(r.status || "-")}</td>
    </tr>
  `).join("");

  return `
    <h5 style="margin-top:0;">Last Purchase (reference)</h5>
    <div class="muted" style="margin-bottom:8px;">
      Supplier: <b>${esc(lastPurchase.supplier || supplierInfo.supplier_name || supplierInfo.supplier || "-")}</b>
      | Date: <b>${fmtDate(lastPurchase.date)}</b>
      | Base Rate: <b>${fmtCurrency(lastPurchase.base_rate || 0)}</b>
      | Base/Stock UOM: <b>${fmtCurrency(lastPurchase.base_rate_per_stock_uom || 0)}</b>
    </div>

    <h5>Last 3–5 Transactions (Base + normalized)</h5>
    <table class="table table-bordered table-sm">
      <thead>
        <tr>
          <th>Date</th><th>Supplier</th><th class="text-right">Qty</th><th>UOM</th>
          <th class="text-right">Base Rate</th><th class="text-right">Base/Stock UOM</th><th>Doc</th>
        </tr>
      </thead>
      <tbody>${lastRows || `<tr><td colspan="7" class="muted">No history found</td></tr>`}</tbody>
    </table>

    <h5>Rate Trend (Base/Stock UOM)</h5>
    <table class="table table-bordered table-sm">
      <thead><tr><th>Window</th><th class="text-right">Min</th><th class="text-right">Avg</th><th class="text-right">Max</th><th class="text-right">N</th></tr></thead>
      <tbody>${trendRows}</tbody>
    </table>

    <h5>Supplier-wise Last Rate (Base/Stock UOM)</h5>
    <table class="table table-bordered table-sm">
      <thead><tr><th>Supplier</th><th>Last Date</th><th class="text-right">Rate</th><th>Doc</th></tr></thead>
      <tbody>${supRows || `<tr><td colspan="4" class="muted">No supplier-wise history</td></tr>`}</tbody>
    </table>

    <h5>Supplier Quotations (if used)</h5>
    <table class="table table-bordered table-sm">
      <thead><tr><th>Supplier</th><th class="text-right">Qty</th><th>UOM</th><th class="text-right">Base Rate</th><th>Valid Till</th><th>Quotation</th><th>Status</th></tr></thead>
      <tbody>${qRows || `<tr><td colspan="7" class="muted">No supplier quotations found</td></tr>`}</tbody>
    </table>
  `;
}

function render_stock_replenishment_section(k, reorder, lead) {
  const stockRows = (k.stock_by_warehouse || []).map(r => `
    <tr>
      <td>${esc(r.warehouse)}</td>
      <td class="text-right">${fmtFloat(r.qty)}</td>
      <td class="text-right">${fmtCurrency(r.valuation_rate || 0)}</td>
      <td class="text-right">${fmtCurrency((r.qty || 0) * (r.valuation_rate || 0))}</td>
    </tr>
  `).join("");

  const reorderRows = (reorder || []).map(r => `
    <tr>
      <td>${esc(r.warehouse)}</td>
      <td class="text-right">${fmtFloat(r.warehouse_reorder_level)}</td>
      <td class="text-right">${fmtFloat(r.warehouse_reorder_qty)}</td>
      <td>${esc(r.material_request_type || "-")}</td>
    </tr>
  `).join("");

  const samples = (lead.samples || []).map(r => `
    <tr>
      <td>${r.po ? `<a href="/app/purchase-order/${r.po}">${esc(r.po)}</a>` : "-"}</td>
      <td>${fmtDate(r.po_date)}</td>
      <td>${r.pr ? `<a href="/app/purchase-receipt/${r.pr}">${esc(r.pr)}</a>` : "-"}</td>
      <td>${fmtDate(r.pr_date)}</td>
      <td class="text-right">${esc(r.lead_days)}</td>
    </tr>
  `).join("");

  return `
    <h5 style="margin-top:0;">Stock (scoped) with valuation</h5>
    <table class="table table-bordered table-sm">
      <thead><tr><th>Warehouse</th><th class="text-right">Qty</th><th class="text-right">Valuation Rate</th><th class="text-right">Value</th></tr></thead>
      <tbody>${stockRows || `<tr><td colspan="4" class="muted">No stock records</td></tr>`}</tbody>
    </table>

    <h5>Consumption & Cover</h5>
    <table class="table table-bordered table-sm">
      <tbody>
        <tr><td>Consumption Window</td><td>${esc(k.consumption_days)} days (${esc(k.consumption_from)} → ${esc(k.consumption_to)})</td></tr>
        <tr><td>Total Out Qty</td><td>${fmtFloat(k.total_out_qty)}</td></tr>
        <tr><td>Avg / Day</td><td>${fmtFloat(k.avg_per_day)}</td></tr>
        <tr><td>Current Cover (days)</td><td>${k.cover_current_days != null ? k.cover_current_days.toFixed(1) : "-"}</td></tr>
        <tr><td>Post-supply Cover (days)</td><td>${k.cover_post_days != null ? k.cover_post_days.toFixed(1) : "-"}</td></tr>
      </tbody>
    </table>

    <h5>Reorder Settings (Item Reorder)</h5>
    <table class="table table-bordered table-sm">
      <thead><tr><th>Warehouse</th><th class="text-right">Reorder Level</th><th class="text-right">Reorder Qty</th><th>MR Type</th></tr></thead>
      <tbody>${reorderRows || `<tr><td colspan="4" class="muted">No reorder settings found</td></tr>`}</tbody>
    </table>

    <h5>Lead Time Evidence (PO → PR linked only)</h5>
    <div class="muted" style="margin-bottom:6px;">
      Avg: <b>${lead.avg_days != null ? lead.avg_days.toFixed(1) + " days" : "-"}</b> | Samples: <b>${esc(lead.n || 0)}</b>
    </div>
    <table class="table table-bordered table-sm">
      <thead><tr><th>PO</th><th>PO Date</th><th>PR</th><th>PR Date</th><th class="text-right">Days</th></tr></thead>
      <tbody>${samples || `<tr><td colspan="5" class="muted">No linked PO→PR samples found</td></tr>`}</tbody>
    </table>
  `;
}

function render_open_po_section(open_pos) {
  const rows = (open_pos || []).map(r => `
    <tr>
      <td>${r.po ? `<a href="/app/purchase-order/${r.po}">${esc(r.po)}</a>` : "-"}</td>
      <td>${fmtDate(r.transaction_date)}</td>
      <td>${esc(r.supplier || "-")}</td>
      <td>${fmtDate(r.schedule_date)}</td>
      <td>${esc(r.warehouse || "-")}</td>
      <td class="text-right">${fmtFloat(r.qty)}</td>
      <td class="text-right">${fmtFloat(r.received_qty)}</td>
      <td class="text-right">${fmtFloat(r.open_qty)}</td>
      <td class="text-right">${fmtCurrency(r.base_rate)}</td>
      <td class="text-right">${fmtCurrency(r.base_amount)}</td>
    </tr>
  `).join("");

  return `
    <h5 style="margin-top:0;">Open Purchase Orders (pending receipt)</h5>
    <table class="table table-bordered table-sm">
      <thead>
        <tr>
          <th>PO</th><th>PO Date</th><th>Supplier</th><th>Schedule</th><th>Warehouse</th>
          <th class="text-right">Qty</th><th class="text-right">Received</th><th class="text-right">Open</th>
          <th class="text-right">Base Rate</th><th class="text-right">Base Amount</th>
        </tr>
      </thead>
      <tbody>${rows || `<tr><td colspan="10" class="muted">No open POs for this item (scoped)</td></tr>`}</tbody>
    </table>
  `;
}

function render_notes_section(flags) {
  const notes = (flags.notes || []).map(n => `<li>${esc(n)}</li>`).join("");
  return `
    <h5 style="margin-top:0;">Exceptions & Notes</h5>
    <table class="table table-bordered table-sm">
      <tbody>
        <tr><td>Price Exception</td><td>${flags.price_exception ? badge("Yes", "red") : badge("No", "green")}</td></tr>
        <tr><td>Overstock Risk</td><td>${flags.cover_exception ? badge("Yes", "orange") : badge("No", "green")}</td></tr>
        <tr><td>Supplier Exception</td><td>${flags.supplier_exception ? badge("Yes", "orange") : badge("No", "green")}</td></tr>
      </tbody>
    </table>
    <ul>${notes || `<li class="muted">No exception notes.</li>`}</ul>
  `;
}

function slug(dt) {
  // Convert doctype to route
  return (dt || "").toLowerCase().replaceAll(" ", "-");
}
