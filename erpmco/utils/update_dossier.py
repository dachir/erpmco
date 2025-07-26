# app_name/app_name/patches/hourly/update_dossier.py

import frappe

def update_gl_entry_dossier():
    frappe.db.sql("""
        UPDATE `tabGL Entry` gle
        JOIN `tabPurchase Receipt` pr ON pr.name = gle.voucher_no AND gle.voucher_type = 'Purchase Receipt'
        JOIN `tabPurchase Receipt Item` pri ON pri.parent = pr.name
        SET gle.dossier = pri.purchase_order
        WHERE gle.voucher_type = 'Purchase Receipt'
          AND (gle.dossier IS NULL OR gle.dossier = '');
    """)
    
    frappe.db.sql("""
        UPDATE `tabGL Entry` gle
        JOIN `tabPurchase Invoice` pr ON pr.name = gle.voucher_no AND gle.voucher_type = 'Purchase Invoice'
        JOIN `tabPurchase Invoice Item` pri ON pri.parent = pr.name
        SET gle.dossier = pri.purchase_order
        WHERE gle.voucher_type = 'Purchase Invoice'
          AND (gle.dossier IS NULL OR gle.dossier = '')
          AND (gle.account LIKE '408%');
    """)
