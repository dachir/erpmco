# Copyright (c) 2025, Kossivi Dodzi Amouzou and contributors
# For license information, please see license.txt

import frappe
from frappe import _
import pandas as pd
import numpy as np
from copy import deepcopy



def execute(filters=None):
	filters = frappe._dict(filters or {})
	data, mois = get_data(filters)
	columns = get_columns(filters, mois)
	return columns, data


def get_columns(filters, mois):
	columns = []

	# Colonnes littérales (communes à tous les mois)
	litteral_columns = [
		{"label": _("Branch"), "fieldtype": "Link", "fieldname": "branch", "options": "Branch", "width": 100},
		{"label": _("Category"), "fieldtype": "Data", "fieldname": "category", "width": 100},
		{"label": _("Sub Category"), "fieldtype": "Data", "fieldname": "sub_category", "width": 100},
		{"label": _("Group"), "fieldtype": "Data", "fieldname": "group", "width": 150},
		{"label": _("Item Code"), "fieldtype": "Link", "fieldname": "item_code", "options": "Item", "width": 100, "fixed": 1,},
		{"label": _("Item Name"), "fieldtype": "Data", "fieldname": "item_name", "width": 150, "fixed": 1,},
	]

	# Colonnes numériques de base
	numeric_columns = [
		{"label": _("Qty (CT)"), "fieldtype": "Float", "fieldname": "qty"},
		{"label": _("Qty (MT)"), "fieldtype": "Float", "fieldname": "stock_qty"},
		{"label": _("Free qty"), "fieldtype": "Float", "fieldname": "free_qty"},
		{"label": _("Gross Amount"), "fieldtype": "Currency", "fieldname": "gross_amount"},
		{"label": _("TVA"), "fieldtype": "Currency", "fieldname": "tva"},
		{"label": _("FPI"), "fieldtype": "Currency", "fieldname": "fpi"},
		{"label": _("DDA"), "fieldtype": "Currency", "fieldname": "dda"},
		{"label": _("Net Amount"), "fieldtype": "Currency", "fieldname": "net_amount"},
		{"label": _("Actual Selling Price/CT"), "fieldtype": "Currency", "fieldname": "actual_cost_ct"},
		{"label": _("Actual Selling Price/T"), "fieldtype": "Currency", "fieldname": "actual_cost_t"},
		{"label": _("Actual COGS / T"), "fieldtype": "Currency", "fieldname": "actual_cogs_t"},
		{"label": _("Actual Buying"), "fieldtype": "Currency", "fieldname": "actual_buying"},
		{"label": _("COGS Free Qty / T"), "fieldtype": "Currency", "fieldname": "cogs_free_qty_t"},
		{"label": _("Actual GP"), "fieldtype": "Currency", "fieldname": "actual_gp"},
		{"label": _("Actual GP(%)"), "fieldtype": "Float", "fieldname": "actual_gp_percent"},
		{"label": _("SP/CT"), "fieldtype": "Currency", "fieldname": "price_list_rate"},
		{"label": _("Weight in CT"), "fieldtype": "Float", "fieldname": "weight_in_ct"},
		{"label": _("STD Gorss Sales"), "fieldtype": "Currency", "fieldname": "std_gross_rate"},
		{"label": _("Inv Disc"), "fieldtype": "Currency", "fieldname": "inv_disc"},
		{"label": _("Bonus"), "fieldtype": "Currency", "fieldname": "bonus"},
		{"label": _("Royalty"), "fieldtype": "Currency", "fieldname": "royalty"},
		{"label": _("STD Net Sales CT with Tax"), "fieldtype": "Currency", "fieldname": "std_net_sales_with_tax_ct"},
		{"label": _("STD Net Sales T with Tax"), "fieldtype": "Currency", "fieldname": "std_net_sales_with_tax_t"},
		{"label": _("STD TVA"), "fieldtype": "Currency", "fieldname": "std_tva"},
		{"label": _("STD DDA"), "fieldtype": "Currency", "fieldname": "std_dda"},
		{"label": _("STD FPI"), "fieldtype": "Currency", "fieldname": "std_fpi"},
		{"label": _("STD Net Sales CT"), "fieldtype": "Currency", "fieldname": "std_net_sales_ct"},
		{"label": _("STD Net Sales T"), "fieldtype": "Currency", "fieldname": "std_net_sales_t"},
		{"label": _("Net Material Cost"), "fieldtype": "Currency", "fieldname": "raw_material_cost"},
		{"label": _("Factory Overhead"), "fieldtype": "Currency", "fieldname": "factory_overhead"},
		{"label": _("Other Overhead"), "fieldtype": "Currency", "fieldname": "other_overhead"},
		{"label": _("Labour"), "fieldtype": "Currency", "fieldname": "labour"},
		{"label": _("Depreciation"), "fieldtype": "Currency", "fieldname": "depreciation"},
		{"label": _("COGS / T"), "fieldtype": "Currency", "fieldname": "std_cogs"},
		{"label": _("Gross Profit"), "fieldtype": "Currency", "fieldname": "gp"},
		{"label": _("GP%"), "fieldtype": "Float", "fieldname": "gp_percent"},
		{"label": _("Conversion cost/T"), "fieldtype": "Currency", "fieldname": "conv_cost_t"},
	]

	# Ajouter les colonnes littérales (fixes)
	columns.extend(litteral_columns)

	# Colonnes dynamiques par mois
	for month in mois:
		for base_col in numeric_columns:
			col = deepcopy(base_col)
			col["label"] = f"{base_col['label']} {month}"
			col["fieldname"] = f"{base_col['fieldname']}_{month}"
			col["width"] = base_col.get("width", 80)
			columns.append(col)

	return columns



def get_data(filters=None):
	if not filters:
		filters = {}

	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
	branch = (filters.get("branch") or "") + "%"

	inv_disc_rate = float(filters.get("inv_disc_rate") or 0) / 100
	csh_disc_rate = float(filters.get("csh_disc_rate") or 0) / 100
	bonus_rate = float(filters.get("bonus_rate") or 0) / 100
	royalty_rate = float(filters.get("royalty_rate") or 0) / 100

	# Define the months in the period
	months = pd.date_range(from_date, to_date, freq='MS').strftime('%Y-%m').tolist()

	# Initialize an empty list to hold the monthly dataframes
	monthly_dfs = []

	# Loop through each month in the period
	for month in months:
		# Get the start and end of the month
		month_start = f"{month}-01"
		month_end = pd.to_datetime(month_start) + pd.offsets.MonthEnd(1)

		# Execute the query for each month
		query = f"""
			WITH sales AS (
				SELECT
					sii.item_code,  
					sii.item_name,  
					si.branch,
					MAX(sii.uom) AS uom,
					MAX(ucd.conversion_factor) AS conversion_factor,
					SUM(sii.qty) AS qty,  
					SUM(CASE WHEN sii.stock_uom = 'T' THEN sii.stock_qty ELSE 0 END) AS stock_qty,
					SUM(sii.net_amount) AS net_amount,  
					SUM(sii.amount) AS gross_amount,
					SUM(
						(JSON_UNQUOTE(JSON_EXTRACT(sii.item_tax_rate, '$."44310000 - T.V.A. Charged On Sales - MCO"')) / 100) 
						* sii.net_amount
					) AS tva, 
					SUM(
						(JSON_UNQUOTE(JSON_EXTRACT(sii.item_tax_rate, '$."44210300 - Taxes - FPI on Sales - MCO"')) / 100) 
						* sii.net_amount
					) AS fpi,
					SUM(
						(JSON_UNQUOTE(JSON_EXTRACT(sii.item_tax_rate, '$."44350000 - Droit de Acciss on Sales - MCO"')) / 100) 
						* sii.net_amount
					) AS dda
				FROM `tabSales Invoice` si
				INNER JOIN `tabSales Invoice Item` sii ON si.name = sii.parent 
				INNER JOIN `tabUOM Conversion Detail` ucd ON ucd.parent = sii.item_code AND ucd.uom = sii.uom
				WHERE
					si.docstatus = 1  
					AND si.posting_date BETWEEN %(month_start)s AND %(month_end)s  
					AND si.branch LIKE %(branch)s
				GROUP BY sii.item_code, sii.item_name, si.branch
			),
			ranked_routing AS (
				SELECT r.production_item, b.raw_material_cost, 
						(b.scrap_material_cost * -1) AS scrap_material_credit, 
						b.total_cost,
						(w.hour_rate_electricity * o.time_in_mins / 60) AS factory_overhead, 
						(w.hour_rate_consumable * o.time_in_mins / 60) AS other_overhead, 
						(w.hour_rate_labour * o.time_in_mins / 60) AS labour,
						(w.hour_rate_rent * o.time_in_mins / 60) AS depreciation,
						b.total_cost + ((w.hour_rate_electricity + w.hour_rate_consumable + w.hour_rate_labour + w.hour_rate_rent) * o.time_in_mins / 60) AS std_cogs,
						ROW_NUMBER() OVER (PARTITION BY r.production_item ORDER BY r.name) AS rn
				FROM `tabRouting` r 
				INNER JOIN `tabBOM Operation` o ON o.parent = r.name 
				INNER JOIN `tabWorkstation` w ON w.name = o.workstation
				INNER JOIN `tabBOM` b ON b.item = r.production_item
				WHERE b.docstatus = 1 AND b.is_active = 1 AND b.is_default = 1
			),
			cogs AS (
				SELECT t.item_code, SUM(t.cogs) / SUM(t.stock_qty) AS cogs_rate_t
				FROM(
					SELECT si.name, si.posting_date, si.customer, si.customer_name, dni.item_code, dni.item_name, dni.qty, 
						CASE WHEN dni.stock_uom = 'T' THEN dni.stock_qty ELSE 0 END as stock_qty,
						dni.stock_qty * dni.incoming_rate AS cogs, dni.parent, dni.against_sales_order
					FROM `tabDelivery Note Item` dni 
					INNER JOIN `tabSales Invoice Item` sii on dni.parent = sii.delivery_note and dni.item_code = sii.item_code
					LEFT JOIN `tabSales Invoice` si ON si.name = sii.parent 
					WHERE si.docstatus = 1 
						AND si.posting_date BETWEEN %(month_start)s AND %(month_end)s 
						AND si.branch LIKE %(branch)s
					GROUP BY si.name, si.posting_date, si.customer, si.customer_name, dni.item_code, dni.item_name, 
							dni.qty, dni.stock_qty, dni.amount, dni.parent, dni.against_sales_order
					ORDER BY si.posting_date, si.name
				) AS t
				GROUP BY t.item_code
			)
			SELECT v.*, v.std_net_sales_ct / weight_in_ct AS std_net_sales_t, v.std_net_sales_with_tax_ct / weight_in_ct AS std_net_sales_with_tax_t,
					(v.std_net_sales_ct / weight_in_ct) - v.std_cogs AS gp, gross_amount / qty AS actual_cost_ct, gross_amount / stock_qty AS actual_cost_t,
					CASE WHEN (v.std_net_sales_ct / weight_in_ct) <> 0 THEN 100 * (1 - v.std_cogs / (v.std_net_sales_ct / weight_in_ct)) ELSE 0 END AS gp_percent,
					v.actual_gp / v.net_amount * 100 AS actual_gp_percent, v.actual_buying / v.stock_qty AS actual_cogs_t, 
					v.factory_overhead + v.other_overhead + v.labour + v.depreciation AS conv_cost_t
			FROM(
				SELECT t.*, t.price_list_rate - t.inv_disc - t.cash_disc - t.bonus - t.royalty AS std_net_sales_with_tax_ct, 
						t.net_amount - t.actual_buying AS actual_gp,
						(t.price_list_rate - t.inv_disc - t.cash_disc - t.bonus - t.royalty) * 0.16 / weight_in_ct AS std_tva,
						(t.price_list_rate - t.inv_disc - t.cash_disc - t.bonus - t.royalty) * 0.84 * 0.1 * (IFNULL(dda,0) <> 0) / weight_in_ct AS std_dda,
						(t.price_list_rate - t.inv_disc - t.cash_disc - t.bonus - t.royalty) * 0.84 * (1 - 0.1*(IFNULL(dda,0) <> 0)) * 0.0167 / weight_in_ct AS std_fpi,
						(t.price_list_rate - t.inv_disc - t.cash_disc - t.bonus - t.royalty) * 0.84 * (1 - 0.1*(IFNULL(dda,0) <> 0)) * 0.9833 AS std_net_sales_ct
				FROM (
						SELECT s.*, r.*, ip.price_list, ip.price_list_rate, s.conversion_factor AS weight_in_ct, 
								ip.price_list_rate / s.conversion_factor AS std_gross_rate, 
								ip.price_list_rate * %(inv_disc_rate)s AS inv_disc,
								ip.price_list_rate * %(csh_disc_rate)s * (1 - %(inv_disc_rate)s) AS cash_disc,
								ip.price_list_rate * %(bonus_rate)s * (1 - %(inv_disc_rate)s) * (1 - %(csh_disc_rate)s) AS bonus,
								CASE WHEN LOWER(s.item_name) LIKE '%%band%%' 
									THEN ip.price_list_rate * %(royalty_rate)s * (1 - %(inv_disc_rate)s) * (1 - %(csh_disc_rate)s) 
									ELSE 0 
								END AS royalty, c.cogs_rate_t , c.cogs_rate_t * stock_qty AS actual_buying, c.free_qty, c.cogs_free_qty_t,
								cat.description AS category, scat.description AS sub_category
						FROM sales s 
						INNER JOIN `tabItem Price` ip ON s.item_code = ip.item_code 
						INNER JOIN tabItem i ON i.item_code = ip.item_code
						INNER JOIN `tabFamille Statistique` cat ON cat.name = i.category
						INNER JOIN `tabFamille Statistique` scat ON scat.name = i.sub_category
						INNER JOIN ranked_routing r ON r.production_item = s.item_code AND r.rn = 1
						LEFT JOIN cogs c ON c.item_code = s.item_code
						WHERE LOWER(ip.price_list) LIKE CONCAT(LOWER(s.branch), ' gross', '%%') 
							AND (%(month_start)s >= valid_from AND (%(month_start)s <= valid_upto OR valid_upto IS NULL))
				) AS t
			) AS v
		"""

		# Fetch data for the current month
		result = frappe.db.sql(query, {
			"month_start": month_start,
			"month_end": month_end,
			"branch": branch,
			"inv_disc_rate": inv_disc_rate,
			"csh_disc_rate": csh_disc_rate,
			"bonus_rate": bonus_rate,
			"royalty_rate": royalty_rate
		}, as_dict=True)

		df = pd.DataFrame(result)
		if df.empty:
			continue

		df['group'] = df['category'] + " - " + df['sub_category']
		literal_cols = ["branch", "category", "sub_category", "group", "item_code", "item_name"]
		numeric_cols = [col for col in df.columns if col not in literal_cols]
		df = df[literal_cols + numeric_cols]
		df = df.rename(columns={col: f"{col}_{month}" for col in numeric_cols})
		monthly_dfs.append(df)

	if not monthly_dfs:
		return [], months

	consolidated_df = monthly_dfs[0]
	for df in monthly_dfs[1:]:
		consolidated_df = pd.merge(consolidated_df, df, how='outer', on=literal_cols)

	# Sous-totaux par groupe
	grouped_totals = []
	group_keys = consolidated_df['group'].unique()

	for group in group_keys:
		group_df = consolidated_df[consolidated_df['group'] == group]
		total_row = {col: group_df[col].iloc[0] if col in literal_cols else group_df[col].sum()
						for col in consolidated_df.columns}
		total_row['item_name'] = f"TOTAL {group}"
		total_row['item_code'] = ''
		grouped_totals.append(total_row)

	# Ajoute les lignes de sous-totaux
	consolidated_df = pd.concat([consolidated_df, pd.DataFrame(grouped_totals)], ignore_index=True)

	# Total général
	numeric_columns = [col for col in consolidated_df.columns if col not in literal_cols]
	numeric_columns = [col for col in numeric_columns if consolidated_df[col].dtype in [np.float64, np.int64]]

	total_general = {col: consolidated_df[col].sum() if col in numeric_columns else '' for col in consolidated_df.columns}
	total_general['item_name'] = 'TOTAL GENERAL'

	consolidated_df = pd.concat([consolidated_df, pd.DataFrame([total_general])], ignore_index=True)

	return consolidated_df.fillna(0).to_dict(orient='records'), months
