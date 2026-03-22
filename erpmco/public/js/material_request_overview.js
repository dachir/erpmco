frappe.ui.form.on("Material Request", {
  refresh(frm) {
    add_mr_item_overview_buttons(frm);
  },
  onload_post_render(frm) {
    add_mr_item_overview_buttons(frm);
  }
});

function add_mr_item_overview_buttons(frm) {
  const grid = frm.get_field("items").grid;
  if (grid.__mr_overview_patched) return;
  grid.__mr_overview_patched = true;

  // Button for both purposes; behavior depends on frm.doc.material_request_type / purpose
  grid.add_custom_button(__("Item Overview"), () => {
    const row = get_selected_row(grid);
    if (!row || !row.item_code) {
      frappe.msgprint(__("Please select one item row and set Item Code."));
      return;
    }

    const purpose = frm.doc.material_request_type || frm.doc.purpose || frm.doc.material_request_purpose || "";

    // If "Material Issue" show last 10 issuance
    if ((purpose || "").toLowerCase().includes("material issue")) {
      open_issue_history_dialog(frm, row);
      return;
    }

    // If "Purchase" you can either:
    // - open your existing PO-style item 360 dialog (recommended), or
    // - show a simpler purchase-focused dialog for MR
    // For now, we open the existing PO-style API (you already have it).
    open_purchase_style_overview(frm, row);
  });
}

function get_selected_row(grid) {
  if (grid.get_selected_children) {
    const selected = grid.get_selected_children();
    if (selected && selected.length) return selected[0];
  }
  return null;
}

function open_issue_history_dialog(frm, row) {
  const branch = frm.doc.branch || frm.doc.custom_branch || null;

  frappe.call({
    method: "erpmco.erpmco.material_request_overview.get_mr_issue_history",
    args: {
      company: frm.doc.company,
      branch: branch,
      item_code: row.item_code,
      warehouse: row.warehouse || frm.doc.set_warehouse || null,
      limit: 10
    },
    callback: (r) => {
      const data = r.message || {};
      show_issue_history_dialog(row.item_code, data);
    }
  });
}

function show_issue_history_dialog(item_code, data) {
  const d = new frappe.ui.Dialog({
    title: __("Last Issuances: {0}", [item_code]),
    size: "large",
    fields: [{ fieldtype: "HTML", fieldname: "html" }]
  });

  const rows = (data.issue_history || []).map(x => `
    <tr>
      <td>${frappe.datetime.str_to_user(x.posting_date)}</td>
      <td class="text-right">${frappe.format(x.issued_qty || 0, {fieldtype:"Float"})}</td>
      <td>${frappe.utils.escape_html(x.stock_uom || "-")}</td>
      <td>${frappe.utils.escape_html(x.warehouse || "-")}</td>
      <td>${frappe.utils.escape_html(x.cost_center || "-")}</td>
      <td>${x.user ? frappe.utils.escape_html(x.user) : "-"}</td>
      <td>${x.voucher_no ? `<a href="/app/${slug(x.voucher_type)}/${x.voucher_no}">${frappe.utils.escape_html(x.voucher_type)} ${frappe.utils.escape_html(x.voucher_no)}</a>` : "-"}</td>
    </tr>
  `).join("");

  const html = `
    <div class="text-muted" style="margin-bottom:8px;">
      Showing last 10 stock-out issuances (all voucher types where SLE is negative).
    </div>
    <table class="table table-bordered table-sm">
      <thead>
        <tr>
          <th>Date</th>
          <th class="text-right">Issued Qty</th>
          <th>UOM</th>
          <th>Warehouse</th>
          <th>Cost Center</th>
          <th>User</th>
          <th>Voucher</th>
        </tr>
      </thead>
      <tbody>${rows || `<tr><td colspan="7" class="text-muted">No issuance history found.</td></tr>`}</tbody>
    </table>
  `;

  d.fields_dict.html.$wrapper.html(html);
  d.show();
}

function open_purchase_style_overview(frm, row) {
  // Reuse your existing item_360 method (same as PO dialog).
  // For MR purchase, we don’t have PO rate; it will show stock/consumption/purchase history/trends.
  const branch = frm.doc.branch || frm.doc.custom_branch || null;
  const po_base_rate = 0.0; // MR doesn't have a PO price

  frappe.call({
    method: "erpmco.item_360.get_item_360_for_po",
    args: {
      company: frm.doc.company,
      branch: branch,
      item_code: row.item_code,
      supplier: null,
      warehouse: row.warehouse || frm.doc.set_warehouse || null,

      consumption_days: 180,
      history_limit: 5,
      lead_time_receipts: 5,

      po_name: null,
      po_base_rate: po_base_rate,
      po_uom: row.uom,
      po_conversion_factor: row.conversion_factor || 1
    },
    callback: (r) => {
      if (!r.message) return;
      // uses your existing renderer from PO JS file
      if (typeof show_item_360_dialog === "function") {
        show_item_360_dialog(row.item_code, r.message);
      } else {
        frappe.msgprint(__("Item 360 dialog renderer not found. Include purchase_order_item_360.js globally or replicate renderer here."));
      }
    }
  });
}

function slug(dt) {
  return (dt || "").toLowerCase().replaceAll(" ", "-");
}