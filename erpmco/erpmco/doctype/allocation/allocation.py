# Copyright (c) 2024, Kossivi Dodzi Amouzou and contributors
# For license information, please see license.txt

from frappe.model.document import Document
import frappe
from frappe import _
from frappe.utils import flt
import copy


class Allocation(Document):
    #def before_save(self):
    #    self.populate_details()

    def after_save(self):
        self.update_shortages()

    def on_submit(self):
        # Handle reservations and shortages for each detail
        for detail in self.details:
            #if detail.qty_allocated > 0:
            sales_order = frappe.get_doc("Sales Order", detail.sales_order)
            # Create reservation or shortage entries
            create_stock_reservation_entries(
                sales_order=sales_order, item=detail
            )

            

    def create_reservation_entries(self, sales_order, detail):
        # Prepare item details for reservation
        item= {
                "item_code": detail.item_code,
                "warehouse": detail.warehouse,
                "qty_to_reserve": detail.qty_to_allocate,
                "sales_order_item": detail.so_item,
                "allocation": detail.parent,
                "allocation_detail": detail.name,
                "conversion_factor": detail.conversion_factor,
            }

        # Create reservation entries
        create_stock_reservation_entries(
            sales_order=sales_order, item=item
        )



    def update_shortages(self):
        """
        Updates shortage and allocation quantities for each detail.
        """
        for detail in self.details:
            # Fetch reserved quantity and calculate shortage
            reserved_qty = get_reservation_by_item(detail.sales_order, detail.so_item) /(detail.conversion_factor or 1)
            #frappe.throw(str(reserved_qty))
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

    @frappe.whitelist()
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
            WHERE so.docstatus = 1 AND (soi.qty - (soi.stock_reserved_qty  + soi.delivered_qty) / conversion_factor) > 0
                AND so.company = %(company)s AND so.branch LIKE %(branch)s AND so.customer LIKE %(customer)s
                AND soi.item_code LIKE %(item_code)s AND so.name LIKE %(sales_order)s
        """

        # Adjust query based on filters
        if self.include_lines_fully_allocated:
            query += " AND (soi.qty = soi.stock_reserved_qty / conversion_factor OR soi.qty > (soi.stock_reserved_qty + soi.delivered_qty) / conversion_factor)"
        else:
            query += " AND soi.qty > (soi.stock_reserved_qty + soi.delivered_qty) / conversion_factor"

        customer = self.customer if self.customer else "%"
        item_code = self.item if self.item else "%"
        branch = self.branch if self.branch else "%"
        sales_order = self.sales_order if self.sales_order else "%"
        #frappe.throw(str(query))
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
        self.save()


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

    #frappe.throw(str(shortages))
    for shortage in shortages:
        reserved_qty = get_reservation_by_item(shortage.voucher_no, shortage.voucher_detail_no)
        if reserved_qty == 0:
            shortage_clone = copy.deepcopy(shortage)
            shortage_clone.update({"qty_to_allocate": shortage.shortage, "so_item": shortage.voucher_detail_no})
            al_doc = frappe.get_doc("Allocation", shortage.allocation)
            sales_order = frappe.get_doc("Sales Order", shortage.voucher_no,)
            al_doc.create_reservation_entries(sales_order, shortage_clone)

            # Fetch reserved quantity and calculate shortage
            reserved_qty = get_reservation_by_item(shortage.voucher_no, shortage.voucher_detail_no)
            remaining_qty = shortage.shortage - reserved_qty
            #frappe.throw(str(remaining_qty))

            if remaining_qty > 0:
                frappe.db.set_value("Shortage", shortage.name, "shortage", remaining_qty)
            else:
                #frappe.delete_doc("Shortage", shortage.name, force=True)
                doc = frappe.get_doc("Shortage", shortage.name)
                doc.cancel()

            frappe.db.set_value("Allocation Detail", shortage.allocation_detail, "shortage", remaining_qty)
            frappe.db.set_value("Allocation Detail", shortage.allocation_detail, "qty_allocated", reserved_qty)


######################################################################################################################
def get_available_stock_by_status(item_code, warehouse, status="A"):
    result =  frappe.db.sql(
            """
            SELECT s.item_code, s.warehouse, i.stock_uom, s.quality_status, sum(s.actual_qty) AS actual_qty
            FROM `tabStock Ledger Entry` s INNER JOIN `tabItem` i ON s.item_code = i.item_code
            WHERE s.posting_date <= CURDATE() AND i.name = %s AND s.quality_status = %s AND  s.warehouse = %s
            GROUP BY s.item_code, s.warehouse, s.quality_status
            ORDER BY s.item_code, s.warehouse, s.quality_status
            """,(item_code, status, warehouse), as_dict=1
        )
    return result

def create_stock_reservation_entries(
    sales_order: object,
    item: dict | None = None,
    #from_voucher_type: Literal["Pick List", "Purchase Receipt"] = None,
    notify=True,
) -> None:
    """Creates Stock Reservation Entries for Sales Order Items."""
    from frappe.utils.nestedset import get_descendants_of

    # Check if the warehouse is a parent
    is_group = frappe.get_cached_value("Warehouse", item.warehouse, "is_group")
    child_warehouses = (
        get_descendants_of("Warehouse", item.warehouse) if is_group else [item.warehouse]
    )

    # Aggregate available stock across child warehouses
    total_available_stock = 0
    warehouse_stock_map = {}
    sre_count = 0

    for warehouse in child_warehouses:
        warehouse_stock = get_available_stock_by_status(item.item_code, warehouse)
        for s in warehouse_stock:
            available_qty = s.actual_qty or 0
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

    # Distribute reservation across child warehouses
    qty_to_be_reserved = flt(item.qty_to_allocate * item.conversion_factor,9) or 0
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
            "voucher_detail_no": item.so_item,
            "available_qty": available_qty,
            "voucher_qty": flt(item.qty_to_allocate * item.conversion_factor,9),
            "reserved_qty": reserved_qty,
            "company": sales_order.company,
            "stock_uom": frappe.db.get_value("Item", item.item_code, "stock_uom"),
            "project": sales_order.project,
            "reservation_based_on": "Serial and Batch",
            "has_batch_no": 1,
        })

        # Serial and Batch Handling
        sbb_entries = frappe.db.sql(
            """
            SELECT sbe.serial_no, sbe.batch_no, sbe.qty- IFNULL(r.qty,0) As qty, sbe.warehouse
            FROM `tabSerial and Batch Bundle` sbb INNER JOIN `tabSerial and Batch Entry` sbe ON sbe.parent = sbb.name
                INNER JOIN `tabStock Ledger Entry` sle ON sle.serial_and_batch_bundle = sbb.name
                LEFT JOIN (
                    SELECT sbe1.batch_no, SUM(sbe1.qty) AS qty
                    FROM `tabSerial and Batch Entry` sbe1 INNER JOIN `tabStock Reservation Entry` sre ON sbe1.parent = sre.name
                    GROUP BY sbe1.batch_no
                    ) AS r ON r.batch_no = sbe.batch_no AND r.qty < sbe.qty
            WHERE sbb.item_code = %s AND sbb.type_of_transaction = 'Inward' AND sbb.docstatus = 1 AND sle.quality_status = 'A'
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

        if picked_qty > 0:
            args.update({"sb_entries": sb_entries})
            #frappe.throw(str(args))
            sre = frappe.get_doc(args)
            #sre.reservation_based_on = "Serial and Batch"
            sre.save()
            sre.submit()
            sre_count += 1
        
    if sre_count and notify:
        frappe.msgprint(_("Stock Reservation Entries Created"), alert=True, indicator="green")

