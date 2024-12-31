from erpnext.manufacturing.doctype.work_order.work_order import WorkOrder

import frappe
from frappe import _
from frappe.utils import cint, flt

class CustomWorkOrder(WorkOrder):
    pass

@frappe.whitelist()
def fetch_operations(routing_name):
    if not routing_name:
        frappe.throw(_("Routing Name are required"))

    operations = frappe.get_all(
        "BOM Operation",
        filters={"parent":  routing_name},
        fields=["operation", "workstation", "time_in_mins"],
    )
    return operations
    
@frappe.whitelist()
def get_converted_qty(item_code, uom, qty):
    try:
        qty = flt(qty)

        # Default conversion rate (no conversion)
        conversion_factor = 1

        # Check if item_code is provided
        if item_code:
            # Fetch the conversion factor for the given UOM and item
            conversion_detail = frappe.db.sql(
                """
                    SELECT conversion_factor
                    FROM `tabUOM Conversion Detail`
                    WHERE parent = %s AND uom = %s
                """, (item_code, uom), as_dict=True)

            if conversion_detail and conversion_detail[0].get('conversion_factor'):
                conversion_factor = flt(conversion_detail[0]['conversion_factor'])
            else:
                frappe.throw(_("No conversion factor found for UOM {0} in item {1}").format(uom, item_code))

        # Calculate the converted quantity
        converted_qty = qty * conversion_factor

        return converted_qty

    except Exception as e:
        frappe.log_error(message=str(e), title="Error in get_converted_qty")
        frappe.throw(_("An error occurred during quantity conversion: {0}").format(str(e)))
