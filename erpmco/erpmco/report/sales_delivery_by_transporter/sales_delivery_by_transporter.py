import frappe
def execute(filters=None):
    # Step 1: Fetch list of transporter names from Supplier master
    transporters = frappe.get_all(
        "Supplier",
        filters={"is_transporter": 1},
        fields=["name"]
    )
    
    # Step 2: Generate dynamic CASE statements for each transporter
    case_statements = []
    columns = [
        {"label": "Delivered Product", "fieldname": "item_code", "fieldtype": "Data", "width": 150},
        {"label": "Item Name", "fieldname": "item_name", "fieldtype": "Data", "width": 150},
        {"label": "Stock UOM", "fieldname": "stock_uom", "fieldtype": "Data", "width": 100}
    ]
    
    for transporter in transporters:
        transporter_name = transporter["name"]
        case_statements.append(f"""
            SUM(CASE WHEN dn.transporter_name = '{transporter_name}' THEN dni.stock_qty ELSE 0 END) AS "cartons_by_{transporter_name}",
            SUM(CASE WHEN dn.transporter_name = '{transporter_name}' THEN (dni.stock_qty * dni.conversion_factor) ELSE 0 END) AS "metric_ton_by_{transporter_name}"
        """)
        
        # Add corresponding columns for each transporter
        columns.append({"label": f"Cartons by {transporter_name}", "fieldname": f"cartons_by_{transporter_name}", "fieldtype": "Float", "width": 120})
        columns.append({"label": f"Metric Ton by {transporter_name}", "fieldname": f"metric_ton_by_{transporter_name}", "fieldtype": "Float", "width": 120})
    
    # Step 3: Join all CASE statements into the main query
    case_statements_sql = ",\n".join(case_statements)

    # Ensure there's no trailing comma by checking if there are any CASE statements
    if case_statements_sql:
        case_statements_sql = ",\n" + case_statements_sql

    query = f"""
        SELECT
            dni.item_code AS "item_code",
            dni.item_name AS "item_name",
            dni.stock_uom AS "stock_uom"
            {case_statements_sql}
        FROM
            `tabDelivery Note` dn
        INNER JOIN
            `tabDelivery Note Item` dni ON dn.name = dni.parent
        WHERE
            dn.docstatus = 1 -- Only consider submitted delivery notes
        GROUP BY
            dni.item_code, dni.item_name, dni.stock_uom
        ORDER BY
            dni.item_code;
    """

    
    # Step 4: Execute the query
    result = frappe.db.sql(query, as_dict=True)
    
    # Step 5: Return columns and result as expected by ERPNext
    return columns, result
