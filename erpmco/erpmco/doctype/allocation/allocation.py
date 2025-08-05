# Copyright (c) 2024, Kossivi Dodzi Amouzou and contributors
# For license information, please see license.txt

from frappe.model.document import Document
import frappe
from frappe import _
from frappe.utils import flt
import copy
from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import cancel_stock_reservation_entries


class Allocation(Document):
    #def before_save(self):
    #    self.populate_details()

    #def after_save(self):
    #    self.update_shortages()

    @frappe.whitelist()
    def reserve_all(self):
        # Handle reservations and shortages for each detail
        warehouse_stock_map = {}
        for detail in self.details:
            #if detail.qty_allocated > 0:
            sales_order = frappe.get_doc("Sales Order", detail.sales_order)

            # Retrieve warehouse_stock_map from cache or initialize a new one
            warehouse_stock_map = frappe.cache().get_value(detail.item_code) or {}

            warehouse_stock_map = get_warehouse_stock_map(detail, warehouse_stock_map)
            warehouse_stock = sum(warehouse_stock_map.values()) #get_parent_stock_by_status(detail.item_code, "FG - MCO")
            if warehouse_stock > 0:
                # Create reservation or shortage entries
                create_stock_reservation_entries(
                    sales_order=sales_order, 
                    item=detail,
                    warehouse_stock_map=warehouse_stock_map,
                )
        #frappe.throw("OK")
        for detail in self.details:
            frappe.cache.delete_value(detail.item_code) 

        #frappe.publish_realtime("after_submit_event", {"docname": self.name})

            

    @frappe.whitelist()
    def cancel_stock_reservation_entries(self, details=None) -> None:
        """Cancel Stock Reservation Entries for Sales Order Items."""

        from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
            cancel_stock_reservation_entries,
        )
        branch = self.branch or "%" 
        customer = self.customer or "%" 
        #sales_order = self.sales_order or "%" 
        #item = self.item or "%"

        unique_orders = set()
        if details != None:
            for detail in details:
                unique_orders.add((detail["sales_order"], detail["item_code"]))
        else:
            for detail in self.details:
                unique_orders.add((detail.sales_order, detail.item_code))

        #result = [{'order_id': order_id, 'items': item} for order_id, item in unique_orders]

        for detail in unique_orders:
            sre_entries = frappe.db.sql(
                """
                SELECT sre.name
                FROM `tabStock Reservation Entry` sre INNER JOIN `tabSales Order` so ON sre.voucher_no = so.name AND sre.docstatus = so.docstatus
                    INNER JOIN  `tabSales Order Item` soi ON sre.voucher_detail_no = soi.name
                WHERE sre.status NOT IN ('Delivered', 'Cancelled') AND so.company = %(company)s AND so.branch LIKE %(branch)s AND so.customer LIKE %(customer)s 
                    AND soi.item_code LIKE %(item)s AND so.name LIKE %(sales_order)s
                """, {"company": self.company, "customer": customer, "sales_order":  detail[0], "branch": branch, "item": detail[1], }, as_dict=1
            )
            
            for sre in sre_entries:
                stock_reservation_entry = frappe.get_doc("Stock Reservation Entry", sre.name)
                stock_reservation_entry.cancel()

                al = frappe.get_doc("Allocation Detail", {"sales_order": stock_reservation_entry.voucher_no, "so_item": stock_reservation_entry.voucher_detail_no})
                frappe.db.set_value("Allocation Detail", al.name, "qty_allocated",  flt(al.qty_allocated - flt(stock_reservation_entry.custom_so_reserved_qty),9))
                frappe.db.set_value("Allocation Detail", al.name, "qty_to_allocate",  flt(al.qty_to_allocate +  flt(stock_reservation_entry.custom_so_reserved_qty),9))
                frappe.db.set_value("Allocation Detail", al.name, "shortage", flt(al.qty_to_allocate +  flt(stock_reservation_entry.custom_so_reserved_qty),9))

    
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
            SELECT *
            FROM
            (
            SELECT DISTINCT
                    so.name AS sales_order,
                    so.transaction_date AS date,
                    soi.item_code,
                    soi.item_name,
                    soi.qty AS qty_ordered,
                    soi.delivered_qty AS qty_delivered,
                    (soi.qty - IFNULL(dn_draft_qty.delivered_qty, 0) - soi.delivered_qty) AS qty_remaining,
                    IFNULL(reserved_stock.custom_so_reserved_qty, 0) AS qty_allocated,
                    (soi.qty - IFNULL(dn_draft_qty.delivered_qty, 0) - soi.delivered_qty) * soi.conversion_factor AS pending_qty_mt,
                    CASE WHEN IFNULL(reserved_stock.reserved_qty, 0) = 0 THEN 0 ELSE
                    CASE WHEN IFNULL(reserved_stock.reserved_qty, 0) - (soi.qty - IFNULL(dn_draft_qty.delivered_qty, 0) - soi.delivered_qty) * soi.conversion_factor < 0 THEN 1 ELSE 2 END END as reserved_status,
                    soi.conversion_factor,
                    soi.stock_qty,
                    soi.warehouse,
                    soi.name as detail_name,
                    so.customer, so.branch
                FROM
                    `tabSales Order` so
                INNER JOIN
                    `tabSales Order Item` soi ON so.name = soi.parent
                LEFT JOIN (
                    SELECT
                        dni.against_sales_order AS sales_order,
                        dni.item_code,
                        SUM(dni.qty) AS delivered_qty
                    FROM
                        `tabDelivery Note` dn
                    INNER JOIN
                        `tabDelivery Note Item` dni ON dn.name = dni.parent
                    WHERE
                        dn.docstatus = 0 -- Only draft delivery notes
                    GROUP BY
                        dni.against_sales_order, dni.item_code
                ) dn_draft_qty 
                    ON so.name = dn_draft_qty.sales_order 
                    AND soi.item_code = dn_draft_qty.item_code
                LEFT JOIN (
                    SELECT
                        sre.item_code,
                        sre.voucher_no AS sales_order,
                        sre.voucher_detail_no AS sales_order_item,
                        SUM(sre.reserved_qty) AS reserved_qty,
                        SUM(sre.custom_so_reserved_qty) AS custom_so_reserved_qty
                    FROM
                        `tabStock Reservation Entry` sre
                    WHERE
                        sre.docstatus = 1
                        AND sre.voucher_type = 'Sales Order'
                    GROUP BY
                        sre.voucher_no, sre.voucher_detail_no, sre.item_code
                ) reserved_stock
                    ON soi.item_code = reserved_stock.item_code
                    AND soi.parent = reserved_stock.sales_order
                    AND soi.name = reserved_stock.sales_order_item
                WHERE
                    so.docstatus = 1
                    AND so.status NOT IN ('Closed', 'Completed')
                    AND (soi.qty - IFNULL(dn_draft_qty.delivered_qty, 0) - soi.delivered_qty) > 0
                    AND so.company = %(company)s AND so.branch LIKE %(branch)s AND so.customer LIKE %(customer)s
                    AND soi.item_code LIKE %(item_code)s AND so.name LIKE %(sales_order)s
                ORDER BY
                    so.transaction_date, so.name, soi.item_code
            ) AS t   
        """

        # Adjust query based on filters
        if self.include_lines_fully_allocated:
            query += " WHERE t.reserved_status <= 2"
        else:
            query += " WHERE t.reserved_status <= 1"

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
                    "qty_ordered": so["qty_ordered"],
                    "qty_allocated": so["qty_allocated"],
                    "qty_delivered": so["qty_delivered"],
                    "shortage": max(so["qty_remaining"] - so["qty_allocated"], 0),
                    "qty_to_allocate": max(so["qty_remaining"] - so["qty_allocated"], 0),
                    "so_item": so["detail_name"],
                    "customer": so["customer"],
                    "branch": so["branch"],
                    "conversion_factor": so["conversion_factor"],
                    "remaining_qty": so["qty_remaining"],
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
            SELECT t.item_code, t.warehouse, t.stock_uom, t.quality_status, t.actual_qty - b.reserved_stock AS actual_qty
            FROM(
                SELECT s.item_code, s.warehouse, i.stock_uom, s.quality_status, SUM(s.actual_qty) AS actual_qty
                FROM `tabStock Ledger Entry` s INNER JOIN `tabItem` i ON s.item_code = i.item_code
                WHERE s.posting_date <= CURDATE() AND i.name = %s AND s.quality_status = %s AND  s.warehouse = %s
                GROUP BY s.item_code, s.warehouse, i.stock_uom, s.quality_status
            ) AS t INNER JOIN tabBin b ON t.item_code = b.item_code AND t.warehouse = b.warehouse
            """,(item_code, status, warehouse), as_dict=1
        )
    return result

def get_parent_stock_by_status(item_code, warehouse, status="A"):
    result =  frappe.db.sql(
            """
            SELECT t.item_code, t.warehouse, t.stock_uom, t.quality_status, t.actual_qty - b.reserved_stock AS actual_qty
            FROM(
                SELECT s.item_code, s.warehouse, i.stock_uom, s.quality_status, SUM(s.actual_qty) AS actual_qty
                FROM `tabStock Ledger Entry` s INNER JOIN `tabItem` i ON s.item_code = i.item_code
                    INNER JOIN tabWarehouse w On s.warehouse = w.name
                WHERE s.posting_date <= CURDATE() AND i.name = %s AND s.quality_status = %s AND  w.parent_warehouse = %s
                GROUP BY s.item_code, s.warehouse, i.stock_uom, s.quality_status
            ) AS t INNER JOIN tabBin b ON t.item_code = b.item_code AND t.warehouse = b.warehouse
            """,(item_code, status, warehouse), as_dict=1
        )
    return result


def get_warehouse_stock_map(item, warehouse_stock_map):
    from frappe.utils.nestedset import get_descendants_of

    # Check if the warehouse is a parent
    is_group = frappe.get_cached_value("Warehouse", item.warehouse, "is_group")
    child_warehouses = (
        get_descendants_of("Warehouse", item.warehouse) if is_group else [item.warehouse]
    )
    for warehouse in child_warehouses:
        # Check if warehouse data is already cached
        if not warehouse in warehouse_stock_map:
            warehouse_stock = get_available_stock_by_status(item.item_code, warehouse)
            for s in warehouse_stock:
                available_qty = s.actual_qty or 0
                if available_qty > 0:
                    warehouse_stock_map[warehouse] = available_qty
                    frappe.cache().set_value(item.item_code, warehouse_stock_map)

    return warehouse_stock_map


def create_stock_reservation_entries(
    sales_order: object,
    item: dict,
    warehouse_stock_map: dict,
    notify=True,
) -> None:
    """Creates Stock Reservation Entries for Sales Order Items."""
    
    #frappe.msgprint("create_stock_reservation_entries")
    # Aggregate available stock across child warehouses
    total_available_stock = flt(sum(warehouse_stock_map.values()),9)
    #frappe.msgprint(f"total_available_stock  {total_available_stock}")
    #warehouse_stock_map = {}
    sre_count = 0

    if total_available_stock <= 0:
        return
    else:
        # Distribute reservation across child warehouses
        qty_to_be_reserved = flt(item.qty_to_allocate * item.conversion_factor,9) or 0

        if qty_to_be_reserved <= 0:
            frappe.throw("No stock to reserve.")

        reserved_qty = min(qty_to_be_reserved, total_available_stock)
        qty_allocated = 0

        qty_to_allocate = flt(item.qty_to_allocate,9)

        # Fetch additional item details from Sales Order Item
        so_item_data = frappe.db.sql("""
            SELECT *
            FROM `tabSales Order Item`
            WHERE name = %s
        """, (item.so_item), as_dict=True)

        for warehouse in warehouse_stock_map.keys():
            warehouse_stock = warehouse_stock_map[warehouse]
            #frappe.msgprint("avant if")
            if warehouse_stock > 0 or reserved_qty > 0:
                #frappe.msgprint("apres if")
                
                args = frappe._dict({
                    "doctype": "Stock Reservation Entry",
                    "item_code": item.item_code,
                    "warehouse": warehouse,
                    "voucher_type": sales_order.doctype,
                    "voucher_no": sales_order.name,
                    "voucher_detail_no": item.so_item,
                    "available_qty": total_available_stock,
                    "voucher_qty": item.remaining_qty, #Ajout de remaining qty
                    "reserved_qty": reserved_qty if warehouse_stock >= reserved_qty else warehouse_stock,
                    "company": sales_order.company,
                    "stock_uom": so_item_data[0].stock_uom,
                    "project": sales_order.project,
                    "reservation_based_on": "Qty",
                    #"has_batch_no": 1,
                    "custom_uom": so_item_data[0].uom,
                    "custom_conversion_factor": item.conversion_factor,
                    "custom_so_available_qty": flt(total_available_stock / item.conversion_factor,9),
                    "custom_so_voucher_qty": so_item_data[0].stock_qty,
                    "custom_so_reserved_qty": flt((reserved_qty if warehouse_stock >= reserved_qty else warehouse_stock) / item.conversion_factor,9) ,
                    #"sb_entries": sb_entries,
                })

                #args.update({"sb_entries": sb_entries})
                sre = frappe.get_doc(args)
                sre.save()
                sre.submit()
                old_qty_allocated = frappe.db.get_value("Allocation Detail", item.name, "qty_allocated") or 0
                #qty_ordered
                qty_allocated = old_qty_allocated + flt((reserved_qty if warehouse_stock >= reserved_qty else warehouse_stock) / item.conversion_factor,9)
                frappe.db.set_value("Allocation Detail", item.name, "qty_allocated",  qty_allocated)
                reserved_qty -= reserved_qty if warehouse_stock >= reserved_qty else warehouse_stock
                if reserved_qty <= 0:
                    break

                sre_count += 1
            
        qty_to_allocate -= qty_allocated
        qty_shortage = so_item_data[0].qty - qty_allocated
        frappe.db.set_value("Allocation Detail", item.name, "qty_to_allocate",  qty_to_allocate)
        frappe.db.set_value("Allocation Detail", item.name, "shortage", qty_shortage)
        if sre_count and notify:
            frappe.msgprint(_("Stock Reservation Entries Created"), alert=True, indicator="green")

