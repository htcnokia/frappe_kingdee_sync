import frappe


def after_install():
	"""安装完成后初始化 Kingdee Settings 单据的默认值。"""
	settings = frappe.get_single("Kingdee Settings")
	changed = False
	if not settings.language:
		settings.language = "2052"
		changed = True
	if not settings.org_num:
		settings.org_num = "0"
		changed = True
	if changed:
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		frappe.db.commit()
