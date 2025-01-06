import frappe
from erpnext.stock.doctype.stock_ledger_entry.stock_ledger_entry import StockLedgerEntry
from erpmco.erpmco.doctype.allocation.allocation import process_shortages

class CustomStockLedgerEntry(StockLedgerEntry):
    pass

    def on_submit(self):
        pass
        super().on_submit()

        # Check if the entry is an incoming stock
        #frappe.throw(str(self.actual_qty))
        if self.actual_qty > 0:  # Assuming incoming stock has positive actual_qty
            if frappe.db.exists("Shortage", {"docstatus": 1, "item_code": self.item_code}):
                process_shortages(self.item_code)