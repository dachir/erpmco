import frappe
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
from erpnext.stock.stock_balance import get_reserved_qty, update_bin_qty

class CustomSalesOrder(SalesOrder):
    def update_reserved_qty(self, so_item_rows=None):
        """update requested qty (before ordered_qty is updated)"""
        # Unreserve automatique si le statut est "Closed"
        if self.status == "Closed":
            self._unreserve_all_stock_entries()

        item_wh_list = []

        def _valid_for_reserve(item_code, warehouse):
            if (
                item_code
                and warehouse
                and [item_code, warehouse] not in item_wh_list
                and frappe.get_cached_value("Item", item_code, "is_stock_item")
            ):
                item_wh_list.append([item_code, warehouse])

        for d in self.get("items"):
            if (not so_item_rows or d.name in so_item_rows) and not d.delivered_by_supplier:
                if self.has_product_bundle(d.item_code):
                    for p in self.get("packed_items"):
                        if p.parent_detail_docname == d.name and p.parent_item == d.item_code:
                            _valid_for_reserve(p.item_code, p.warehouse)
                else:
                    _valid_for_reserve(d.item_code, d.warehouse)

        for item_code, warehouse in item_wh_list:
            update_bin_qty(item_code, warehouse, {"reserved_qty": get_reserved_qty(item_code, warehouse)})

    def _unreserve_all_stock_entries(self):
        """Annule toutes les réservations pour ce Sales Order (y compris partiellement livrées)
        en utilisant SQL pour détecter, mais cancel() pour exécuter toute la logique liée.
        """
        from frappe.utils import flt

        # Détection rapide via SQL
        sre_names = frappe.db.sql("""
            SELECT name
            FROM `tabStock Reservation Entry`
            WHERE voucher_no = %s
            AND voucher_type = 'Sales Order'
            AND status NOT IN ('Delivered', 'Cancelled')
            AND docstatus = 1
            AND reserved_qty > delivered_qty
        """, (self.name,), as_dict=False)

        if not sre_names:
            return

        cancelled_count = 0
        for (sre_name,) in sre_names:
            try:
                doc = frappe.get_doc("Stock Reservation Entry", sre_name)
                doc.cancel()  # Exécute toute la logique standard
                cancelled_count += 1
            except Exception:
                frappe.log_error(frappe.get_traceback(), f"Error cancelling SRE {sre_name}")

        frappe.logger().info(f"[SO {self.name}] Unreserved {cancelled_count} Stock Reservation Entries.")

        # Rafraîchir les qty dans les bins
        for row in self.get("items"):
            if frappe.get_cached_value("Item", row.item_code, "is_stock_item") and row.warehouse:
                update_bin_qty(row.item_code, row.warehouse, {
                    "reserved_qty": get_reserved_qty(row.item_code, row.warehouse)
                })


def create_allocation(doc, method):
    try:
        if doc.branch == "Kinshasa":
            """
            Custom method to handle allocation logic
            """
            allocation_entry = frappe.get_doc({
                "doctype": "Allocation",
                "company": doc.company,
                "branch": doc.branch,
                "shipment_date": doc.delivery_date,
                "customer": doc.customer,
                "sales_order": doc.name,
            })
            allocation_entry.insert(ignore_permissions=True)
            allocation_entry.populate_details()
            allocation_entry.reserve_all()
            allocation_entry.save(ignore_permissions=True)

    except Exception as e:
        frappe.log_error(
            message=frappe.get_traceback(),
            title=f"Error creating allocation for Sales Order {doc.name}"
        )

            

