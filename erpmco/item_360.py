import frappe
from frappe.utils import flt, getdate, nowdate, add_months


# ----------------------------
# Public API (single payload)
# ----------------------------
@frappe.whitelist()
def get_item_360_for_po(
    company: str,
    item_code: str,
    supplier: str | None = None,
    warehouse: str | None = None,
    branch: str | None = None,
    consumption_days: int = 180,
    history_limit: int = 5,
    lead_time_receipts: int = 5,
    po_name: str | None = None,
    po_base_rate: float | None = None,
    po_uom: str | None = None,
    po_conversion_factor: float | None = None,
):
    """
    Choices locked per your requirements:
      1) Consumption definition: ALL stock-out (SLE actual_qty < 0)
      2) In-transit definition: Open POs only
      3) Currency normalization: Base rate always
      4) Lead time: PO -> PR (linked PO only)

    Branch scoping:
      - Primarily filter by warehouses belonging to that branch
      - If no mapping exists, fallback to passed warehouse
    """

    if not company or not item_code:
        frappe.throw("company and item_code are required")

    consumption_days = int(consumption_days or 180)
    history_limit = int(history_limit or 5)
    lead_time_receipts = int(lead_time_receipts or 5)

    to_date = getdate(nowdate())
    # Use exact days window (not month approximation) for consumption window
    from_date = getdate(frappe.utils.add_days(to_date, -max(consumption_days - 1, 0)))

    # Resolve branch warehouses (preferred scope control)
    branch_whs = _get_branch_warehouses(company, branch)

    # If no branch warehouses found, fall back to explicit warehouse (if any)
    # This still lets you "scope" the data to the PO warehouse which is usually branch-specific.
    effective_wh = warehouse if warehouse else None

    # --- Stock (Bin) ---
    stock = _get_stock(company, item_code, effective_wh, branch_whs)

    # --- Open POs (in-transit definition) ---
    open_po = _get_open_po(company, item_code, effective_wh, branch_whs, exclude_po=po_name)

    # --- Consumption (ALL stock-out) ---
    consumption = _get_consumption_all_stock_out(company, item_code, from_date, to_date, effective_wh, branch_whs)

    # --- Cover days ---
    avg_per_day = flt(consumption["avg_per_day"])
    total_stock = flt(stock["total_stock"])
    open_po_qty = flt(open_po["open_po_qty"])

    cover_current = (total_stock / avg_per_day) if avg_per_day else None
    cover_post = ((total_stock + open_po_qty) / avg_per_day) if avg_per_day else None

    # --- Purchases history + last purchase ---
    purchases = _get_purchase_history(company, item_code, supplier, history_limit, effective_wh, branch_whs)
    last_purchase = purchases[0] if purchases else {}

    # --- Rate trends (3/6/12 months) ---
    trends = {
        "m3": _get_rate_trend(company, item_code, supplier, months=3, warehouse=effective_wh, branch_whs=branch_whs),
        "m6": _get_rate_trend(company, item_code, supplier, months=6, warehouse=effective_wh, branch_whs=branch_whs),
        "m12": _get_rate_trend(company, item_code, supplier, months=12, warehouse=effective_wh, branch_whs=branch_whs),
    }

    # --- Supplier-wise last rate ---
    supplier_last_rates = _get_supplier_wise_last_rate(company, item_code, limit=10, warehouse=effective_wh, branch_whs=branch_whs)

    # --- Supplier quotations (optional) ---
    quotations = _get_supplier_quotations(company, item_code, limit=5, warehouse=effective_wh, branch_whs=branch_whs)

    # --- Reorder settings ---
    reorder = _get_reorder_settings(item_code, effective_wh, branch_whs)

    # --- Lead time from linked PO only ---
    lead_time = _get_lead_time_po_to_pr(company, item_code, lead_time_receipts, effective_wh, branch_whs)

    # --- Supplier status (useful flags) ---
    supplier_info = _get_supplier_info(supplier) if supplier else {}

    # --- Exception flags (policy thresholds can later be moved to a Settings doctype) ---
    flags = _build_flags(
        po_base_rate=po_base_rate,
        po_cf=po_conversion_factor,
        last_purchase=last_purchase,
        cover_post_days=cover_post,
        supplier_info=supplier_info
    )

    return {
        "scope": {
            "company": company,
            "branch": branch,
            "warehouse": effective_wh,
            "branch_warehouses": branch_whs,
        },
        "kpis": {
            "total_stock": total_stock,
            "stock_by_warehouse": stock["by_warehouse"],

            "open_po_qty": open_po_qty,
            "open_pos": open_po["open_pos"],

            "consumption_from": str(from_date),
            "consumption_to": str(to_date),
            "consumption_days": consumption_days,
            "total_out_qty": flt(consumption["total_out_qty"]),
            "avg_per_day": avg_per_day,

            "cover_current_days": cover_current,
            "cover_post_days": cover_post,

            "last_purchase": last_purchase,
            "lead_time": lead_time,

            "supplier_info": supplier_info,
        },
        "purchases": {
            "history": purchases,
            "trends": trends,
            "supplier_last_rates": supplier_last_rates,
            "quotations": quotations,
        },
        "replenishment": {
            "reorder": reorder,
        },
        "flags": flags,
    }


# ----------------------------
# Branch -> Warehouses mapping
# ----------------------------
def _get_branch_warehouses(company: str, branch: str | None) -> list[str]:
    """
    Returns warehouses belonging to a branch.
    Supports common patterns:
      - tabWarehouse.branch
      - tabWarehouse.custom_branch
    If neither exists or branch is empty, returns [].
    """
    if not branch:
        return []

    wh_branch_field = None
    if frappe.db.has_column("Warehouse", "branch"):
        wh_branch_field = "branch"
    elif frappe.db.has_column("Warehouse", "custom_branch"):
        wh_branch_field = "custom_branch"

    if not wh_branch_field:
        return []

    rows = frappe.db.sql(
        f"""
        SELECT name
        FROM `tabWarehouse`
        WHERE company = %(company)s
          AND IFNULL(disabled, 0) = 0
          AND `{wh_branch_field}` = %(branch)s
        """,
        {"company": company, "branch": branch},
        as_dict=True,
    )
    return [r["name"] for r in rows]


def _warehouse_condition(alias: str, warehouse: str | None, branch_whs: list[str], params: dict, fieldname: str = "warehouse") -> str:
    """
    Builds safe warehouse scoping SQL.
    Priority: branch_whs -> warehouse -> none
    """
    if branch_whs:
        params["whs"] = tuple(branch_whs)
        return f" AND {alias}.{fieldname} IN %(whs)s"
    if warehouse:
        params["warehouse"] = warehouse
        return f" AND {alias}.{fieldname} = %(warehouse)s"
    return ""


# ----------------------------
# Stock / Open PO / Consumption
# ----------------------------
def _get_stock(company: str, item_code: str, warehouse: str | None, branch_whs: list[str]):
    params = {"company": company, "item_code": item_code}
    wh_cond = _warehouse_condition("b", warehouse, branch_whs, params, fieldname="warehouse")

    by_wh = frappe.db.sql(
        f"""
        SELECT
          b.warehouse,
          SUM(b.actual_qty) AS qty,
          MAX(b.valuation_rate) AS valuation_rate
        FROM `tabBin` b
        WHERE b.item_code = %(item_code)s
          {wh_cond}
        GROUP BY b.warehouse
        ORDER BY b.warehouse
        """,
        params,
        as_dict=True,
    )

    total_stock = sum(flt(r["qty"]) for r in by_wh)
    return {"by_warehouse": by_wh, "total_stock": total_stock}


def _get_open_po(company: str, item_code: str, warehouse: str | None, branch_whs: list[str], exclude_po: str | None = None):
    params = {"company": company, "item_code": item_code}
    wh_cond = _warehouse_condition("poi", warehouse, branch_whs, params, fieldname="warehouse")

    excl_cond = ""
    if exclude_po:
        params["exclude_po"] = exclude_po
        excl_cond = " AND po.name != %(exclude_po)s"

    rows = frappe.db.sql(
        f"""
        SELECT
          po.name AS po,
          po.transaction_date,
          po.supplier,
          poi.schedule_date,
          poi.warehouse,
          poi.uom,
          poi.conversion_factor,
          poi.qty,
          poi.received_qty,
          (poi.qty - IFNULL(poi.received_qty, 0)) AS open_qty,
          poi.base_rate,
          poi.base_amount
        FROM `tabPurchase Order` po
        INNER JOIN `tabPurchase Order Item` poi ON poi.parent = po.name
        WHERE po.docstatus = 1
          AND po.company = %(company)s
          AND poi.item_code = %(item_code)s
          AND (poi.qty - IFNULL(poi.received_qty, 0)) > 0
          {wh_cond}
          {excl_cond}
        ORDER BY po.transaction_date DESC, po.modified DESC
        LIMIT 10
        """,
        params,
        as_dict=True,
    )

    open_po_qty = sum(flt(r["open_qty"]) for r in rows)
    return {"open_po_qty": open_po_qty, "open_pos": rows}


def _get_consumption_all_stock_out(company: str, item_code: str, from_date, to_date, warehouse: str | None, branch_whs: list[str]):
    params = {
        "company": company,
        "item_code": item_code,
        "from_date": from_date,
        "to_date": to_date,
    }
    wh_cond = _warehouse_condition("sle", warehouse, branch_whs, params, fieldname="warehouse")

    r = frappe.db.sql(
        f"""
        SELECT
          SUM(CASE WHEN sle.actual_qty < 0 THEN -sle.actual_qty ELSE 0 END) AS total_out_qty
        FROM `tabStock Ledger Entry` sle
        WHERE sle.is_cancelled = 0
          AND sle.company = %(company)s
          AND sle.item_code = %(item_code)s
          AND sle.posting_date BETWEEN %(from_date)s AND %(to_date)s
          {wh_cond}
        """,
        params,
        as_dict=True,
    )[0]

    total_out = flt(r["total_out_qty"])
    period_days = max((to_date - from_date).days + 1, 1)

    return {"total_out_qty": total_out, "avg_per_day": (total_out / period_days) if period_days else 0}


# ----------------------------
# Purchases: history / trends
# ----------------------------
def _get_purchase_history(company: str, item_code: str, supplier: str | None, limit: int,
                          warehouse: str | None, branch_whs: list[str]):
    """
    Priority: Purchase Invoice -> Purchase Receipt -> Purchase Order
    Always returns base-normalized rate per stock uom:
      base_rate_per_stock_uom = base_rate / conversion_factor
    """
    params = {"company": company, "item_code": item_code, "limit": limit}
    supplier_cond = ""
    if supplier:
        supplier_cond = " AND p.supplier = %(supplier)s"
        params["supplier"] = supplier

    # If we can scope by warehouse (PII/PRI/POI have warehouse), do it.
    wh_cond = _warehouse_condition("pii", warehouse, branch_whs, params, fieldname="warehouse")

    pi = frappe.db.sql(
        f"""
        SELECT
          p.posting_date AS date,
          p.supplier,
          pii.warehouse,
          pii.qty,
          pii.uom,
          pii.conversion_factor,
          pii.base_rate,
          p.currency,
          p.conversion_rate,
          p.name AS ref,
          'Purchase Invoice' AS ref_doctype,
          (pii.base_rate / NULLIF(pii.conversion_factor, 0)) AS base_rate_per_stock_uom
        FROM `tabPurchase Invoice` p
        INNER JOIN `tabPurchase Invoice Item` pii ON pii.parent = p.name
        WHERE p.docstatus = 1
          AND p.company = %(company)s
          AND pii.item_code = %(item_code)s
          {supplier_cond}
          {wh_cond}
        ORDER BY p.posting_date DESC, p.modified DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    if pi:
        return pi

    # PR fallback
    params2 = dict(params)
    wh_cond_pr = _warehouse_condition("pri", warehouse, branch_whs, params2, fieldname="warehouse")
    pr = frappe.db.sql(
        f"""
        SELECT
          p.posting_date AS date,
          p.supplier,
          pri.warehouse,
          pri.qty,
          pri.uom,
          pri.conversion_factor,
          pri.base_rate,
          p.currency,
          p.conversion_rate,
          p.name AS ref,
          'Purchase Receipt' AS ref_doctype,
          (pri.base_rate / NULLIF(pri.conversion_factor, 0)) AS base_rate_per_stock_uom
        FROM `tabPurchase Receipt` p
        INNER JOIN `tabPurchase Receipt Item` pri ON pri.parent = p.name
        WHERE p.docstatus = 1
          AND p.company = %(company)s
          AND pri.item_code = %(item_code)s
          {supplier_cond}
          {wh_cond_pr}
        ORDER BY p.posting_date DESC, p.modified DESC
        LIMIT %(limit)s
        """,
        params2,
        as_dict=True,
    )
    if pr:
        return pr

    # PO fallback
    params3 = dict(params)
    wh_cond_po = _warehouse_condition("poi", warehouse, branch_whs, params3, fieldname="warehouse")
    po = frappe.db.sql(
        f"""
        SELECT
          p.transaction_date AS date,
          p.supplier,
          poi.warehouse,
          poi.qty,
          poi.uom,
          poi.conversion_factor,
          poi.base_rate,
          p.currency,
          p.conversion_rate,
          p.name AS ref,
          'Purchase Order' AS ref_doctype,
          (poi.base_rate / NULLIF(poi.conversion_factor, 0)) AS base_rate_per_stock_uom
        FROM `tabPurchase Order` p
        INNER JOIN `tabPurchase Order Item` poi ON poi.parent = p.name
        WHERE p.docstatus = 1
          AND p.company = %(company)s
          AND poi.item_code = %(item_code)s
          {supplier_cond}
          {wh_cond_po}
        ORDER BY p.transaction_date DESC, p.modified DESC
        LIMIT %(limit)s
        """,
        params3,
        as_dict=True,
    )
    return po


def _get_rate_trend(company: str, item_code: str, supplier: str | None, months: int,
                    warehouse: str | None, branch_whs: list[str]):
    params = {"company": company, "item_code": item_code}
    supplier_cond = ""
    if supplier:
        supplier_cond = " AND p.supplier = %(supplier)s"
        params["supplier"] = supplier

    from_date = getdate(add_months(nowdate(), -months))
    params["from_date"] = from_date

    wh_cond = _warehouse_condition("pii", warehouse, branch_whs, params, fieldname="warehouse")

    r = frappe.db.sql(
        f"""
        SELECT
          MIN(pii.base_rate / NULLIF(pii.conversion_factor, 0)) AS min_rate,
          AVG(pii.base_rate / NULLIF(pii.conversion_factor, 0)) AS avg_rate,
          MAX(pii.base_rate / NULLIF(pii.conversion_factor, 0)) AS max_rate,
          COUNT(*) AS n
        FROM `tabPurchase Invoice` p
        INNER JOIN `tabPurchase Invoice Item` pii ON pii.parent = p.name
        WHERE p.docstatus = 1
          AND p.company = %(company)s
          AND pii.item_code = %(item_code)s
          AND p.posting_date >= %(from_date)s
          {supplier_cond}
          {wh_cond}
        """,
        params,
        as_dict=True,
    )[0]

    return {
        "from_date": str(from_date),
        "months": months,
        "min_rate": flt(r["min_rate"]),
        "avg_rate": flt(r["avg_rate"]),
        "max_rate": flt(r["max_rate"]),
        "n": int(r["n"] or 0),
    }


def _get_supplier_wise_last_rate(company: str, item_code: str, limit: int,
                                 warehouse: str | None, branch_whs: list[str]):
    params = {"company": company, "item_code": item_code, "limit": limit}
    wh_cond = _warehouse_condition("pii", warehouse, branch_whs, params, fieldname="warehouse")

    # Uses window function (MySQL 8+). ERPNext v15 default MariaDB may not support window functions.
    # To be safe across MariaDB, we implement with a subquery using max posting_date per supplier.
    rows = frappe.db.sql(
        f"""
        SELECT
          t.supplier,
          t.date,
          t.base_rate_per_stock_uom,
          t.ref,
          t.ref_doctype
        FROM (
          SELECT
            p.supplier,
            p.posting_date AS date,
            (pii.base_rate / NULLIF(pii.conversion_factor, 0)) AS base_rate_per_stock_uom,
            p.name AS ref,
            'Purchase Invoice' AS ref_doctype
          FROM `tabPurchase Invoice` p
          INNER JOIN `tabPurchase Invoice Item` pii ON pii.parent = p.name
          INNER JOIN (
            SELECT p2.supplier, MAX(p2.posting_date) AS max_date
            FROM `tabPurchase Invoice` p2
            INNER JOIN `tabPurchase Invoice Item` pii2 ON pii2.parent = p2.name
            WHERE p2.docstatus = 1
              AND p2.company = %(company)s
              AND pii2.item_code = %(item_code)s
              {wh_cond.replace("pii.", "pii2.")}
            GROUP BY p2.supplier
          ) mx ON mx.supplier = p.supplier AND mx.max_date = p.posting_date
          WHERE p.docstatus = 1
            AND p.company = %(company)s
            AND pii.item_code = %(item_code)s
            {wh_cond}
        ) t
        ORDER BY t.date DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    return rows


# ----------------------------
# Supplier quotations / reorder
# ----------------------------
def _get_supplier_quotations(company: str, item_code: str, limit: int,
                             warehouse: str | None, branch_whs: list[str]):
    params = {"company": company, "item_code": item_code, "limit": limit}

    # Supplier Quotation Item may not have warehouse; if it does in your setup, we filter.
    wh_cond = ""
    if frappe.db.has_column("Supplier Quotation Item", "warehouse"):
        wh_cond = _warehouse_condition("sqi", warehouse, branch_whs, params, fieldname="warehouse")

    return frappe.db.sql(
        f"""
        SELECT
          sq.name AS quotation,
          sq.supplier,
          sqi.qty,
          sqi.uom,
          sqi.conversion_factor,
          sqi.rate,
          sqi.base_rate,
          sq.currency,
          sq.conversion_rate,
          sq.valid_till,
          sq.transaction_date,
          sq.status
        FROM `tabSupplier Quotation` sq
        INNER JOIN `tabSupplier Quotation Item` sqi ON sqi.parent = sq.name
        WHERE sq.docstatus = 1
          AND sq.company = %(company)s
          AND sqi.item_code = %(item_code)s
          {wh_cond}
        ORDER BY sq.transaction_date DESC, sq.modified DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )


def _get_reorder_settings(item_code: str, warehouse: str | None, branch_whs: list[str]):
    """
    Item Reorder is warehouse-specific.
    If branch_whs exists, return reorder settings for those warehouses.
    Else if warehouse exists, return that.
    Else return all.
    """
    params = {"item_code": item_code}
    cond = ""
    if branch_whs:
        params["whs"] = tuple(branch_whs)
        cond = " AND ir.warehouse IN %(whs)s"
    elif warehouse:
        params["warehouse"] = warehouse
        cond = " AND ir.warehouse = %(warehouse)s"

    # Item Reorder is a child table of Item (parent = item_code)
    return frappe.db.sql(
        f"""
        SELECT
          ir.warehouse,
          ir.warehouse_reorder_level,
          ir.warehouse_reorder_qty,
          ir.material_request_type
        FROM `tabItem Reorder` ir
        WHERE ir.parent = %(item_code)s
          {cond}
        ORDER BY ir.warehouse
        """,
        params,
        as_dict=True,
    )


# ----------------------------
# Lead time: PO -> PR linked only
# ----------------------------
def _get_lead_time_po_to_pr(company: str, item_code: str, limit_receipts: int,
                            warehouse: str | None, branch_whs: list[str]):
    params = {"company": company, "item_code": item_code, "limit": limit_receipts}

    # Scope by PR item warehouse if possible (PRI has warehouse)
    wh_cond = _warehouse_condition("pri", warehouse, branch_whs, params, fieldname="warehouse")

    rows = frappe.db.sql(
        f"""
        SELECT
          pr.name AS pr,
          pr.posting_date AS pr_date,
          pri.purchase_order AS po,
          po.transaction_date AS po_date,
          DATEDIFF(pr.posting_date, po.transaction_date) AS lead_days
        FROM `tabPurchase Receipt` pr
        INNER JOIN `tabPurchase Receipt Item` pri ON pri.parent = pr.name
        INNER JOIN `tabPurchase Order` po ON po.name = pri.purchase_order
        WHERE pr.docstatus = 1
          AND pr.company = %(company)s
          AND pri.item_code = %(item_code)s
          AND pri.purchase_order IS NOT NULL
          {wh_cond}
        ORDER BY pr.posting_date DESC, pr.modified DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )

    if not rows:
        return {"avg_days": None, "n": 0, "samples": []}

    avg_days = sum(flt(r["lead_days"]) for r in rows) / len(rows)
    return {"avg_days": avg_days, "n": len(rows), "samples": rows}


# ----------------------------
# Supplier info & flags
# ----------------------------
def _get_supplier_info(supplier: str):
    # Standard fields; extend with your custom flags as needed
    if not supplier:
        return {}

    fields = ["name", "supplier_name", "disabled", "on_hold", "tax_category", "payment_terms"]
    # Some fields may not exist depending on your customization; filter safely
    meta = frappe.get_meta("Supplier")
    existing = [f for f in fields if meta.has_field(f)]

    doc = frappe.db.get_value("Supplier", supplier, existing, as_dict=True) or {}
    # Normalize keys
    return {
        "supplier": doc.get("name") or supplier,
        "supplier_name": doc.get("supplier_name"),
        "disabled": int(doc.get("disabled") or 0),
        "on_hold": int(doc.get("on_hold") or 0) if "on_hold" in doc else 0,
        "tax_category": doc.get("tax_category"),
        "payment_terms": doc.get("payment_terms"),
    }


def _build_flags(po_base_rate: float | None, po_cf: float | None, last_purchase: dict,
                 cover_post_days: float | None, supplier_info: dict):
    # Replace with Settings doctype later
    PRICE_VAR_THRESH_PCT = 10.0
    COVER_OVERSTOCK_DAYS = 90.0

    flags = {
        "price_variance_pct": None,
        "price_exception": False,
        "cover_exception": False,
        "supplier_exception": False,
        "supplier_disabled": bool(supplier_info.get("disabled")),
        "supplier_on_hold": bool(supplier_info.get("on_hold")),
        "notes": [],
    }

    # Price variance vs last purchase (base, stock uom normalized)
    try:
        # Convert PO base rate into base per stock uom using conversion factor
        po_base_per_stock = None
        if po_base_rate is not None and po_cf:
            po_base_per_stock = flt(po_base_rate) / flt(po_cf)

        last_base = flt((last_purchase or {}).get("base_rate_per_stock_uom"))
        if po_base_per_stock and last_base:
            var_pct = ((po_base_per_stock - last_base) / last_base) * 100.0
            flags["price_variance_pct"] = var_pct
            flags["price_exception"] = abs(var_pct) > PRICE_VAR_THRESH_PCT
            if flags["price_exception"]:
                flags["notes"].append(f"Price variance {var_pct:.2f}% exceeds {PRICE_VAR_THRESH_PCT:.0f}% threshold.")
    except Exception:
        pass

    # Cover exception
    try:
        if cover_post_days is not None and flt(cover_post_days) > COVER_OVERSTOCK_DAYS:
            flags["cover_exception"] = True
            flags["notes"].append(f"Post-supply cover {flt(cover_post_days):.1f} days exceeds {COVER_OVERSTOCK_DAYS:.0f} days.")
    except Exception:
        pass

    # Supplier exception
    if flags["supplier_disabled"] or flags["supplier_on_hold"]:
        flags["supplier_exception"] = True
        if flags["supplier_disabled"]:
            flags["notes"].append("Supplier is disabled.")
        if flags["supplier_on_hold"]:
            flags["notes"].append("Supplier is on hold.")

    return flags

@frappe.whitelist()
def get_po_exception_items(
    po_name: str,
    consumption_days: int = 180,
    price_var_thresh_pct: float = 10.0,
    cover_overstock_days: float = 90.0
):
    """
    Returns PO item rows that trigger exceptions (price variance / cover / supplier hold/disabled).
    Optimized: compute in bulk, minimal queries.
    """

    if not po_name:
        frappe.throw("po_name is required")

    po = frappe.get_doc("Purchase Order", po_name)
    company = po.company
    supplier = po.supplier

    # Branch + warehouse scoping
    branch = getattr(po, "branch", None) or getattr(po, "custom_branch", None)
    set_wh = getattr(po, "set_warehouse", None)

    branch_whs = _get_branch_warehouses(company, branch)

    # Build list of item rows
    items = []
    for it in po.items:
        if not it.item_code:
            continue
        items.append({
            "name": it.name,
            "item_code": it.item_code,
            "item_name": it.item_name,
            "warehouse": it.warehouse or set_wh,
            "qty": flt(it.qty),
            "uom": it.uom,
            "conversion_factor": flt(it.conversion_factor) or 1.0,
            "base_rate": flt(getattr(it, "base_rate", 0))  # v15 has base_rate on row
        })

    if not items:
        return []

    # Precompute consumption window dates
    consumption_days = int(consumption_days or 180)
    to_date = getdate(nowdate())
    from_date = getdate(frappe.utils.add_days(to_date, -max(consumption_days - 1, 0)))

    # Supplier info once
    supplier_info = _get_supplier_info(supplier) if supplier else {}
    supplier_exception = bool(supplier_info.get("disabled")) or bool(supplier_info.get("on_hold"))

    # For performance: fetch last purchase base_rate_per_stock_uom for all item_codes in ONE query
    item_codes = list({x["item_code"] for x in items})
    last_purchase_map = _get_last_purchase_map(company, item_codes, supplier=None, warehouse=None, branch_whs=branch_whs)

    # For performance: fetch consumption avg/day and stock total for all items in ONE query each (scoped)
    stock_map = _get_stock_map(company, item_codes, branch_whs, fallback_wh=None)
    cons_map = _get_consumption_map(company, item_codes, from_date, to_date, branch_whs, fallback_wh=None)

    # For performance: fetch open PO qty for all items in ONE query (excluding current PO) (scoped)
    open_po_map = _get_open_po_map(company, item_codes, po_name, branch_whs)

    exception_rows = []

    for row in items:
        code = row["item_code"]

        # Stock / consumption / open po
        total_stock = flt(stock_map.get(code, 0))
        avg_per_day = flt(cons_map.get(code, 0))
        open_po_qty = flt(open_po_map.get(code, 0))

        cover_post = ((total_stock + open_po_qty) / avg_per_day) if avg_per_day else None
        cover_exception = (cover_post is not None and cover_post > flt(cover_overstock_days))

        # Price exception vs last purchase
        last_base = flt(last_purchase_map.get(code, 0))
        po_base_per_stock = (flt(row["base_rate"]) / flt(row["conversion_factor"])) if row["conversion_factor"] else None

        price_variance_pct = None
        price_exception = False
        if po_base_per_stock and last_base:
            price_variance_pct = ((po_base_per_stock - last_base) / last_base) * 100.0
            price_exception = abs(price_variance_pct) > flt(price_var_thresh_pct)

        has_exception = price_exception or cover_exception or supplier_exception

        if has_exception:
            exception_rows.append({
                "po_detail": row["name"],
                "item_code": code,
                "item_name": row["item_name"],
                "warehouse": row["warehouse"],
                "qty": row["qty"],
                "uom": row["uom"],

                "total_stock": total_stock,
                "avg_per_day": avg_per_day,
                "open_po_qty": open_po_qty,
                "cover_post_days": cover_post,

                "last_purchase_base_per_stock": last_base,
                "po_base_per_stock": po_base_per_stock,
                "price_variance_pct": price_variance_pct,

                "price_exception": price_exception,
                "cover_exception": cover_exception,
                "supplier_exception": supplier_exception,
                "supplier_disabled": bool(supplier_info.get("disabled")),
                "supplier_on_hold": bool(supplier_info.get("on_hold")),
            })

    return exception_rows


def _get_last_purchase_map(company: str, item_codes: list[str], supplier=None, warehouse=None, branch_whs=None):
    """
    Returns {item_code: last_base_rate_per_stock_uom} using fallback:
      Purchase Invoice -> Purchase Receipt -> Purchase Order

    Scope by branch warehouses if provided; else scope by warehouse if provided.
    """
    if not item_codes:
        return {}

    out = {}  # item_code -> base_rate_per_stock_uom

    def wh_cond(alias: str, params: dict):
        if branch_whs:
            params["whs"] = tuple(branch_whs)
            return f" AND {alias}.warehouse IN %(whs)s"
        if warehouse:
            params["warehouse"] = warehouse
            return f" AND {alias}.warehouse = %(warehouse)s"
        return ""

    # 1) Purchase Invoice (latest first)
    params = {"company": company, "item_codes": tuple(item_codes)}
    pi_wh = wh_cond("pii", params)

    pi_rows = frappe.db.sql(
        f"""
        SELECT
          pii.item_code,
          (pii.base_rate / NULLIF(pii.conversion_factor, 0)) AS base_rate_per_stock_uom,
          p.posting_date,
          p.modified
        FROM `tabPurchase Invoice` p
        INNER JOIN `tabPurchase Invoice Item` pii ON pii.parent = p.name
        WHERE p.docstatus = 1
          AND p.company = %(company)s
          AND pii.item_code IN %(item_codes)s
          {pi_wh}
        ORDER BY p.posting_date DESC, p.modified DESC
        """,
        params,
        as_dict=True,
    )

    for r in pi_rows:
        code = r["item_code"]
        if code not in out and r.get("base_rate_per_stock_uom") is not None:
            out[code] = flt(r["base_rate_per_stock_uom"])

    missing = [c for c in item_codes if c not in out]

    # 2) Purchase Receipt fallback
    if missing:
        params = {"company": company, "item_codes": tuple(missing)}
        pr_wh = wh_cond("pri", params)

        pr_rows = frappe.db.sql(
            f"""
            SELECT
              pri.item_code,
              (pri.base_rate / NULLIF(pri.conversion_factor, 0)) AS base_rate_per_stock_uom,
              pr.posting_date,
              pr.modified
            FROM `tabPurchase Receipt` pr
            INNER JOIN `tabPurchase Receipt Item` pri ON pri.parent = pr.name
            WHERE pr.docstatus = 1
              AND pr.company = %(company)s
              AND pri.item_code IN %(item_codes)s
              {pr_wh}
            ORDER BY pr.posting_date DESC, pr.modified DESC
            """,
            params,
            as_dict=True,
        )

        for r in pr_rows:
            code = r["item_code"]
            if code not in out and r.get("base_rate_per_stock_uom") is not None:
                out[code] = flt(r["base_rate_per_stock_uom"])

    missing = [c for c in item_codes if c not in out]

    # 3) Purchase Order fallback (submitted only)
    if missing:
        params = {"company": company, "item_codes": tuple(missing)}
        po_wh = wh_cond("poi", params)

        po_rows = frappe.db.sql(
            f"""
            SELECT
              poi.item_code,
              (poi.base_rate / NULLIF(poi.conversion_factor, 0)) AS base_rate_per_stock_uom,
              po.transaction_date,
              po.modified
            FROM `tabPurchase Order` po
            INNER JOIN `tabPurchase Order Item` poi ON poi.parent = po.name
            WHERE po.docstatus = 1
              AND po.company = %(company)s
              AND poi.item_code IN %(item_codes)s
              {po_wh}
            ORDER BY po.transaction_date DESC, po.modified DESC
            """,
            params,
            as_dict=True,
        )

        for r in po_rows:
            code = r["item_code"]
            if code not in out and r.get("base_rate_per_stock_uom") is not None:
                out[code] = flt(r["base_rate_per_stock_uom"])

    # Ensure all keys exist
    for code in item_codes:
        out.setdefault(code, 0)

    return out



def _get_stock_map(company: str, item_codes: list[str], branch_whs: list[str], fallback_wh=None):
    if not item_codes:
        return {}
    params = {"company": company, "item_codes": tuple(item_codes)}
    wh_cond = ""
    if branch_whs:
        params["whs"] = tuple(branch_whs)
        wh_cond = " AND b.warehouse IN %(whs)s"

    rows = frappe.db.sql(
        f"""
        SELECT b.item_code, SUM(b.actual_qty) AS qty
        FROM `tabBin` b
        WHERE b.item_code IN %(item_codes)s
          {wh_cond}
        GROUP BY b.item_code
        """,
        params, as_dict=True
    )
    return {r["item_code"]: flt(r["qty"]) for r in rows}


def _get_consumption_map(company: str, item_codes: list[str], from_date, to_date, branch_whs: list[str], fallback_wh=None):
    if not item_codes:
        return {}
    params = {"company": company, "item_codes": tuple(item_codes), "from_date": from_date, "to_date": to_date}
    wh_cond = ""
    if branch_whs:
        params["whs"] = tuple(branch_whs)
        wh_cond = " AND sle.warehouse IN %(whs)s"

    rows = frappe.db.sql(
        f"""
        SELECT
          sle.item_code,
          SUM(CASE WHEN sle.actual_qty < 0 THEN -sle.actual_qty ELSE 0 END) AS total_out_qty
        FROM `tabStock Ledger Entry` sle
        WHERE sle.is_cancelled = 0
          AND sle.company = %(company)s
          AND sle.item_code IN %(item_codes)s
          AND sle.posting_date BETWEEN %(from_date)s AND %(to_date)s
          {wh_cond}
        GROUP BY sle.item_code
        """,
        params, as_dict=True
    )
    period_days = max((to_date - from_date).days + 1, 1)
    return {r["item_code"]: (flt(r["total_out_qty"]) / period_days) for r in rows}


def _get_open_po_map(company: str, item_codes: list[str], exclude_po: str, branch_whs: list[str]):
    if not item_codes:
        return {}
    params = {"company": company, "item_codes": tuple(item_codes), "exclude_po": exclude_po}
    wh_cond = ""
    if branch_whs:
        params["whs"] = tuple(branch_whs)
        wh_cond = " AND poi.warehouse IN %(whs)s"

    rows = frappe.db.sql(
        f"""
        SELECT
          poi.item_code,
          SUM(poi.qty - IFNULL(poi.received_qty, 0)) AS open_qty
        FROM `tabPurchase Order` po
        INNER JOIN `tabPurchase Order Item` poi ON poi.parent = po.name
        WHERE po.docstatus = 1
          AND po.company = %(company)s
          AND poi.item_code IN %(item_codes)s
          AND po.name != %(exclude_po)s
          AND (poi.qty - IFNULL(poi.received_qty, 0)) > 0
          {wh_cond}
        GROUP BY poi.item_code
        """,
        params, as_dict=True
    )
    return {r["item_code"]: flt(r["open_qty"]) for r in rows}
