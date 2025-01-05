from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (validate_stock_reservation_settings, get_sre_reserved_qty_details_for_voucher
    , get_available_qty_to_reserve)

import frappe
from frappe import _
from frappe.utils import cint, flt
from typing import Literal

#class CustomStockReservationEntry(StockReservationEntry):
#    pass

def create_stock_reservation_entries_for_so_items(
    sales_order: object,
    items_details: list[dict] | None = None,
    from_voucher_type: Literal["Pick List", "Purchase Receipt"] = None,
    notify=True,
) -> None:
    """Creates Stock Reservation Entries for Sales Order Items."""

    from erpnext.selling.doctype.sales_order.sales_order import get_unreserved_qty
    from frappe.utils.nestedset import get_descendants_of

    validate_stock_reservation_settings(sales_order)

    allow_partial_reservation = frappe.db.get_single_value("Stock Settings", "allow_partial_reservation")

    items = []
    if items_details:
        for item in items_details:
            so_item = frappe.get_doc("Sales Order Item", item.get("sales_order_item"))
            so_item.warehouse = item.get("warehouse")
            so_item.qty_to_reserve = flt(item.get("qty_to_reserve")) * (
                flt(item.get("conversion_factor")) or flt(so_item.conversion_factor) or 1
            )
            so_item.from_voucher_no = item.get("from_voucher_no")
            so_item.from_voucher_detail_no = item.get("from_voucher_detail_no")
            so_item.serial_and_batch_bundle = item.get("serial_and_batch_bundle")
            items.append(so_item)

    sre_count = 0
    reserved_qty_details = get_sre_reserved_qty_details_for_voucher("Sales Order", sales_order.name)

    for item in items if items_details else sales_order.get("items"):
        if not item.get("reserve_stock"):
            continue

        # Check if the warehouse is a parent
        is_group = frappe.get_cached_value("Warehouse", item.warehouse, "is_group")
        child_warehouses = (
            get_descendants_of("Warehouse", item.warehouse) if is_group else [item.warehouse]
        )

        # Aggregate available stock across child warehouses
        total_available_stock = 0
        warehouse_stock_map = {}

        for warehouse in child_warehouses:
            available_qty = get_available_qty_to_reserve(item.item_code, warehouse)
            if available_qty > 0:
                total_available_stock += available_qty
                warehouse_stock_map[warehouse] = available_qty

        if total_available_stock <= 0:
            frappe.msgprint(
                _("Row #{0}: No stock available to reserve for Item {1} in Warehouse {2}.").format(
                    item.idx, frappe.bold(item.item_code), frappe.bold(item.warehouse)
                ),
                title=_("Stock Reservation"),
                indicator="orange",
            )
            continue

        unreserved_qty = get_unreserved_qty(item, reserved_qty_details)
        qty_to_be_reserved = min(unreserved_qty, total_available_stock)

        if hasattr(item, "qty_to_reserve"):
            qty_to_be_reserved = min(qty_to_be_reserved, item.qty_to_reserve)

        # Distribute reservation across child warehouses
        for warehouse, available_qty in warehouse_stock_map.items():
            #frappe.throw(str(warehouse_stock_map))
            if qty_to_be_reserved <= 0:
                break

            reserved_qty = min(qty_to_be_reserved, available_qty)
            qty_to_be_reserved -= reserved_qty

            #sre = frappe.new_doc("Stock Reservation Entry")
            #sre.item_code = item.item_code
            #sre.warehouse = warehouse
            #sre.voucher_type = sales_order.doctype
            #sre.voucher_no = sales_order.name
            #sre.voucher_detail_no = item.name
            #sre.available_qty = available_qty
            #sre.voucher_qty = item.stock_qty
            #sre.reserved_qty = reserved_qty
            #sre.company = sales_order.company
            #sre.stock_uom = item.stock_uom
            #sre.project = sales_order.project

            args = frappe._dict({
                "doctype": "Stock Reservation Entry",
                "item_code": item.item_code,
                "warehouse": warehouse,
                "voucher_type": sales_order.doctype,
                "voucher_no": sales_order.name,
                "voucher_detail_no": item.name,
                "available_qty": available_qty,
                "voucher_qty": item.stock_qty,
                "reserved_qty": reserved_qty,
                "company": sales_order.company,
                "stock_uom": item.stock_uom,
                "project": sales_order.project,
            })

            if from_voucher_type:
                args.update({
                    "from_voucher_type":from_voucher_type,
                    "from_voucher_no": item.from_voucher_no,
                    "from_voucher_detail_no": item.from_voucher_detail_no
                })
                #sre.from_voucher_type = from_voucher_type
                #sre.from_voucher_no = item.from_voucher_no
                #sre.from_voucher_detail_no = item.from_voucher_detail_no

            # Serial and Batch Handling
            #sre.reservation_based_on = "Serial and Batch"
            sbb_entries = frappe.db.sql(
                """
                SELECT sbe.serial_no, sbe.batch_no, sbe.qty- IFNULL(r.qty,0) As qty, sbe.warehouse
                FROM `tabSerial and Batch Bundle` sbb INNER JOIN `tabSerial and Batch Entry` sbe ON sbe.parent = sbb.name
                LEFT JOIN (
                    SELECT sbe1.batch_no, SUM(sbe1.qty) AS qty
                    FROM `tabSerial and Batch Entry` sbe1 INNER JOIN `tabStock Reservation Entry` sre ON sbe1.parent = sre.name
                    GROUP BY sbe1.batch_no
                    ) AS r ON r.batch_no = sbe.batch_no AND r.qty < sbe.qty
                WHERE sbb.item_code = %s AND sbb.type_of_transaction = 'Inward' AND sbb.docstatus = 1 
                """, (item.item_code), as_dict=1
            )

            sb_entries = []
            
            index, picked_qty = 0, 0

            while index < len(sbb_entries) and picked_qty < reserved_qty:
                entry = sbb_entries[index]
                
                qty = 1 if frappe.get_cached_value("Item", item.item_code, "has_serial_no") else min(
                    abs(entry.qty), reserved_qty - picked_qty
                )
                sb_entries.append(
                    {
                        "serial_no": entry.serial_no,
                        "batch_no": entry.batch_no,
                        "qty": qty,
                        "warehouse": entry.warehouse,
                    }
                )

                #sre.append(
                #    "sb_entries",
                #    {
                #        "serial_no": entry.serial_no,
                #        "batch_no": entry.batch_no,
                #        "qty": qty,
                #        "warehouse": entry.warehouse,
                #    },
                #)
                #frappe.throw(str(sre.as_json()))
                index += 1
                picked_qty += qty
            args.update({"sb_entries": sb_entries})
            sre = frappe.get_doc(args)
            sre.reservation_based_on = "Serial and Batch"
            sre.save()
            sre.submit()

            sre_count += 1

    if sre_count and notify:
        frappe.msgprint(_("Stock Reservation Entries Created"), alert=True, indicator="green")



