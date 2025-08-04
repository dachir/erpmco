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

from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry

#class CustomStockEntry(StockEntry):

def distribute_additional_costs(self):
    # If no incoming items, set additional costs blank
    if not any(d.item_code for d in self.items if d.t_warehouse):
        self.additional_costs = []

    self.total_additional_costs = sum(flt(t.base_amount) for t in self.get("additional_costs"))

    # Cas spécifique Manufacture avec work order : pondération par poids
    #if self.stock_entry_type == "Manufacture" and self.work_order:
    if self.stock_entry_type == "Manufacture" :
        # Dictionnaire {item_code: poids total}
        item_weights = {
            i.item_code: (frappe.db.get_value("Item", i.item_code, "weight_per_unit") or 0) * i.qty
            for i in self.items
            if i.t_warehouse and frappe.db.get_value("Item", i.item_code, "weight_per_unit")
        }
        total_weight = sum(item_weights.values())

        #if total_weight == 0:
        #    return
        #frappe.throw(str(self.total_outgoing_value))
        if not self.total_outgoing_value:
            return
        global_unit_cost = self.total_outgoing_value / total_weight if total_weight > 0 else 0
        global_unit_add_cost = self.total_additional_costs / total_weight if total_weight > 0 else 0

        for i in self.items:
            if i.t_warehouse and i.item_code in item_weights:
                # Mise à jour des montants de base et des coûts supplémentaires
                i.basic_amount = item_weights[i.item_code] * global_unit_cost
                i.additional_cost = item_weights[i.item_code] * global_unit_add_cost
                i.basic_rate = i.basic_amount / i.qty if i.qty else 0
                i.amount = i.basic_amount + i.additional_cost
                i.valuation_rate = i.amount / i.qty if i.qty else 0
        return  # sortir ici pour éviter le traitement standard

    # Code standard si non Manufacture ou pas de work_order
    if self.purpose in ("Repack"):
        incoming_items_cost = sum(flt(t.basic_amount) for t in self.get("items") if t.is_finished_item)
    else:
        incoming_items_cost = sum(flt(t.basic_amount) for t in self.get("items") if t.t_warehouse)

    if not incoming_items_cost:
        return

    for d in self.get("items"):
        if self.stock_entry_type != "Manufacture":
            if self.purpose in ("Repack") and not (d.is_finished_item or d.is_scrap_item):
                d.additional_cost = 0
                continue
            elif not d.t_warehouse:
                d.additional_cost = 0
                continue
            d.additional_cost = (flt(d.basic_amount) / incoming_items_cost) * self.total_additional_costs



StockEntry.distribute_additional_costs = distribute_additional_costs