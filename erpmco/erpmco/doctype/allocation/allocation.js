// Copyright (c) 2024, Kossivi Dodzi Amouzou and contributors
// For license information, please see license.txt

frappe.ui.form.on('Allocation', {
    refresh: function (frm) {
        const grid_wrapper = frm.fields_dict.details.grid.wrapper;
        const actions_div = $(grid_wrapper).find('.grid-buttons');

        // 🔹 Fonction utilitaire : effet pulse + fade-out natif
        const highlightRow = (row_name, color) => {
            let $row_el = $(grid_wrapper).find(`[data-name="${row_name}"]`);
            $row_el.css({
                "background-color": color,
                "transition": "transform 0.2s ease-in-out, background-color 1.5s ease"
            }).css("transform", "scale(1.02)");

            setTimeout(() => $row_el.css("transform", "scale(1)"), 200);
            setTimeout(() => $row_el.css("background-color", "#ffffff"), 500);
        };

        // 🔹 Fonction pour mettre à jour les champs d'en-tête depuis le serveur
        const updateHeaderTotalsFromServer = () => {
            if (!frm.doc.item) {
                frm.set_value('total_stock', 0);
                frm.set_value('total_allocated', 0);
                frm.set_value('remaining', 0);
                return;
            }

            frappe.call({
                method: "erpmco.erpmco.doctype.allocation.allocation.get_item_totals", // ⚠️ adapter chemin Python
                args: {
                    item_code: frm.doc.item,
                    warehouse: frm.doc.warehouse || "FG - MCO"
                },
                callback: (r) => {
                    if (r.message) {
                        frm.set_value('total_stock', r.message.total_stock);
                        frm.set_value('total_allocated', r.message.total_allocated);
                        frm.set_value('remaining', r.message.remaining);
                    }
                }
            });
        };

        // ==================== Bouton ✅ Reserve ====================
        let reserve_button = actions_div.find('.btn-reserve');
        if (!reserve_button.length) {
            reserve_button = $('<button class="btn btn-success btn-sm btn-reserve">✅ Reserve</button>')
                .appendTo(actions_div)
                .click(() => {
                    const selected_row_names = frm.fields_dict.details.grid.get_selected();
                    if (!selected_row_names.length) {
                        frappe.msgprint(__('Please select at least one row.'));
                        return;
                    }

                    const details = frm.doc.details
                        .filter(row => selected_row_names.includes(row.name))
                        .map(row => ({
                            sales_order: row.sales_order,
                            item_code: row.item_code,
                            so_item: row.so_item,
                            qty_to_allocate: row.qty_to_allocate,
                            warehouse: row.warehouse,
                            conversion_factor: row.conversion_factor,
                            name: row.name,
                            remaining_qty: row.remaining_qty
                        }));

                    frappe.call({
                        doc: frm.doc,
                        method: "reserve_all",
                        args: { details: details },
                        freeze: true,
                        freeze_message: __("Reserving Stock..."),
                        callback: (r) => {
                            frappe.show_alert({ message: __("✅ Stock Reserved"), indicator: "green" }, 3);
                            if (r.message?.length) {
                                r.message.forEach(updated => {
                                    let row = frm.doc.details.find(x => x.name === updated.name);
                                    if (row) {
                                        row.qty_allocated = updated.qty_allocated;
                                        row.qty_to_allocate = updated.qty_to_allocate;
                                        row.shortage = updated.shortage;
                                        highlightRow(row.name, "#d4edda");
                                    }
                                });
                                frm.refresh_field("details");
                            }
                            updateHeaderTotalsFromServer(); // 🔹 mise à jour des totaux
                            frm.fields_dict.details.grid.grid_rows.forEach(row => {
                                row.doc.check = 0;
                                row.refresh_field('check');
                            });
                            reserve_button.hide();
                        }
                    });
                });
        }

        // ==================== Bouton 🔓 Unreserve ====================
        let unreserve_button = actions_div.find('.btn-unreserve');
        if (!unreserve_button.length) {
            unreserve_button = $('<button class="btn btn-warning btn-sm btn-unreserve">🔓 Unreserve</button>')
                .appendTo(actions_div)
                .click(() => {
                    const selected_row_names = frm.fields_dict.details.grid.get_selected();
                    if (!selected_row_names.length) {
                        frappe.msgprint(__('Please select at least one row.'));
                        return;
                    }

                    const details = frm.doc.details
                        .filter(row => selected_row_names.includes(row.name))
                        .map(row => ({
                            sales_order: row.sales_order,
                            item_code: row.item_code,
                            name: row.name
                        }));

                    frappe.call({
                        doc: frm.doc,
                        method: "cancel_stock_reservation_entries",
                        args: { details: details },
                        freeze: true,
                        freeze_message: __("Unreserving Stock..."),
                        callback: (r) => {
                            frappe.show_alert({ message: __("⚠️ Stock Unreserved"), indicator: "orange" }, 3);
                            if (r.message?.length) {
                                r.message.forEach(updated => {
                                    let row = frm.doc.details.find(x => x.name === updated.name);
                                    if (row) {
                                        row.qty_allocated = updated.qty_allocated;
                                        row.qty_to_allocate = updated.qty_to_allocate;
                                        row.shortage = updated.shortage;
                                        highlightRow(row.name, "#fff3cd");
                                    }
                                });
                                frm.refresh_field("details");
                            }
                            updateHeaderTotalsFromServer(); // 🔹 mise à jour des totaux
                            frm.fields_dict.details.grid.grid_rows.forEach(row => {
                                row.doc.check = 0;
                                row.refresh_field('check');
                            });
                            unreserve_button.hide();
                        }
                    });
                });
        }
        
        // ==================== Bouton 📋 Populate Details ====================
        frm.add_custom_button(__('📋 Populate Details'), () => {
            frappe.call({
                doc: frm.doc,
                method: "populate_details",
                freeze: true,
                freeze_message: __("Populating..."),
                callback: () => {
                    frappe.show_alert({ message: __("📋 Details Updated"), indicator: "blue" }, 3);
                    frm.refresh_field("details");
                    updateHeaderTotalsFromServer(); // 🔹 mise à jour des totaux
                }
            });
        }, __('Tools'));

        // ==================== Bouton 📦✅ Reserve All ====================
        frm.add_custom_button(__('✅ Reserve All'), () => {
            frappe.call({
                doc: frm.doc,
                method: "reserve_all",
                freeze: true,
                freeze_message: __("Reserving All Stock..."),
                callback: (r) => {
                    frappe.show_alert({ message: __("✅ All Stock Reserved"), indicator: "green" }, 3);
                    if (r.message?.length) {
                        r.message.forEach(updated => {
                            let row = frm.doc.details.find(x => x.name === updated.name);
                            if (row) {
                                row.qty_allocated = updated.qty_allocated;
                                row.qty_to_allocate = updated.qty_to_allocate;
                                row.shortage = updated.shortage;
                                highlightRow(row.name, "#d4edda");
                            }
                        });
                        frm.refresh_field("details");
                    }
                    updateHeaderTotalsFromServer(); // 🔹 mise à jour des totaux
                }
            });
        }, __('Tools'));

        // ==================== Bouton 📦🔓 Unreserve All ====================
        frm.add_custom_button(__('🔓 Unreserve All'), () => {
            frappe.call({
                doc: frm.doc,
                method: "cancel_stock_reservation_entries",
                freeze: true,
                freeze_message: __("Unreserving All Stock..."),
                callback: (r) => {
                    frappe.show_alert({ message: __("⚠️ All Stock Unreserved"), indicator: "orange" }, 3);
                    if (r.message?.length) {
                        r.message.forEach(updated => {
                            let row = frm.doc.details.find(x => x.name === updated.name);
                            if (row) {
                                row.qty_allocated = updated.qty_allocated;
                                row.qty_to_allocate = updated.qty_to_allocate;
                                row.shortage = updated.shortage;
                                highlightRow(row.name, "#fff3cd");
                            }
                        });
                        frm.refresh_field("details");
                    }
                    updateHeaderTotalsFromServer(); // 🔹 mise à jour des totaux
                }
            });
        }, __('Tools'));

        // ==================== Gestion visibilité Reserve/Unreserve ====================
        const toggle_buttons_visibility = () => {
            const selected_rows = frm.fields_dict.details.grid.get_selected();
            if (selected_rows.length > 0) {
                reserve_button.show();
                unreserve_button.show();
            } else {
                reserve_button.hide();
                unreserve_button.hide();
            }
        };
        toggle_buttons_visibility();
        $(grid_wrapper).on('change', '.grid-row-check, .grid-select-all', toggle_buttons_visibility);

        // 🔹 Initialisation des totaux au refresh
        updateHeaderTotalsFromServer();
    }
});



/*frappe.ui.form.on("Allocation", {
    
    refresh(frm) {
        frm.add_custom_button(__('Populate Details'), function() {
            //frm.call("populate_details");
            frappe.call({
                doc: frm.doc,
                method: "populate_details",
                freeze: true,
                freeze_message: __("Populating..."),
                callback: (r) => {
                    frm.reload_doc();
                },
            });
        },__('Tools'));

        frm.add_custom_button(__('Reserve All'), function() {
            frappe.call({
                doc: frm.doc,
                method: "reserve_all",
                freeze: true,
                freeze_message: __("Reserving Stock..."),
                callback: (r) => {
                    frm.reload_doc();
                },
            });
        },__('Tools'));
        
        frm.add_custom_button(__('Unreserve All'), function() {
            frappe.call({
                doc: frm.doc,
                method: "cancel_stock_reservation_entries",
                freeze: true,
                freeze_message: __("Unreserving Stock..."),
                callback: (r) => {
                    frm.reload_doc();
                },
            });
        },__('Tools'));
    },

});*/

frappe.ui.form.on("Allocation Detail", {
    qty_to_allocate: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // Exemple : calcul simple
        if (row.qty_to_allocate > Math.max(row.remaining_qty - row.qty_allocated, 0)) {
             frappe.model.set_value(cdt, cdn, "qty_to_allocate", row.remaining_qty - row.qty_allocated);
        }
       

        // Rafraîchir la ligne dans la table
        frm.refresh_field("allocation_detail");
    }
});

