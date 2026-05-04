frappe.ui.form.on("LLM Model", {
	onload(frm) {
		const raw = sessionStorage.getItem("lazychat_mcp_erpnext_llm_model_prefill");
		if (raw && frm.is_new()) {
			try {
				const p = JSON.parse(raw);
				sessionStorage.removeItem("lazychat_mcp_erpnext_llm_model_prefill");
				if (p.provider) frm.set_value("provider", p.provider);
				if (p.model_id) frm.set_value("model_id", p.model_id);
				if (p.model_label) frm.set_value("model_label", p.model_label);
				frappe.show_alert({
					message: __("Prefilled from LLM Provider — confirm Model Label is unique, enable, then Save."),
					indicator: "green",
				});
			} catch (e) {
				sessionStorage.removeItem("lazychat_mcp_erpnext_llm_model_prefill");
			}
		}
	},

	refresh(frm) {
		frm.add_custom_button(
			__("New LLM Provider"),
			() => frappe.new_doc("LLM Provider"),
			__("Actions")
		);
		if (frm.doc.provider) {
			frm.add_custom_button(
				__("Edit provider"),
				() => frappe.set_route("Form", "LLM Provider", frm.doc.provider),
				__("Actions")
			);
		}
	},
});

frappe.listview_settings["LLM Model"] = {
	onload(listview) {
		listview.page.add_inner_button(__("New LLM Provider"), () => frappe.new_doc("LLM Provider"));
		listview.page.add_inner_button(__("Import cURL → new provider"), () => {
			const d = lazychat_mcp_erpnext.llm_setup.wrapSetupDialog(
				new frappe.ui.Dialog({
					title: __("New provider from cURL"),
					fields: [
						{
							fieldtype: "Data",
							fieldname: "provider_name",
							label: __("Provider name"),
							reqd: 1,
							default: __("Custom API"),
						},
						{
							fieldtype: "Select",
							fieldname: "provider_type",
							label: __("Provider type"),
							options: "openai_compatible\nanthropic",
							default: "openai_compatible",
							reqd: 1,
						},
						{
							fieldtype: "Long Text",
							fieldname: "curl",
							label: __("cURL"),
							reqd: 1,
						},
					],
					primary_action_label: __("Create & open"),
					primary_action(values) {
						const parsed = lazychat_mcp_erpnext.llm_setup.parseCurl(values.curl || "");
						if (parsed.error) {
							frappe.msgprint({ title: __("cURL"), message: parsed.error, indicator: "red" });
							return;
						}
						d.hide();
						sessionStorage.setItem(
							"lazychat_mcp_erpnext_llm_prefill",
							JSON.stringify({
								provider_name: values.provider_name,
								provider_type: values.provider_type,
								base_url: parsed.base_url,
								api_key: parsed.api_key,
								headers: parsed.headers,
							})
						);
						frappe.new_doc("LLM Provider");
					},
				})
			);
			d.show();
		});
	},
};
