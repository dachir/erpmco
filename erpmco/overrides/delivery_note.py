import frappe
from erpnext.stock.doctype.delivery_note.delivery_note import DeliveryNote

class CustomDeliveryNote(DeliveryNote):
    pass

@frappe.whitelist()
def fetch_reserved_batches(customer=None):
    query = """
        SELECT 
            sbe.batch_no, 
            (sbe.qty - sbe.delivered_qty) AS qty, 
            sbe.warehouse, 
            sre.item_code, 
            sre.warehouse AS reservation_warehouse, 
            sre.voucher_no AS sales_order, 
            so.customer
        FROM 
            `tabSerial and Batch Entry` sbe 
        INNER JOIN 
            `tabStock Reservation Entry` sre 
            ON sbe.parent = sre.name AND sre.voucher_type = 'Sales Order'
        INNER JOIN 
            `tabSales Order` so 
            ON so.name = sre.voucher_no
        WHERE 
            sbe.qty > sbe.delivered_qty 
            AND sre.docstatus = 1

    """
    result = frappe.db.sql(query, as_dict=True)
    return result



        #               AND  so.customer = %s




    #erpmco.overrides.stock_entry.delivery_note.fetch_reserved_batches
