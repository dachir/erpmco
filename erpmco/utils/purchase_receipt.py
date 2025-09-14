import frappe
from erp_space import erpspace

def share_document(doc, method):
    erpspace.share_doc(doc)

def close_todos_on_rejected(doc, method):
    erpspace.close_todos_on_rejected(doc, method)  

def close_previous_state_todos_on_state_change(doc, method):
    erpspace.close_previous_state_todos_on_state_change(doc, method)

def close_todos_on_submit(doc, method):
    erpspace.close_todos_on_submit(doc, method)

def on_workflow_action_on_update(doc, method):
    erpspace.on_workflow_action_on_update(doc, method)



def update_dossier(doc, method):
    # Create a new Dossier document with the purchase_order linked to the current doc's name
    dossier = frappe.get_doc({
        "doctype": "Dossier",
        "purchase_order": doc.name
    })
    # Insert the new Dossier document into the database
    dossier.insert(ignore_permissions=True)


def process_unreconciled_purchase_receipts():
    """
    Processes Purchase Receipts without corresponding Stock Reconciliation entries.
    Creates a Stock Reconciliation for each Purchase Receipt with items having quality_status == "5K".
    """
    # SQL query to fetch Purchase Receipts without corresponding Stock Reconciliation
    purchase_receipts = frappe.db.sql(
        """
            SELECT pr.name, pr.posting_date, pr.posting_time, pr.company, pr.branch, pr.cost_center
            FROM `tabPurchase Receipt` pr INNER JOIN `tabPurchase Receipt Item` pri ON pri.parent = pr.name
            LEFT JOIN `tabStock Reconciliation` sr
            ON sr.custom_purchase_receipt = pr.name
            WHERE sr.name IS NULL AND pr.docstatus = 1 AND pr.is_return = 0 AND pri.quality_status = "5K"
            GROUP BY pr.name, pr.posting_date, pr.posting_time, pr.company, pr.branch, pr.cost_center
        """, as_dict=1)

    for receipt in purchase_receipts:
        # Fetch the Purchase Receipt document
        pr_doc = frappe.get_doc("Purchase Receipt", receipt["name"])

        if pr_doc.is_return:
            continue

        # Create a new Stock Reconciliation document
        sr = frappe.new_doc("Stock Reconciliation")
        sr.posting_date = pr_doc.posting_date
        sr.posting_time = pr_doc.posting_time
        sr.company = pr_doc.company
        sr.purpose = "Stock Reconciliation"
        sr.custom_purchase_receipt = pr_doc.name
        sr.branch = pr_doc.branch
        sr.cost_center = pr_doc.cost_center

        # Filter items with quality_status == "5K" and add to Stock Reconciliation
        for item in pr_doc.items:
            if item.quality_status == "5K":
                # Fetch batch details if required
                batch_data = frappe.db.sql("""
                    SELECT batch_no
                    FROM `tabSerial and Batch Entry`
                    WHERE parent = %s
                """, (item.serial_and_batch_bundle), as_dict=1)

                if batch_data:
                    sr.append("items", {
                        "item_code": item.item_code,
                        "warehouse": item.warehouse,
                        "use_serial_batch_fields": 1,
                        "batch_no": batch_data[0].batch_no,
                        "batch_qty": item.received_qty,
                        "qty": item.received_qty,
                        "valuation_rate": 0.01,
                        "quality_status": item.quality_status
                    })

        # Save and submit the Stock Reconciliation if items were added
        if sr.items:
            sr.insert()
            sr.submit()

        # Commit the transaction
        frappe.db.commit()

        # Log the processing for debugging
        #frappe.log_error(f"Stock Reconciliation created for Purchase Receipt: {pr_doc.name}", "Stock Reconciliation Created")


def on_submit_purchase_receipt(doc, method):
    """
    Lorsqu'un Purchase Receipt est soumis, créer un Stock Reconciliation
    si certains items ont quality_status = "5K".
    """

    if doc.is_return:
        return

    # Vérifier s’il existe déjà un Stock Reconciliation lié
    if frappe.db.exists("Stock Reconciliation", {"custom_purchase_receipt": doc.name}):
        return

    # Sélectionner uniquement les items 5K
    items_5k = frappe.db.sql("""
        SELECT item_code, warehouse, received_qty, quality_status, serial_and_batch_bundle
        FROM `tabPurchase Receipt Item`
        WHERE parent = %s AND quality_status = '5K'
    """, (doc.name,), as_dict=1)

    if not items_5k:
        return  # Rien à faire

    # Créer le Stock Reconciliation
    sr = frappe.new_doc("Stock Reconciliation")
    sr.posting_date = doc.posting_date
    sr.posting_time = doc.posting_time
    sr.company = doc.company
    sr.purpose = "Stock Reconciliation"
    sr.custom_purchase_receipt = doc.name
    sr.branch = getattr(doc, "branch", None)
    sr.cost_center = getattr(doc, "cost_center", None)

    for item in items_5k:
        batch_data = frappe.db.sql("""
            SELECT batch_no
            FROM `tabSerial and Batch Entry`
            WHERE parent = %s
        """, (item.serial_and_batch_bundle,), as_dict=1)

        if batch_data:
            sr.append("items", {
                "item_code": item.item_code,
                "warehouse": item.warehouse,
                "use_serial_batch_fields": 1,
                "batch_no": batch_data[0].batch_no,
                "batch_qty": item.received_qty,
                "qty": item.received_qty,
                "valuation_rate": 0.01,  # ces items sont deja consommes et sont gardes a valeurs minimales
                "quality_status": item.quality_status
            })

    if sr.items:
        sr.insert()
        sr.submit()


