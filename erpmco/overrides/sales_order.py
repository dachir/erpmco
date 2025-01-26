import frappe
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder

class CustomSalesOrder(SalesOrder):
    pass

    #def on_submit(self):
    #    super().on_submit()
    #    self.create_allocation()


def create_allocation(doc, method):

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
        allocation_entry.insert()
        allocation_entry.populate_details()
        allocation_entry.reserve_all()
        allocation_entry.submit()
            

