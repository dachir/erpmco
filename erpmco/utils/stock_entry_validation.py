import frappe
from frappe import _
from erpnext.stock.doctype.stock_ledger_entry.stock_ledger_entry import StockLedgerEntry


def validate_against_stock_ledger(doc, method):
    """Simule les Stock Ledger Entry pour ce Stock Entry
       et applique les mêmes validations métier que les vrais SLE.
    """

    # On ne teste que les brouillons
    if doc.docstatus != 0:
        return

    # Optionnel : ne le faire qu'à certaines étapes du workflow
    # (sinon ça risque d'être lourd à chaque save)
    #states_a_controler = {"À approuver", "Ready to Submit"}
    #workflow_state = doc.get("workflow_state")
    #if workflow_state and workflow_state not in states_a_controler:
    #    return

    # Filtrer les types de Stock Entry (on évite Manufacture/Repack pour ne pas tout casser)
    # doc.purpose est du type "Material Issue", "Material Transfer", etc.
    purposes_a_controler = {"Material Issue"}
    if doc.purpose not in purposes_a_controler:
        return

    # On utilise la même méthode que le core pour générer les SLE
    # (héritée de StockController)
    sl_entries = doc.get_stock_ledger_entries()

    errors = []

    for sle_dict in sl_entries:
        try:
            _run_sle_dry_validation(sle_dict, doc.company)
        except Exception as e:
            # On garde le message pour savoir quelle ligne pose problème
            errors.append(str(e))

    if errors:
        # On remonte une seule erreur avec tous les détails
        frappe.throw(
            _(
                "Ce Stock Entry échouerait au niveau du Stock Ledger. "
                "Corrige les problèmes suivants avant de continuer :<br><br>{msg}"
            ).format(msg="<br>".join(f"- {e}" for e in errors)),
            title=_("Simulation du Stock Ledger"),
        )

def _run_sle_dry_validation(sle_dict, company):
    """Construit un SLE en mémoire et exécute sa logique de validation."""

    sle = frappe.new_doc("Stock Ledger Entry")
    sle.update(sle_dict)
    sle.company = company
    sle.flags.ignore_permissions = True

    # Important : on reste en docstatus = 0 pour ne pas déclencher de logique de submit
    sle.docstatus = 0
    sle.is_cancelled = 0

    # 1) Toutes les validations de SLE.validate()
    #    - mandatory fields
    #    - validate_item (stock item, batch, variants)
    #    - validate_batch (expiration)
    #    - validate_disabled_warehouse
    #    - validate_warehouse_company
    #    - fiscal year
    #    - block_transactions_against_group_warehouse
    #    - validate_with_last_transaction_posting_time (back-dated)
    sle.run_method("validate")

    # 2) On peut aussi tester le freeze de stock
    # (cette méthode ne fait que lire les settings / rôles)
    sle.check_stock_frozen_date()

    # 3) Dry-run Serial No : on ne veut pas modifier les Serial No,
    #    seulement vérifier qu'ils sont valides.
    #_validate_serial_nos_dry_run(sle)

from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos

def _validate_serial_nos_dry_run(sle):
    """Vérifie les Serial No comme le ferait process_serial_no,
       mais sans update des documents.
    """
    if not getattr(sle, "serial_no", None):
        return

    serial_nos = get_serial_nos(sle.serial_no)

    for sn in serial_nos:
        sdoc = frappe.get_doc("Serial No", sn)

        # 1) Le serial doit correspondre au bon item
        if sdoc.item_code != sle.item_code:
            frappe.throw(
                _(
                    "Numéro de série {sn} ne correspond pas à l'article {item} "
                    "pour le mouvement en {wh}."
                ).format(sn=sn, item=sle.item_code, wh=sle.warehouse)
            )

        # 2) Si mouvement sortant (actual_qty < 0), le serial doit être dans le même WH
        if sle.actual_qty < 0 and sdoc.warehouse != sle.warehouse:
            frappe.throw(
                _(
                    "Numéro de série {sn} n'est pas disponible dans l'entrepôt {wh} "
                    "(entrepôt actuel : {cur_wh})."
                ).format(sn=sn, wh=sle.warehouse, cur_wh=sdoc.warehouse or _("Aucun"))
            )

        # 3) Tu peux rajouter ici d'autres règles
        #    (par ex. interdire si status = 'Delivered', etc.)
