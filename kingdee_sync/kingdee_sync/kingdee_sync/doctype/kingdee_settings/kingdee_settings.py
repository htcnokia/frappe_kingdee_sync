import frappe
from frappe.model.document import Document


class KingdeeSettings(Document):
	pass


@frappe.whitelist()
def test_connection():
	"""前端「测试连接」按钮调用：校验 Kingdee Settings 中的账号密码是否可登录。"""
	frappe.only_for("System Manager")
	from kingdee_sync.kingdee_client import verify_login

	ok, msg = verify_login()
	return {"success": ok, "message": msg}
