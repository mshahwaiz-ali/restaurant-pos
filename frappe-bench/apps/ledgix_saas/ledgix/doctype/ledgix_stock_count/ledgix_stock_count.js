async function load_stock_count_sheet(frm) {
	if (!frm.doc.stock_location) {
		frappe.msgprint(__("Select a Stock Location before loading the count sheet."));
		return;
	}

	const response = await frappe.call({
		method: "ledgix_saas.api.inventory_reorder.count_sheet",
		args: {
			branch: frm.doc.branch || null,
			stock_location: frm.doc.stock_location,
		},
	});
	const payload = response.message || {};
	frm.clear_table("items");
	(payload.items || []).forEach((item) => {
		const row = frm.add_child("items");
		row.item = item.item;
		row.uom = item.uom;
		row.expected_quantity = item.expected_quantity || 0;
		row.valuation_rate = item.valuation_rate || 0;
		row.counted_quantity = 0;
		row.count_confirmed = 0;
	});
	frm.refresh_field("items");

	const unsupported = (payload.unsupported_items || []).length;
	if (unsupported) {
		frappe.show_alert({
			message: __("Count sheet loaded. {0} Lot/Serial tracked item(s) were excluded.", [unsupported]),
			indicator: "orange",
		});
	} else {
		frappe.show_alert({message: __("Count sheet loaded."), indicator: "green"});
	}
}

frappe.ui.form.on("Ledgix Stock Count", {
	refresh(frm) {
		if (frm.doc.docstatus !== 0) return;
		frm.add_custom_button(__("Load Count Sheet"), () => {
			if ((frm.doc.items || []).length) {
				frappe.confirm(
					__("Replace the existing count rows with the current location count sheet?"),
					() => load_stock_count_sheet(frm),
				);
				return;
			}
			load_stock_count_sheet(frm);
		});
	},
});

frappe.ui.form.on("Ledgix Stock Count Item", {
	counted_quantity(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "count_confirmed", 1);
	},
});
