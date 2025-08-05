// Copyright (c) 2024, Kossivi Dodzi Amouzou and contributors
// For license information, please see license.txt

frappe.ui.form.on('Allocation', {
    refresh: function (frm) {
        const grid_wrapper = frm.fields_dict.details.grid.wrapper;
        // Find the grid-buttons div
        const actions_div = $(grid_wrapper).find('.grid-buttons');

        // Add a custom button if it doesn't already exist
        let unreserve_button = actions_div.find('.btn-unreserve');
        if (!unreserve_button.length) {
            unreserve_button = $('<button class="btn btn-warning btn-sm btn-unreserve">Unreserve</button>')
                .appendTo(actions_div)
                .click(() => {
                    // Get selected row names
                    const selected_row_names = frm.fields_dict.details.grid.get_selected();
                    if (selected_row_names.length === 0) {
                        frappe.msgprint(__('Please select at least one row.'));
                        return;
                    }

                    // Extract full row data for the selected rows
                    const details = frm.doc.details.filter(row => selected_row_names.includes(row.name)).map(row => ({
                        sales_order: row.sales_order,
                        item_code: row.item_code
                    }));

                    console.log("Selected rows data:", details);

                    frappe.call({
                        doc: frm.doc,
                        method: "cancel_stock_reservation_entries",
                        args: { details: details },
                        freeze: true,
                        freeze_message: __("Unreserving Stock..."),
                        callback: (r) => {
                            // Uncheck all checkboxes
                            frm.fields_dict.details.grid.grid_rows.forEach(row => {
                                row.doc.check = 0; // Uncheck the checkbox
                                row.refresh_field('check'); // Refresh the field to update UI
                            });

                            // Hide the button
                            unreserve_button.hide();
                            frm.reload_doc();
                        },
                        error: function (error) {
                            frappe.msgprint(__('An error occurred while canceling stock reservations.'));
                            console.error(error);
                        }
                    });
                });
        }

        // Check the selected rows in the grid
        const toggle_button_visibility = () => {
            const selected_rows = frm.fields_dict.details.grid.get_selected();
            if (selected_rows.length > 0) {
                unreserve_button.show(); // Show the button if rows are selected
            } else {
                unreserve_button.hide(); // Hide the button if no rows are selected
            }
        };

        // Initial visibility check
        toggle_button_visibility();

        // Re-check visibility whenever a checkbox is clicked in the grid
        $(grid_wrapper).on('change', '.grid-row-check', function () {
            toggle_button_visibility();
        });
    }
});



frappe.ui.form.on("Allocation", {
    
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

});

frappe.ui.form.on("Allocation Detail", {
    qty_to_allocate: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // Exemple : calcul simple
        if (row.qty_to_allocate > row.remaining_qty) {
             row.qty_to_allocate = row.remaining_qty;
        }
       

        // Rafraîchir la ligne dans la table
        frm.refresh_field("allocation_detail");
    }
});

