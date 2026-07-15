frappe.ui.form.on("Kingdee Sync Profile", {
	refresh(frm) {
		if (frm.doc.__islocal) return;

		frm.add_custom_button(
			__("立即同步"),
			() => {
				frappe.confirm(__("确定立即执行一次同步吗？数据量较大时可能需要等待。"), () => {
					frappe.call({
						method: "kingdee_sync.kingdee_sync.doctype.kingdee_sync_profile.kingdee_sync_profile.run_now",
						args: { profile_name: frm.doc.name },
						freeze: true,
						freeze_message: __("正在同步，请稍候..."),
						callback(r) {
							if (r.exc) return;
							const res = r.message || {};
							const indicator =
								res.status === "Success" ? "green" : res.status === "Partial Success" ? "orange" : "red";
							frappe.msgprint({
								title: __("同步完成"),
								indicator,
								message: `状态: ${res.status}<br>共 ${res.total} 行，新建 ${res.created}，更新 ${res.updated}，失败 ${res.failed}`,
							});
							frm.reload_doc();
						},
					});
				});
			},
			__("操作")
		);

		frm.add_custom_button(
			__("预览数据"),
			() => {
				frappe.call({
					method: "kingdee_sync.kingdee_sync.doctype.kingdee_sync_profile.kingdee_sync_profile.preview",
					args: { profile_name: frm.doc.name, rows: 5 },
					freeze: true,
					freeze_message: __("正在查询..."),
					callback(r) {
						if (r.exc) return;
						const rows = r.message || [];
						const html = `<pre style="max-height:400px;overflow:auto;">${frappe.utils.escape_html(
							JSON.stringify(rows, null, 2)
						)}</pre>`;
						frappe.msgprint({ title: __("预览（前5行）"), message: html, wide: true });
					},
				});
			},
			__("操作")
		);

		frm.add_custom_button(
			__("查看同步日志"),
			() => {
				frappe.set_route("List", "Kingdee Sync Log", { profile: frm.doc.name });
			},
			__("操作")
		);
	},
});
