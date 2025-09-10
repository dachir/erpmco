from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (validate_stock_reservation_settings, get_sre_reserved_qty_details_for_voucher
    , get_available_qty_to_reserve, StockReservationEntry, get_sre_reserved_qty_for_voucher_detail_no, get_stock_balance)

import frappe
from frappe import _
from frappe.utils import cint, flt
from typing import Literal

class CustomStockReservationEntry(StockReservationEntry):
    def before_submit(self) -> None:
        self.set_reservation_based_on()
        #self.validate_reservation_based_on_qty()
        if self.reservation_based_on == "Qty":
            self.validate_with_allowed_qty_2(self.reserved_qty)
        self.auto_reserve_serial_and_batch()
        #self.validate_reservation_based_on_serial_and_batch()

    def on_update_after_submit(self) -> None:
        self.can_be_updated()
        self.validate_uom_is_integer()
        self.set_reservation_based_on()
        #self.validate_reservation_based_on_qty()
        if self.reservation_based_on == "Qty":
            self.validate_with_allowed_qty_2(self.reserved_qty)
        #self.validate_reservation_based_on_serial_and_batch()
        self.update_reserved_qty_in_voucher()
        self.update_status()
        self.update_reserved_stock_in_bin()
        self.reload()


    def validate_with_allowed_qty_2(self, qty_to_be_reserved: float) -> None:
        """Validates `Reserved Qty` with `Max Reserved Qty`."""

        self.db_set(
            "available_qty",
            get_available_qty_to_reserve(self.item_code, self.warehouse, ignore_sre=self.name),
        )

        total_reserved_qty = get_sre_reserved_qty_for_voucher_detail_no(
            self.voucher_type, self.voucher_no, self.voucher_detail_no, ignore_sre=self.name
        )

        voucher_delivered_qty = 0
        if self.voucher_type == "Sales Order":
            delivered_qty = frappe.db.get_value("Sales Order Item", self.voucher_detail_no, "delivered_qty") or 0
            conversion_factor = frappe.db.get_value("Sales Order Item", self.voucher_detail_no, "conversion_factor")
            voucher_delivered_qty = flt(delivered_qty) * flt(conversion_factor)

        allowed_qty = min(self.available_qty, (self.voucher_qty - voucher_delivered_qty - total_reserved_qty))

        if self.get("_action") != "submit" and self.voucher_type == "Sales Order" and allowed_qty <= 0:
            msg = _("Item {0} is already reserved/delivered against Sales Order {1}.").format(
                frappe.bold(self.item_code), frappe.bold(self.voucher_no)
            )

            if self.docstatus == 1:
                self.cancel()
                return frappe.msgprint(msg)
            else:
                frappe.throw(msg)

        if qty_to_be_reserved > allowed_qty:
            actual_qty = get_stock_balance(self.item_code, self.warehouse)
            msg = """
                Cannot reserve more than Allowed Qty {} {} for Item {} against {} {}.<br /><br />
                The <b>Allowed Qty</b> is calculated as follows:<br />
                <ul>
                    <li>Actual Qty [Available Qty at Warehouse] = {}</li>
                    <li>Reserved Stock [Ignore current SRE] = {}</li>
                    <li>Available Qty To Reserve [Actual Qty - Reserved Stock] = {}</li>
                    <li>Voucher Qty [Voucher Item Qty] = {}</li>
                    <li>Delivered Qty [Qty delivered against the Voucher Item] = {}</li>
                    <li>Total Reserved Qty [Qty reserved against the Voucher Item] = {}</li>
                    <li>Allowed Qty [Minimum of (Available Qty To Reserve, (Voucher Qty - Delivered Qty - Total Reserved Qty))] = {}</li>
                </ul>
            """.format(
                frappe.bold(allowed_qty),
                self.stock_uom,
                frappe.bold(self.item_code),
                self.voucher_type,
                frappe.bold(self.voucher_no),
                actual_qty,
                actual_qty - self.available_qty,
                self.available_qty,
                self.voucher_qty,
                voucher_delivered_qty,
                total_reserved_qty,
                allowed_qty,
            )
            frappe.throw(msg)

        if qty_to_be_reserved <= self.delivered_qty:
            msg = _("Reserved Qty should be greater than Delivered Qty.")
            frappe.throw(msg)



#########################################################################################################
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
            #frappe.msgprint(str(available_qty))
            if available_qty > 0:
                total_available_stock += available_qty
                warehouse_stock_map[warehouse] = available_qty

        #frappe.throw(str(child_warehouses))
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
                "reservation_based_on": "Serial and Batch",
                "has_batch_no": 1,
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

                index += 1
                picked_qty += qty

            if qty > 0:
                args.update({"sb_entries": sb_entries})
                sre = frappe.get_doc(args)
                #sre.reservation_based_on = "Serial and Batch"
                sre.save()
                sre.submit()

            sre_count += 1

    if sre_count and notify:
        frappe.msgprint(_("Stock Reservation Entries Created"), alert=True, indicator="green")



