app_name = "erpmco"
app_title = "Erpmco"
app_publisher = "Kossivi Dodzi Amouzou"
app_description = "Marsavco customization"
app_email = "mcoit@marsavco.com"
app_license = "mit"

import erpmco.overrides.stock_entry

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "erpmco",
# 		"logo": "/assets/erpmco/logo.png",
# 		"title": "Erpmco",
# 		"route": "/erpmco",
# 		"has_permission": "erpmco.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/erpmco/css/erpmco.css"
# app_include_js = "/assets/erpmco/js/erpmco.js"

# include js, css files in header of web template
# web_include_css = "/assets/erpmco/css/erpmco.css"
# web_include_js = "/assets/erpmco/js/erpmco.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "erpmco/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "erpmco/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "erpmco.utils.jinja_methods",
# 	"filters": "erpmco.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "erpmco.install.before_install"
# after_install = "erpmco.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "erpmco.uninstall.before_uninstall"
# after_uninstall = "erpmco.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "erpmco.utils.before_app_install"
# after_app_install = "erpmco.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "erpmco.utils.before_app_uninstall"
# after_app_uninstall = "erpmco.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "erpmco.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

override_doctype_class = {
    #"Purchase Receipt": "erpmco.overrides.purchase_receipt.CustomPurchaseReceipt",
    "Work Order": "erpmco.overrides.work_order.CustomWorkOrder",
    #"Stock Entry": "erpmco.overrides.stock_entry.CustomStockEntry",
    "Stock Reservation Entry": "erpmco.overrides.stock_reservation_entry.CustomStockReservationEntry",
    #"Stock Ledger Entry": "erpmco.overrides.stock_ledger_entry.CustomStockLedgerEntry",
    "Sales Order": "erpmco.overrides.sales_order.CustomSalesOrder",
    "Material Request": "erpmco.overrides.material_request.CustomMaterialRequest",
    #"Delivery Note": "erpmco.overrides.delivery_note.CustomDeliveryNote",
    #"BOM": "erpmco.overrides.stock_entry.CustomStockEntry",
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
    "Purchase Invoice": {
        "validate": "erpmco.utils.purchase_receipt.share_document",
        "on_update": "erp_space.erpspace.ErpSpace.on_workflow_action_on_update",
    },
    "Payment Request": {
        "validate": "erpmco.utils.purchase_receipt.share_document",
        "on_update": "erp_space.erpspace.ErpSpace.on_workflow_action_on_update",
    },
    "Purchase Receipt": {
        "validate": "erpmco.utils.purchase_receipt.share_document",
        "on_update": "erp_space.erpspace.ErpSpace.on_workflow_action_on_update",
    },
    "Material Request": {
        "validate": "erpmco.utils.purchase_receipt.share_document",
        "on_update": "erp_space.erpspace.ErpSpace.on_workflow_action_on_update",
    },
    "Purchase Order": {
        "validate": "erpmco.utils.purchase_receipt.share_document",
        "after_insert": "erpmco.utils.purchase_receipt.update_dossier",
        "on_update": "erp_space.erpspace.ErpSpace.on_workflow_action_on_update",
    },
    "Leave Application": {
        "validate": "erpmco.utils.purchase_receipt.share_document",
        "on_update": "erp_space.erpspace.ErpSpace.on_workflow_action_on_update",
    },
    "Stock Entry": {
        "validate": "erpmco.utils.purchase_receipt.share_document",
        "on_update": "erp_space.erpspace.ErpSpace.on_workflow_action_on_update",
        "on_submit": "erpmco.overrides.stock_entry.create_allocation",
    },
    "Sales Order": {
        "on_submit": "erpmco.overrides.sales_order.create_allocation",
    },
    "*": {
        "submit": "erp_space.erpspace.ErpSpace.close_todos_on_submit",
    },
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
}

# Scheduled Tasks
# ---------------

scheduler_events = {
    "cron": {
        "*/1 * * * *": [
            "erpmco.utils.purchase_receipt.process_unreconciled_purchase_receipts"
        ],
        #"*/10 * * * *": [
        #    "erpmco.erpmco.doctype.allocation.allocation.process_shortages"
        #],
    },
# 	"all": [
# 		"erpmco.tasks.all"
# 	],
# 	"daily": [
# 		"erpmco.tasks.daily"
# 	],
# 	"hourly": [
# 		"erpmco.tasks.hourly"
# 	],
# 	"weekly": [
# 		"erpmco.tasks.weekly"
# 	],
# 	"monthly": [
# 		"erpmco.tasks.monthly"
# 	],
}

# Testing
# -------

# before_tests = "erpmco.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "erpmco.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "erpmco.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["erpmco.utils.before_request"]
# after_request = ["erpmco.utils.after_request"]

# Job Events
# ----------
# before_job = ["erpmco.utils.before_job"]
# after_job = ["erpmco.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"erpmco.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

fixtures = [
    {"dt": "Custom Field", "filters": [["module", "=", "Erpmco"]]},
    {"dt": "Client Script", "filters": [["enabled", "=", 1],["module", "=", "Erpmco"]]},
    {"dt": "Server Script", "filters": [["disabled", "=", 0],["module", "=", "Erpmco"]]},
]

# In your app's hooks.py

scheduler_events = {
    "hourly": [
        "erpmco.utils.update_dossier.update_gl_entry_dossier"
    ],
    "cron": {
        "0 1 * * *": [
            "erpmco.utils.cleanup.delete_old_allocations"
        ]
    }
}

# dans hooks.py
app_include = [
    "erpmco.overrides.stock_entry.CustomStockEntry"
]

