import frappe
from frappe.utils import getdate, nowdate, flt


@frappe.whitelist()
def get_mr_issue_history(
    company: str,
    item_code: str,
    branch: str | None = None,
    warehouse: str | None = None,
    limit: int = 10,
):
    """
    For Material Request (Purpose = Material Issue):
    Return last N issuance movements with date, cost_center and user.

    Source of truth: Stock Ledger Entry (all stock-out).
    We then pull cost_center from the voucher item row where possible.
    """

    if not company or not item_code:
        frappe.throw("company and item_code are required")

    limit = int(limit or 10)

    branch_whs = _get_branch_warehouses(company, branch)

    params = {"company": company, "item_code": item_code, "limit": limit}
    wh_cond = _warehouse_condition("sle", warehouse, branch_whs, params, fieldname="warehouse")

    # Stock-out only (issuance)
    # NOTE: voucher_no + voucher_type identifies the document. We show owner from the voucher (user).
    rows = frappe.db.sql(
        f"""
        SELECT
          sle.posting_date,
          sle.voucher_type,
          sle.voucher_no,
          sle.warehouse,
          (-sle.actual_qty) AS issued_qty,
          sle.stock_uom,
          sle.company
        FROM `tabStock Ledger Entry` sle
        WHERE sle.is_cancelled = 0
          AND sle.company = %(company)s
          AND sle.item_code = %(item_code)s
          AND sle.actual_qty < 0
          {wh_cond}
        ORDER BY sle.posting_date DESC, sle.posting_time DESC, sle.creation DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )

    # Enrich: cost_center + user/owner
    out = []
    for r in rows:
        voucher_type = r.get("voucher_type")
        voucher_no = r.get("voucher_no")

        owner = None
        cost_center = None

        # owner from voucher header (fast, single get_value)
        try:
            owner = frappe.db.get_value(voucher_type, voucher_no, "owner")
        except Exception:
            owner = None

        # cost center depends on voucher type; handle common issuance sources
        # Most issuances will be Stock Entry (Material Issue) or Delivery Note, etc.
        cost_center = _get_cost_center_from_voucher(voucher_type, voucher_no, item_code, r.get("warehouse"))

        out.append({
            "posting_date": str(r.get("posting_date")),
            "voucher_type": voucher_type,
            "voucher_no": voucher_no,
            "warehouse": r.get("warehouse"),
            "issued_qty": flt(r.get("issued_qty")),
            "stock_uom": r.get("stock_uom"),
            "cost_center": cost_center,
            "user": owner,
        })

    return {
        "scope": {
            "company": company,
            "branch": branch,
            "warehouse": warehouse,
            "branch_warehouses": branch_whs,
        },
        "issue_history": out,
    }


def _get_cost_center_from_voucher(voucher_type: str, voucher_no: str, item_code: str, warehouse: str | None):
    """
    Best-effort cost center extraction per voucher type.
    - Stock Entry: cost_center on Stock Entry Item (s_warehouse movements)
    - Delivery Note / Sales Invoice: cost_center may exist on item row or parent (depends on your setup)
    - Others: returns None if not found
    """
    if not voucher_type or not voucher_no:
        return None

    # Stock Entry (most common for Material Issue)
    if voucher_type == "Stock Entry":
        # Prefer row with item_code and matching source warehouse (issue side)
        cc = frappe.db.sql(
            """
            SELECT sei.cost_center
            FROM `tabStock Entry Detail` sei
            WHERE sei.parent = %s
              AND sei.item_code = %s
              AND IFNULL(sei.s_warehouse, '') != ''
            ORDER BY IF(sei.s_warehouse = %s, 0, 1), sei.idx
            LIMIT 1
            """,
            (voucher_no, item_code, warehouse or ""),
        )
        return cc[0][0] if cc and cc[0] and cc[0][0] else frappe.db.get_value("Stock Entry", voucher_no, "cost_center")

    # Delivery Note
    if voucher_type == "Delivery Note":
        # Some setups keep cost_center on DN item; else on DN
        if frappe.db.has_column("Delivery Note Item", "cost_center"):
            cc = frappe.db.sql(
                """
                SELECT dni.cost_center
                FROM `tabDelivery Note Item` dni
                WHERE dni.parent = %s AND dni.item_code = %s
                ORDER BY dni.idx
                LIMIT 1
                """,
                (voucher_no, item_code),
            )
            if cc and cc[0] and cc[0][0]:
                return cc[0][0]
        return frappe.db.get_value("Delivery Note", voucher_no, "cost_center")

    # Sales Invoice (rare for SLE negative but possible)
    if voucher_type == "Sales Invoice":
        if frappe.db.has_column("Sales Invoice Item", "cost_center"):
            cc = frappe.db.sql(
                """
                SELECT sii.cost_center
                FROM `tabSales Invoice Item` sii
                WHERE sii.parent = %s AND sii.item_code = %s
                ORDER BY sii.idx
                LIMIT 1
                """,
                (voucher_no, item_code),
            )
            if cc and cc[0] and cc[0][0]:
                return cc[0][0]
        return frappe.db.get_value("Sales Invoice", voucher_no, "cost_center")

    # Fallback: try cost_center on parent if exists
    if frappe.db.has_column(voucher_type, "cost_center"):
        return frappe.db.get_value(voucher_type, voucher_no, "cost_center")

    return None


def _get_branch_warehouses(company: str, branch: str | None) -> list[str]:
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
    if branch_whs:
        params["whs"] = tuple(branch_whs)
        return f" AND {alias}.{fieldname} IN %(whs)s"
    if warehouse:
        params["warehouse"] = warehouse
        return f" AND {alias}.{fieldname} = %(warehouse)s"
    return ""