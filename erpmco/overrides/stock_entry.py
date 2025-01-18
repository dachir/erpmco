import frappe
from frappe import _
from frappe.utils import flt
from collections import Counter
from frappe.query_builder.functions import Sum
import erpnext
from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry
from erpnext.stock.stock_ledger import NegativeStockError, get_previous_sle, get_valuation_rate
from erpmco.overrides.bom import add_additional_cost2
from erpnext.manufacturing.doctype.bom.bom import get_op_cost_from_sub_assemblies
from frappe.utils import (
    cint,
    comma_or,
    cstr,
    flt,
    format_time,
    formatdate,
    get_link_to_form,
    getdate,
    nowdate,
)

from erpnext.accounts.general_ledger import process_gl_map
from erpnext.accounts.general_ledger import (
    make_gl_entries,
    make_reverse_gl_entries,
    process_gl_map,
)
from erpnext.stock import get_warehouse_account_map

class CustomStockEntry(StockEntry):
    
    def on_submit(self):
        self.validate_closed_subcontracting_order()
        self.make_bundle_using_old_serial_batch_fields()
        self.update_stock_ledger()
        self.update_work_order()
        self.validate_subcontract_order()
        self.update_subcontract_order_supplied_items()
        self.update_subcontracting_order_status()
        self.update_pick_list_status()

        self.make_gl_entries()

        self.repost_future_sle_and_gle()
        self.update_cost_in_project()
        self.update_transferred_qty()
        self.update_quality_inspection()

        if self.purpose == "Material Transfer" and self.add_to_transit:
            self.set_material_request_transfer_status("In Transit")
        if self.purpose == "Material Transfer" and self.outgoing_stock_entry:
            self.set_material_request_transfer_status("Completed")


    def make_gl_entries(self, gl_entries=None, from_repost=False, via_landed_cost_voucher=False):
        if self.docstatus == 2:
            make_reverse_gl_entries(voucher_type=self.doctype, voucher_no=self.name)

        provisional_accounting_for_non_stock_items = cint(
            frappe.get_cached_value(
                "Company", self.company, "enable_provisional_accounting_for_non_stock_items"
            )
        )

        is_asset_pr = any(d.get("is_fixed_asset") for d in self.get("items"))

        if (
            cint(erpnext.is_perpetual_inventory_enabled(self.company))
            or provisional_accounting_for_non_stock_items
            or is_asset_pr
        ):
            warehouse_account = get_warehouse_account_map(self.company)

            if self.docstatus == 1:
                if not gl_entries:
                    gl_entries = (
                        self.get_gl_entries(warehouse_account, via_landed_cost_voucher)
                        if self.doctype == "Purchase Receipt"
                        else self.get_gl_entries(warehouse_account)
                    )
                make_gl_entries(gl_entries, from_repost=from_repost)


    def get_gl_entries(self, warehouse_account):
        gl_entries = super().get_gl_entries(warehouse_account)

        if self.purpose in ("Repack", "Manufacture"):
            total_basic_amount = sum(flt(t.basic_amount) for t in self.get("items") if t.is_finished_item)
        else:
            total_basic_amount = sum(flt(t.basic_amount) for t in self.get("items") if t.t_warehouse)

        divide_based_on = total_basic_amount

        if self.get("additional_costs") and not total_basic_amount:
            # if total_basic_amount is 0, distribute additional charges based on qty
            divide_based_on = sum(item.qty for item in list(self.get("items")))

        item_account_wise_additional_cost = {}

        for t in self.get("additional_costs"):
            for d in self.get("items"):
                if self.purpose in ("Repack", "Manufacture") and not d.is_finished_item:
                    continue
                elif not d.t_warehouse:
                    continue

                item_account_wise_additional_cost.setdefault((d.item_code, d.name), {})
                item_account_wise_additional_cost[(d.item_code, d.name)].setdefault(
                    t.expense_account, {"amount": 0.0, "base_amount": 0.0}
                )

                multiply_based_on = d.basic_amount if total_basic_amount else d.qty

                item_account_wise_additional_cost[(d.item_code, d.name)][t.expense_account]["amount"] += (
                    flt(t.amount * multiply_based_on) / divide_based_on
                )
                if not t.base_amount:
                    frappe.throw(str("base_amount is null"))
                if not multiply_based_on:
                    frappe.throw(str("multiply_based_on is null"))

                item_account_wise_additional_cost[(d.item_code, d.name)][t.expense_account][
                    "base_amount"
                ] += flt(t.base_amount * multiply_based_on) / divide_based_on

        if item_account_wise_additional_cost:
            for d in self.get("items"):
                for account, amount in item_account_wise_additional_cost.get(
                    (d.item_code, d.name), {}
                ).items():
                    if not amount:
                        continue

                    gl_entries.append(
                        self.get_gl_dict(
                            {
                                "account": account,
                                "against": d.expense_account,
                                "cost_center": d.cost_center,
                                "remarks": self.get("remarks") or _("Accounting Entry for Stock"),
                                "credit_in_account_currency": flt(amount["amount"]),
                                "credit": flt(amount["base_amount"]),
                            },
                            item=d,
                        )
                    )

                    gl_entries.append(
                        self.get_gl_dict(
                            {
                                "account": d.expense_account,
                                "against": account,
                                "cost_center": d.cost_center,
                                "remarks": self.get("remarks") or _("Accounting Entry for Stock"),
                                "credit": -1
                                * amount[
                                    "base_amount"
                                ],  # put it as negative credit instead of debit purposefully
                            },
                            item=d,
                        )
                    )

        return process_gl_map(gl_entries)
        
    

def get_operating_cost_per_unit(work_order=None, bom_no=None):
    operating_cost_per_unit = 0
    use_detail_addtional_cost = 0
    if work_order:
        use_detail_addtional_cost = work_order.use_detail_addtional_cost

    if not bool(use_detail_addtional_cost):
        if work_order:
            if (
                bom_no
                and frappe.db.get_single_value(
                    "Manufacturing Settings", "set_op_cost_and_scrape_from_sub_assemblies"
                )
                and frappe.get_cached_value("Work Order", work_order, "use_multi_level_bom")
            ):
                return get_op_cost_from_sub_assemblies(bom_no)

            if not bom_no:
                bom_no = work_order.bom_no

            for d in work_order.get("operations"):
                if flt(d.completed_qty):
                    operating_cost_per_unit += flt(d.actual_operating_cost) / flt(d.completed_qty)
                elif work_order.qty:
                    operating_cost_per_unit += flt(d.planned_operating_cost) / flt(work_order.qty)

        # Get operating cost from BOM if not found in work_order.
        if not operating_cost_per_unit and bom_no:
            bom = frappe.db.get_value("BOM", bom_no, ["operating_cost", "quantity"], as_dict=1)
            if bom.quantity:
                operating_cost_per_unit = flt(bom.operating_cost) / flt(bom.quantity)

        if (
            work_order
            and work_order.produced_qty
            and cint(
                frappe.db.get_single_value(
                    "Manufacturing Settings", "add_corrective_operation_cost_in_finished_good_valuation"
                )
            )
        ):
            operating_cost_per_unit += flt(work_order.corrective_operation_cost) / flt(work_order.produced_qty)
    else:
        costs_list = []
        if work_order:
            for d in work_order.get('operations', []):
                ws = frappe.get_doc("Workstation", d.workstation)
                total_cost = sum(s.cost for s in ws.custom_details)

                if flt(d.completed_qty):
                    operating_cost_per_unit = flt(d.actual_operating_cost) / flt(d.completed_qty)
                elif work_order.qty:
                    operating_cost_per_unit = flt(d.planned_operating_cost) / flt(work_order.qty)
                else:
                    operating_cost_per_unit = 0  # Handle cases where quantities are zero or None

                costs_dict = {
                    detail.account: (operating_cost_per_unit * detail.cost / total_cost) if total_cost != 0 else 0
                    for detail in ws.custom_details
                }
                costs_list.append(costs_dict)  

            #costs_dict = {k: sum(i.get(k, 0) for i in costs_list) for k in {key for j in costs_list for key in j}}

            # Initialize a Counter object
            total_counter = Counter()
            # Iterate through the list and update the Counter with each dictionary
            for d in costs_list:
                total_counter.update(d)
            # Convert the Counter back to a regular dictionary (optional)
            costs_dict = dict(total_counter)

            #frappe.throw(str(costs_dict))

    return flt(operating_cost_per_unit,9) if not bool(use_detail_addtional_cost) else costs_dict


