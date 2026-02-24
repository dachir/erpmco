import frappe
from erpnext.stock.doctype.delivery_note.delivery_note import DeliveryNote
from frappe.utils import cint, flt, nowdate, nowtime, parse_json
from erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle import add_serial_batch_ledgers

class CustomDeliveryNote(DeliveryNote):
    pass

@frappe.whitelist()
def get_delivery_note_items_from_reserved_stock(doc,details):
    try:
        # Parse input details if passed as a JSON string
        if isinstance(details, str):
            details = frappe.parse_json(details)

        if not details:
            frappe.throw("No entries selected.")

        items = []
        taxes_and_charges = None
        taxes = []

        for d in details:
            # Fetch Stock Reservation Entry
            sre = frappe.get_doc("Stock Reservation Entry", d["stock_reservation_entry"])

            # Fetch additional item details from Sales Order Item
            so_item_data = frappe.db.sql("""
                SELECT 
                    is_free_item, grant_commission, item_name, rate, amount
                FROM `tabSales Order Item`
                WHERE name = %s
            """, (d["sales_order_item"],), as_dict=True)

            if so_item_data:
                so_item = so_item_data[0]

                # Build item dictionary
                item = frappe._dict({
                    "item_code": d["item_code"],
                    "qty": d["qty"],
                    "stock_qty": d["stock_qty"],
                    "use_serial_batch_fields": 0,
                    "conversion_factor": d["conversion_factor"],
                    "stock_uom": d["stock_uom"],
                    "uom": d["uom"],
                    "against_sales_order": d["sales_order"],
                    "so_detail": d["sales_order_item"],
                    "is_free_item": so_item.get("is_free_item"),
                    "grant_commission": so_item.get("grant_commission"),
                    "item_name": so_item.get("item_name"),
                    "rate": so_item.get("rate"),
                    "amount": so_item.get("amount"),
                    "parenttype": "Delivery Note",
                    "warehouse": sre.warehouse,
                })

                # Process batches from Stock Reservation Entry
                #batches = []
                #for idx, b in enumerate(sre.sb_entries, start=1):
                #    batches.append({
                #        "batch_no": b.batch_no,
                #        "idx": idx,
                #        "name": f"row {idx}",
                #        "qty": b.qty,
                #    })


                # Add serial and batch ledger data
                #sb_doc = add_serial_batch_ledgers(batches, item, doc, sre.warehouse)
                #item.update({
                #    "serial_and_batch_bundle": sb_doc.name,
                #    "warehouse": sb_doc.warehouse,
                #})

                items.append(item)

            # Check and fetch taxes from the Sales Order
            sales_order = frappe.get_doc("Sales Order", d["sales_order"])
            if sales_order.taxes_and_charges and not taxes_and_charges:
                taxes_and_charges = sales_order.taxes_and_charges

                # Fetch taxes using SQL query
                taxes = frappe.db.sql("""
                    SELECT 
                        charge_type, account_head, description, rate, tax_amount, included_in_print_rate
                    FROM `tabSales Taxes and Charges`
                    WHERE parent = %s
                """, (d["sales_order"],), as_dict=True)

        # Consolidated data to return
        data = {
            "items": items,
            "taxes_and_charges": taxes_and_charges,
            "taxes": taxes,
        }
        return data

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Delivery Note Creation Error")
        frappe.throw(f"An error occurred while creating Delivery Notes: {str(e)}")






@frappe.whitelist()
def fetch_reserved_stock(customer=None):
    # 1) Draft DN quantities grouped by (so_detail, item_code, warehouse)
    draft_delivery = frappe.db.sql("""
        SELECT
            dni.so_detail,
            dni.item_code,
            dni.warehouse,
            SUM(dni.qty) AS qty
        FROM `tabDelivery Note Item` dni
        INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
        WHERE dn.docstatus = 0
          AND dni.so_detail IS NOT NULL
        GROUP BY dni.so_detail, dni.item_code, dni.warehouse
    """, as_dict=True)

    draft_map = {
        (row.so_detail, row.item_code, row.warehouse): flt(row.qty)
        for row in draft_delivery
    }

    # 2) Your main query (unchanged)
    query = """
        SELECT
            SUM(sre.custom_so_reserved_qty - sre.delivered_qty / sre.custom_conversion_factor) AS qty,
            SUM(sre.reserved_qty - sre.delivered_qty) AS stock_qty,
            sre.warehouse, sre.item_code, sre.name AS stock_reservation_entry, sre.custom_uom, sre.stock_uom,
            sre.voucher_no AS sales_order, so.customer, sre.voucher_detail_no AS sales_order_item,
            sre.custom_conversion_factor, i.item_name,
            MIN(sre.creation) AS creation
        FROM `tabStock Reservation Entry` sre
        INNER JOIN `tabSales Order` so ON so.name = sre.voucher_no
        INNER JOIN `tabItem` i ON i.name = sre.item_code
        WHERE
            sre.reserved_qty > sre.delivered_qty
            AND sre.docstatus = 1
            AND so.customer = %s
            AND sre.status NOT IN ("Delivered", "Cancelled")
            AND sre.voucher_type = 'Sales Order'
            AND so.status NOT IN ("Delivered", "Cancelled", "Closed")
        GROUP BY
            sre.item_code, sre.warehouse, sre.voucher_no, so.customer,
            sre.voucher_detail_no, sre.name, sre.custom_conversion_factor
        ORDER BY creation ASC
    """
    raw_result = frappe.db.sql(query, customer, as_dict=True)

    # 3) Allocate draft qty across reservations (FIFO)
    # Group rows by the same key used in draft_map
    grouped = {}
    for row in raw_result:
        key = (row["sales_order_item"], row["item_code"], row["warehouse"])
        grouped.setdefault(key, []).append(row)

    final_result = []
    for key, rows in grouped.items():
        remaining_draft = flt(draft_map.get(key, 0))

        # FIFO: rows already ordered by creation in SQL; sort again defensively if needed
        rows = sorted(rows, key=lambda r: r.get("creation") or "")

        for row in rows:
            available = flt(row["qty"])

            if remaining_draft > 0:
                consume = min(available, remaining_draft)
                available -= consume
                remaining_draft -= consume

            if available > 0:
                row["qty"] = available
                final_result.append(row)

    return final_result


