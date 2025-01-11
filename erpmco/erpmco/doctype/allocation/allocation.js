// Copyright (c) 2024, Kossivi Dodzi Amouzou and contributors
// For license information, please see license.txt

frappe.ui.form.on("Allocation", {
    refresh(frm) {
        frm.add_custom_button(__('Populate Details'), function() {
            frm.call("populate_details")/*.then(() => {
                frm.reload_doc();
            });*/
        });
    },
});

