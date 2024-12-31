import frappe
from frappe import _
from frappe.query_builder.functions import Floor, Sum
from frappe.utils import cint
from pypika.terms import ExistsCriterion
from erpnext.stock.doctype.material_request.material_request import MaterialRequest
#from erpnext.manufacturing.report.bom_stock_report.bom_stock_report import get_bom_stock

class CustomMaterialRequest(MaterialRequest):
    
    def on_submit(self):
        super().on_submit()
        self.create_raw_material_request()

    def create_raw_material_request(self):
        """
        This function is triggered on submission of a Material Request for manufacturing goods.
        It checks for BOM for all items and creates a new Material Request for raw materials if needed.
        """
        if self.material_request_type != "Manufacture":
            return

        raw_material_items = []

        for item in self.items:
            # Check if the item has a BOM
            bom = frappe.db.get_value("BOM", {"item": item.item_code, "is_active": 1, "is_default": 1})

            if not bom:
                frappe.throw(_(f"Item {item.item_code} does not have an active and default BOM."))

            # Get raw materials details using get_bom_stock
            raw_materials = get_bom_stock({
                "bom": bom,
                "qty_to_produce": item.qty,
                "warehouse": item.warehouse,
                "show_exploded_view": 1,  # To include all sub-components
            })

            for rm in raw_materials:
                raw_material_items.append({
                    "item_code": rm["item_code"],
                    "qty": rm["required_qty"],
                    "uom": rm["stock_uom"],
                    "schedule_date": self.schedule_date,
                    "warehouse": item.warehouse,
                })

        if not raw_material_items:
            frappe.msgprint(_("No raw materials required for this Material Request."))
            return

        # Create a new Material Request for raw materials
        new_material_request = frappe.new_doc("Material Request")
        new_material_request.update({
            "material_request_type": "Purchase",
            "transaction_date" : self.transaction_date,
            "schedule_date": self.schedule_date,
            "items": raw_material_items,
            "company": self.company,
            "branch": self.branch,
        })
        
        #new_material_request.wf_user = frappe.session.user
        new_material_request.insert()
        frappe.msgprint(_(f"Raw Material Request {new_material_request.name} created."))



def get_bom_stock(filters):
    """
    Fetch raw material details from a BOM and calculate required quantities.
    Returns a list of dictionaries for each raw material.
    """
    qty_to_produce = filters.get("qty_to_produce")

    if cint(qty_to_produce) <= 0:
        frappe.throw(_("Quantity to Produce should be greater than zero."))

    # Determine whether to use exploded view
    bom_item_table = "`tabBOM Explosion Item`" if filters.get("show_exploded_view") else "`tabBOM Item`"

    # Fetch warehouse hierarchy details
    warehouse_details = frappe.db.get_value(
        "Warehouse", filters.get("warehouse"), ["lft", "rgt"], as_dict=1
    )

    conditions = ""
    if warehouse_details:
        conditions = (
            "EXISTS (SELECT name FROM `tabWarehouse` WH WHERE WH.lft >= %s AND WH.rgt <= %s AND BIN.warehouse = WH.name)"
            % (warehouse_details.lft, warehouse_details.rgt)
        )
    else:
        conditions = "BIN.warehouse = '%s'" % filters.get("warehouse")

    # SQL query to fetch raw materials
    query = f"""
        SELECT
            BI.item_code,BI.description, BI.stock_qty, BI.stock_uom,
            (BI.stock_qty * {qty_to_produce} / BOM.quantity) AS required_qty,
            SUM(BIN.actual_qty) AS actual_qty,
            FLOOR(SUM(BIN.actual_qty) / (BI.stock_qty * {qty_to_produce} / BOM.quantity)) AS max_batches
        FROM  `tabBOM` BOM INNER JOIN {bom_item_table} BI ON BOM.name = BI.parent LEFT JOIN
            `tabBin` BIN ON BI.item_code = BIN.item_code AND ({conditions})
        WHERE BI.parent = '{filters.get("bom")}' AND BI.parenttype = 'BOM'
        GROUP BY BI.item_code
    """

    # Execute query and return results as a list of dictionaries
    results = frappe.db.sql(query, as_dict=True)
    return results
