from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt

import frappe
from frappe.utils import cint, flt
import time
import json

from master_modules.master_modules.event_manager import EventManager

class CustomPurchaseReceipt(PurchaseReceipt):

    def before_save(self):
        # Define conditions for item groups
        group_5k = ['ENG', 'ENGSS', 'ENGCS']
        group_all = ['ITEQP', 'ADMFO', 'LABCH', 'OFF', 'STAT']

        # Update quality_status for matching items
        for item in self.items:
            if self.branch:
                item.branch = self.branch

            # Get item group
            item_group = frappe.db.get_value("Item", item.item_code, "item_group")

            if ((item_group in group_5k and flt(item.valuation_rate) <= 5000) or (item_group in group_all)):
                item.quality_status = "5K"
            else:
                custom_control_quality = frappe.db.get_value("Item", item.item_code, "custom_control_quality")
                if bool(custom_control_quality):
                    item.quality_status = "Q"
                else:
                    item.quality_status = "A"


