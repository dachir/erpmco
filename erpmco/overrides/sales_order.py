import frappe
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder

class CustomSalesOrder(SalesOrder):
    pass

    def on_submit(self):
        pass
        super().on_submit()
        self.create_allocation()


    def create_allocation(self):
        """
        Custom method to handle allocation logic
        """
        allocation_entry = frappe.get_doc({
            "doctype": "Allocation",
            "company": self.company,
            "branch": self.branch,
            "shipment_date": self.delivery_date,
            "customer": self.customer,
            "sales_order": self.name,
        })
        allocation_entry.insert()
        allocation_entry.populate_details()
        allocation_entry.submit()
            

