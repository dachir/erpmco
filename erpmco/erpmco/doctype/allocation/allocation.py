# Copyright (c) 2024, Kossivi Dodzi Amouzou and contributors
# For license information, please see license.txt

from frappe.model.document import Document
import frappe
from frappe.utils import flt
import copy


class Allocation(Document):
    def before_save(self):
        self.populate_details()

    def after_save(self):
        self.update_shortages()

    def on_submit(self):
        # Handle reservations and shortages for each detail
        for detail in self.details:
            #if detail.qty_allocated > 0:
            sales_order = frappe.get_doc("Sales Order", detail.sales_order)
            self.create_reservation_entries(sales_order, detail)

            # Update shortages on submit as well
            self.update_shortages()
            if detail.shortage > 0:
                shortages = frappe.get_list(
                    "Shortage",
                    filters={"docstatus": 1, "voucher_no": detail.sales_order, "voucher_detail_no":detail.so_item,},
                    fields=["name"],
                )
                for sh in shortages:
                    doc = frappe.get_doc("Shortage", sh.name)
                    doc.cancel()

                self.create_shortage_entry(
                    item_code=detail.item_code,
                    warehouse=detail.warehouse,
                    shortage_qty=detail.shortage,
                    voucher_type="Sales Order",
                    voucher_no=detail.sales_order,
                    voucher_detail_no=detail.so_item,
                    allocation=self.name,
                    allocation_detail = detail.name,
                    conversion_factor = detail.conversion_factor,
                )

    def create_reservation_entries(self, sales_order, detail):
        """
        Creates Stock Reservation Entries for the sales order items in the allocation.
        """
        from erpmco.overrides.stock_reservation_entry import (
            create_stock_reservation_entries_for_so_items as create_stock_reservation_entries,
        )

        # Prepare item details for reservation
        item_details = [
            {
                "item_code": detail.item_code,
                "warehouse": detail.warehouse,
                "qty_to_reserve": detail.qty_to_allocate,
                "sales_order_item": detail.so_item,
            }
        ]

        # Create reservation entries
        create_stock_reservation_entries(
            sales_order=sales_order, items_details=item_details
        )



    def update_shortages(self):
        """
        Updates shortage and allocation quantities for each detail.
        """
        for detail in self.details:
            # Fetch reserved quantity and calculate shortage
            reserved_qty = get_reservation_by_item(detail.sales_order, detail.so_item) /(detail.conversion_factor or 1)
            detail.qty_allocated = reserved_qty

            # Calculate the shortage
            detail.shortage = max(detail.qty_to_allocate - reserved_qty, 0)

    def create_shortage_entry(
        self, item_code, warehouse, shortage_qty, voucher_type, voucher_no, voucher_detail_no, allocation, allocation_detail,conversion_factor
    ):
        """
        Creates a Shortage Entry for insufficient stock.
        """
        shortage = frappe.get_doc(
            {
                "doctype": "Shortage",
                "item_code": item_code,
                "warehouse": warehouse,
                "shortage": shortage_qty * flt(conversion_factor or 1),
                "voucher_type": voucher_type,
                "voucher_no": voucher_no,
                "voucher_detail_no": voucher_detail_no,
                "stock_uom": frappe.db.get_value("Item", item_code, "stock_uom"),
                "allocation": allocation,
                "allocation_detail": allocation_detail,
            }
        )
        shortage.insert()
        shortage.submit()

    def populate_details(self):
        """
        Populates the details table with relevant sales orders and their stock status.
        """
        self.details = []

        query = """
            SELECT 
                so.name AS sales_order,
                so.customer,
                so.branch,
                so.transaction_date AS date,
                soi.name AS detail_name,
                soi.item_code,
                soi.warehouse,
                soi.qty AS qty_ordered,
                soi.stock_reserved_qty / conversion_factor AS qty_allocated,
                soi.delivered_qty / conversion_factor AS qty_delivered,
                (soi.qty - (soi.stock_reserved_qty  + soi.delivered_qty) / conversion_factor) AS qty_remaining,
                conversion_factor
            FROM `tabSales Order` so
            INNER JOIN `tabSales Order Item` soi ON soi.parent = so.name
            WHERE so.docstatus = 1 AND so.company = %(company)s AND so.branch LIKE %(branch)s AND so.customer LIKE %(customer)s
                AND soi.item_code LIKE %(item_code)s AND so.name LIKE %(sales_order)s
        """

        # Adjust query based on filters
        if self.include_lines_fully_allocated:
            query += """
                AND (soi.qty = soi.stock_reserved_qty / conversion_factor OR soi.qty > (soi.stock_reserved_qty + soi.delivered_qty) / conversion_factor)
            """
        else:
            query += " AND soi.qty > (soi.stock_reserved_qty + soi.delivered_qty) / conversion_factor"

        customer = self.customer if self.customer else "%"
        item_code = self.item if self.item else "%"
        branch = self.branch if self.branch else "%"
        sales_order = self.sales_order if self.sales_order else "%"
        
        sales_orders = frappe.db.sql(query,{"company": self.company, "customer": customer,"item_code": item_code,"branch": branch,"sales_order": sales_order,}, as_dict=True)

        # Populate the child table
        self.details.clear()
        for so in sales_orders:
            self.append(
                "details",
                {
                    "sales_order": so["sales_order"],
                    "date": so["date"],
                    "item_code": so["item_code"],
                    "warehouse": so["warehouse"],
                    "qty_ordered": flt(so["qty_ordered"],2),
                    "qty_allocated": flt(so["qty_allocated"],2),
                    "qty_delivered": flt(so["qty_delivered"],2),
                    "shortage": flt(max(so["qty_remaining"] - so["qty_allocated"], 0),2),
                    "qty_to_allocate": flt(so["qty_remaining"] if so["qty_remaining"] > 0 else so["qty_allocated"],2),
                    "so_item": so["detail_name"],
                    "customer": so["customer"],
                    "branch": so["branch"],
                    "conversion_factor": so["conversion_factor"],
                },
            )


def get_reservation_by_item(sale_order, detail_name):
    """
    Fetch the sum of reserved quantities for a specific Sales Order Item
    and calculate the shortage.
    """
    # Sum of reserved_qty from Stock Reservation Entries related to the Sales Order Item
    reserved_qty = frappe.db.sql(
        """
            SELECT SUM(reserved_qty - delivered_qty)
            FROM `tabStock Reservation Entry`
            WHERE
                voucher_type = %s
                AND voucher_no = %s
                AND voucher_detail_no = %s
                AND docstatus = 1
        """,
        ("Sales Order", sale_order, detail_name)
    )[0][0] or 0.0

    return reserved_qty

def process_shortages(item_code=None):
    shortages = []
    if item_code:
        shortages = frappe.get_list(
            "Shortage",
            filters={"docstatus": 1, "item_code": item_code},
            fields=["name", "item_code", "warehouse", "shortage", "voucher_type", "voucher_no", "voucher_detail_no", "allocation", "allocation_detail", "conversion_factor"],
        )
    else:
        shortages = frappe.get_list(
            "Shortage",
            filters={"docstatus": 1},
            fields=["name", "item_code", "warehouse", "shortage", "voucher_type", "voucher_no", "voucher_detail_no", "allocation", "allocation_detail", "conversion_factor"],
        )

    for shortage in shortages:
        reserved_qty = get_reservation_by_item(shortage.voucher_no, shortage.voucher_detail_no)
        if reserved_qty == 0:
            shortage_clone = copy.deepcopy(shortage)
            shortage_clone.update({"qty_to_allocate": shortage.shortage, "so_item": shortage.voucher_detail_no})
            al_doc = frappe.get_doc("Allocation", shortage.allocation)
            al_doc.create_reservation_entries(shortage.voucher_no, shortage_clone)

            # Fetch reserved quantity and calculate shortage
            reserved_qty = get_reservation_by_item(shortage.voucher_no, shortage.voucher_detail_no)
            remaining_qty = shortage.shortage - reserved_qty

            if remaining_qty > 0:
                frappe.db.set_value("Shortage", shortage.name, "shortage", remaining_qty)
            else:
                #frappe.delete_doc("Shortage", shortage.name, force=True)
                doc = frappe.get_doc("Shortage", shortage.name)
                doc.cancel()

            frappe.db.set_value("Allocation Detail", shortage.allocation_detail, "shortage", remaining_qty)
            frappe.db.set_value("Allocation Detail", shortage.allocation_detail, "qty_allocated", reserved_qty)

