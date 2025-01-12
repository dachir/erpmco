from erpnext.manufacturing.doctype.bom.bom import BOM, add_non_stock_items_cost

import frappe
from frappe import _
from frappe.utils import cint, flt

class CustomBOM(BOM):
    pass
    
def add_additional_cost2(stock_entry, work_order):
	# Add non stock items cost in the additional cost
	stock_entry.additional_costs = []
	company_account = frappe.db.get_value(
		"Company",
		work_order.company,
		["expenses_included_in_valuation", "default_operating_cost_account"],
		as_dict=1,
	)

	expense_account = (
		company_account.default_operating_cost_account or company_account.expenses_included_in_valuation
	)
	add_non_stock_items_cost(stock_entry, work_order, expense_account)
	add_operations_cost2(stock_entry, work_order, expense_account)

def add_operations_cost2(stock_entry, work_order=None, expense_account=None):
    from erpmco.overrides.stock_entry import get_operating_cost_per_unit

    operating_cost_per_unit = get_operating_cost_per_unit(work_order, stock_entry.bom_no)

    frappe.throw(str(operating_cost_per_unit))

    if isinstance(operating_cost_per_unit, float):
        if operating_cost_per_unit:
            stock_entry.append(
                "additional_costs",
                {
                    "expense_account": expense_account,
                    "description": _("Operating Cost as per Work Order / BOM"),
                    "amount": operating_cost_per_unit * flt(stock_entry.fg_completed_qty),
                },
            )

        if work_order and work_order.additional_operating_cost and work_order.qty:
            additional_operating_cost_per_unit = flt(work_order.additional_operating_cost) / flt(work_order.qty)

            if additional_operating_cost_per_unit:
                stock_entry.append(
                    "additional_costs",
                    {
                        "expense_account": expense_account,
                        "description": "Additional Operating Cost",
                        "amount": additional_operating_cost_per_unit * flt(stock_entry.fg_completed_qty),
                    },
                )
    else:
        for key, value in operating_cost_per_unit.items():
            stock_entry.append(
                "additional_costs",
                {
                    "expense_account": key,
                    "description": key,
                    "amount": flt(value) * flt(stock_entry.fg_completed_qty),
                },
            )

