frappe.ui.form.on("Kingdee Settings", {
	refresh(frm) {
		frm.add_custom_button(__("测试连接"), () => {
			frappe.call({
				method: "kingdee_sync.kingdee_sync.doctype.kingdee_settings.kingdee_settings.test_connection",
				freeze: true,
				freeze_message: __("正在测试连接..."),
				callback(r) {
					if (r.exc) return;
					const res = r.message || {};
					frappe.msgprint({
						title: res.success ? __("连接成功") : __("连接失败"),
						indicator: res.success ? "green" : "red",
						message: res.message,
					});
				},
			});
		});
	},
});
