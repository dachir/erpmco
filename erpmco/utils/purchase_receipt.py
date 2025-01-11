import frappe

def process_unreconciled_purchase_receipts():
    """
    Processes Purchase Receipts without corresponding Stock Reconciliation entries.
    Creates a Stock Reconciliation for each Purchase Receipt with items having quality_status == "5K".
    """
    # SQL query to fetch Purchase Receipts without corresponding Stock Reconciliation
    purchase_receipts = frappe.db.sql("""
        SELECT pr.name, pr.posting_date, pr.posting_time, pr.company, pr.branch, pr.cost_center
        FROM `tabPurchase Receipt` pr
        LEFT JOIN `tabStock Reconciliation` sr
        ON sr.custom_purchase_receipt = pr.name
        WHERE sr.name IS NULL AND pr.docstatus = 1
    """, as_dict=1)

    for receipt in purchase_receipts:
        # Fetch the Purchase Receipt document
        pr_doc = frappe.get_doc("Purchase Receipt", receipt["name"])

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
