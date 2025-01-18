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

class CustomStockEntry(StockEntry):
    
    #def before_save(self):
    #    self.adjust_additional_costs()

    #def on_submit(self):
    #    super().on_submit()

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
        

    def set_basic_rate(self, reset_outgoing_rate=True, raise_error_if_no_rate=True):
        """
        Set rate for outgoing, scrapped and finished items
        """
        # Set rate for outgoing items
        outgoing_items_cost = self.set_rate_for_outgoing_items(reset_outgoing_rate, raise_error_if_no_rate)
        finished_item_qty = sum(d.transfer_qty for d in self.items if d.is_finished_item)

        items = []
        # Set basic rate for incoming items
        for d in self.get("items"):
            d.weight_per_unit = frappe.db.get_value("Item", d.item_code, "weight_per_unit")
            d.weight_uom = frappe.db.get_value("Item", d.item_code, "weight_uom")
            
            if d.s_warehouse or d.set_basic_rate_manually:
                continue

            if d.allow_zero_valuation_rate:
                d.basic_rate = 0.0
                items.append(d.item_code)

            elif d.t_warehouse:
                scrap_in_incoming_cost = frappe.db.get_single_value('Custom Manufacturing Setting', 'scrap_in_incoming_cost')
                if not bool(scrap_in_incoming_cost):
                    if d.is_finished_item:
                        if self.purpose == "Manufacture":
                            d.basic_rate = self.get_basic_rate_for_manufactured_item(
                                finished_item_qty, outgoing_items_cost
                            )
                        elif self.purpose == "Repack":
                            d.basic_rate = self.get_basic_rate_for_repacked_items(d.transfer_qty, outgoing_items_cost)
                else:
                    if self.purpose == "Manufacture":
                        d.basic_rate = self.get_basic_rate_for_manufactured_item(
                            finished_item_qty, outgoing_items_cost 
                        ) * (d.custom_weight_per_unit if d.custom_weight_per_unit else frappe.db.get_value("Item", d.item_code, "weight_per_unit"))
                        #frappe.msgprint("outgoing_items_cost" + str(outgoing_items_cost) + "basic_rate" + str(d.basic_rate))
                    elif self.purpose == "Repack":
                        d.basic_rate = self.get_basic_rate_for_repacked_items(d.transfer_qty, outgoing_items_cost)

            if not d.basic_rate and not d.allow_zero_valuation_rate:
                if self.is_new():
                    raise_error_if_no_rate = False

                d.basic_rate = get_valuation_rate(
                    d.item_code,
                    d.t_warehouse,
                    self.doctype,
                    self.name,
                    d.allow_zero_valuation_rate,
                    currency=erpnext.get_company_currency(self.company),
                    company=self.company,
                    raise_error_if_no_rate=raise_error_if_no_rate,
                    batch_no=d.batch_no,
                    serial_and_batch_bundle=d.serial_and_batch_bundle,
                )

            # do not round off basic rate to avoid precision loss
            d.basic_rate = flt(d.basic_rate)
            d.basic_amount = flt(flt(d.transfer_qty) * flt(d.basic_rate), d.precision("basic_amount"))

        if items:
            message = ""

            if len(items) > 1:
                message = _(
                    "Items rate has been updated to zero as Allow Zero Valuation Rate is checked for the following items: {0}"
                ).format(", ".join(frappe.bold(item) for item in items))
            else:
                message = _(
                    "Item rate has been updated to zero as Allow Zero Valuation Rate is checked for item {0}"
                ).format(frappe.bold(items[0]))

            frappe.msgprint(message, alert=True)

    def get_basic_rate_for_manufactured_item(self, finished_item_qty, outgoing_items_cost=0) -> float:
        scrap_in_incoming_cost = frappe.db.get_single_value('Custom Manufacturing Setting', 'scrap_in_incoming_cost')
        settings = frappe.get_single("Manufacturing Settings")
        scrap_items_cost, scrap_items_qty = map(sum, zip(*((flt(d.basic_amount), flt(d.qty)) for d in self.get("items") if d.is_scrap_item)))

        if settings.material_consumption:
            if settings.get_rm_cost_from_consumption_entry and self.work_order:
                # Validate only if Material Consumption Entry exists for the Work Order.
                if frappe.db.exists(
                    "Stock Entry",
                    {
                        "docstatus": 1,
                        "work_order": self.work_order,
                        "purpose": "Material Consumption for Manufacture",
                    },
                ):
                    for item in self.items:
                        if not item.is_finished_item and not item.is_scrap_item:
                            label = frappe.get_meta(settings.doctype).get_label(
                                "get_rm_cost_from_consumption_entry"
                            )
                            frappe.throw(
                                _(
                                    "Row {0}: As {1} is enabled, raw materials cannot be added to {2} entry. Use {3} entry to consume raw materials."
                                ).format(
                                    item.idx,
                                    frappe.bold(label),
                                    frappe.bold(_("Manufacture")),
                                    frappe.bold(_("Material Consumption for Manufacture")),
                                )
                            )

                    if frappe.db.exists(
                        "Stock Entry",
                        {"docstatus": 1, "work_order": self.work_order, "purpose": "Manufacture"},
                    ):
                        frappe.throw(
                            _("Only one {0} entry can be created against the Work Order {1}").format(
                                frappe.bold(_("Manufacture")), frappe.bold(self.work_order)
                            )
                        )

                    SE = frappe.qb.DocType("Stock Entry")
                    SE_ITEM = frappe.qb.DocType("Stock Entry Detail")

                    outgoing_items_cost = (
                        frappe.qb.from_(SE)
                        .left_join(SE_ITEM)
                        .on(SE.name == SE_ITEM.parent)
                        .select(Sum(SE_ITEM.valuation_rate * SE_ITEM.transfer_qty))
                        .where(
                            (SE.docstatus == 1)
                            & (SE.work_order == self.work_order)
                            & (SE.purpose == "Material Consumption for Manufacture")
                        )
                    ).run()[0][0] or 0

            elif not outgoing_items_cost:
                bom_items = self.get_bom_raw_materials(finished_item_qty)
                outgoing_items_cost = sum([flt(row.qty) * flt(row.rate) for row in bom_items.values()])

        total_cost = 0
        if bool(scrap_in_incoming_cost):
            #incoming_item_weight = sum(d.transfer_qty if d.stock_uom.lower() == "kg" else d.transfer_qty * (d.custom_weight_per_unit if d.custom_weight_per_unit else frappe.db.get_value("Item", d.item_code, "weight_per_unit")) for d in self.items if d.t_warehouse)
            incoming_item_weight = sum(d.transfer_qty * (d.custom_weight_per_unit if d.custom_weight_per_unit else frappe.db.get_value("Item", d.item_code, "weight_per_unit")) for d in self.items if d.t_warehouse)
            #sum_cost = sum(d.amount for d in self.additional_costs)
            total_cost = flt((outgoing_items_cost) / incoming_item_weight)
        return flt((outgoing_items_cost - scrap_items_cost) / finished_item_qty) if not bool(scrap_in_incoming_cost) else total_cost

                
    def distribute_additional_costs(self):
        # If no incoming items, set additional costs blank
        if not any(d.item_code for d in self.items if d.t_warehouse):
            self.additional_costs = []

        self.total_additional_costs = sum(flt(t.base_amount) for t in self.get("additional_costs"))

        if self.purpose in ("Repack", "Manufacture"):
            incoming_items_cost = sum(flt(t.basic_amount) for t in self.get("items") if t.is_finished_item)
        else:
            incoming_items_cost = sum(flt(t.basic_amount) for t in self.get("items") if t.t_warehouse)

        if not incoming_items_cost:
            return

        scrap_in_incoming_cost = frappe.db.get_single_value('Custom Manufacturing Setting', 'scrap_in_incoming_cost')
        #incoming_item_weight = sum(d.transfer_qty if d.stock_uom.lower() == "kg" else d.transfer_qty * (d.custom_weight_per_unit if d.custom_weight_per_unit else frappe.db.get_value("Item", d.item_code, "weight_per_unit")) for d in self.items if d.t_warehouse)
        incoming_item_weight = sum(d.transfer_qty * (d.custom_weight_per_unit if d.custom_weight_per_unit else frappe.db.get_value("Item", d.item_code, "weight_per_unit")) for d in self.items if d.t_warehouse)
        sum_cost = sum(d.amount for d in self.additional_costs)
        for d in self.get("items"):
            if not bool(scrap_in_incoming_cost):
                if self.purpose in ("Repack", "Manufacture") and not d.is_finished_item:
                    d.additional_cost = 0
                    continue
                elif not d.t_warehouse:
                    d.additional_cost = 0
                    continue
                d.additional_cost = (flt(d.basic_amount) / incoming_items_cost) * self.total_additional_costs
            else:
                if self.purpose in ("Repack", "Manufacture") and not d.t_warehouse:
                    d.additional_cost = 0
                    continue
                d.additional_cost = (flt(sum_cost) / incoming_item_weight) * ((d.custom_weight_per_unit if d.custom_weight_per_unit else frappe.db.get_value("Item", d.item_code, "weight_per_unit")) if d.stock_uom.lower() != "kg" else 1) * d.qty 


    def adjust_additional_costs(self):
        if self.work_order and self.stock_entry_type == "Manufacture":
            work_order = frappe.get_doc("Work Order", self.work_order)

            if bool(work_order.custom_use_detail_addtional_cost):
                # Initialize variables
                cost_dict = {}
                total_cost_per_hour = 0
                total_costs = self.total_additional_costs
                operations = work_order.get("operations", [])

                for operation in operations:
                    ws = frappe.get_doc("Workstation", operation.workstation)
                    
                    for line in ws.get("custom_details", []):
                        cost_dict[line.account] = cost_dict.get(line.account, 0) + line.cost
                        total_cost_per_hour += line.cost

                            
                # Clear `additional_costs` to avoid duplication
                self.additional_costs = []
                for account, cost in cost_dict.items():
                    self.append("additional_costs", {
                        "expense_account": account,
                        "account_currency": "USD",
                        "exchange_rate": 1,
                        "description": "Operating Cost as per Work Order / BOM",
                        "amount": cost * total_costs / total_cost_per_hour,
                    })


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


