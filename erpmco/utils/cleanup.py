import frappe
from frappe.utils import add_days, now_datetime

def delete_old_allocations():
    # Supprimer uniquement les allocations de plus de 1 jour
    cutoff = add_days(now_datetime(), -1)
    allocations = frappe.get_all("Allocation", filters={"creation": ["<", cutoff]}, fields=["name"])

    for alloc in allocations:
        try:
            frappe.delete_doc("Allocation", alloc.name, force=True)
        except Exception as e:
            frappe.log_error(f"Erreur suppression Allocation {alloc.name}: {e}", "Allocation Cleanup")
