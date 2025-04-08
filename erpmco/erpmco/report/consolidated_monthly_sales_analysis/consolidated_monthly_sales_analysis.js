// Copyright (c) 2025, Kossivi Dodzi Amouzou and contributors
// For license information, please see license.txt

frappe.query_reports["Consolidated Monthly Sales Analysis"] = {
	filters: [
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
            reqd: 1
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            default: frappe.datetime.get_today(),
            reqd: 1
        },
        {
            fieldname: "branch",
            label: __("Branch"),
            fieldtype: "Link",
            options: "Branch"
        },
        {
            fieldname: "inv_disc_rate",
            label: __("Invoice Discount (%)"),
            fieldtype: "Float",
            default: 4
        },
        {
            fieldname: "csh_disc_rate",
            label: __("Cash Discount (%)"),
            fieldtype: "Float",
            default: 3
        },
        {
            fieldname: "bonus_rate",
            label: __("Bonus (%)"),
            fieldtype: "Float",
            default: 1
        },
        {
            fieldname: "royalty_rate",
            label: __("Royalty (%)"),
            fieldtype: "Float",
            default: 6
        }
    ]
};
