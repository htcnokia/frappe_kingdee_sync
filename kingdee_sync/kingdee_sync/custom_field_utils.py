"""
kingdee_sync.custom_field_utils

同步前自动检测目标 DocType 上是否存在所需字段（标准字段或已有自定义字段均可），
不存在则用 Custom Field 自动创建，免去管理员手工 Customize Form 的步骤。
主要用于：
  - 字段映射(Kingdee Sync Field Mapping)里的 frappe_field
  - 匹配键(is_key)字段，用来保存 K3 内码/实体主键，如 FMATERIALID / FCUSTID / FSupplierId
  - 变体属性解析出的辅助资料内码(如 FEntryID)，写到 Item Attribute Value 上
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

# Kingdee Sync Field Mapping 里的 value_type -> 创建自定义字段时使用的 Frappe fieldtype
_FIELDTYPE_FOR_VALUE_TYPE = {
	"Text": "Data",
	"Number": "Float",
	"Check": "Check",
	"Date": "Date",
	"Datetime": "Datetime",
	"Link": "Data",
}


def ensure_custom_field(
	doctype: str,
	fieldname: str,
	value_type: str = "Auto",
	label: str | None = None,
	description: str | None = None,
) -> None:
	"""若 `doctype` 上不存在名为 `fieldname` 的字段，则自动创建一个 Custom Field。
	已存在（无论是标准字段还是之前建过的自定义字段）则直接跳过，安全可重复调用。
	"""
	if not fieldname or not doctype:
		return
	if not frappe.db.exists("DocType", doctype):
		return

	meta = frappe.get_meta(doctype)
	if meta.has_field(fieldname):
		return
	if frappe.db.exists("Custom Field", f"{doctype}-{fieldname}"):
		return

	fieldtype = _FIELDTYPE_FOR_VALUE_TYPE.get((value_type or "Auto").strip(), "Data")
	df = {
		"fieldname": fieldname,
		"label": label or fieldname,
		"fieldtype": fieldtype,
		"description": description,
		"no_copy": 1,
		"print_hide": 1,
	}
	try:
		create_custom_field(doctype, df, ignore_validate=True)
		frappe.clear_cache(doctype=doctype)
	except Exception:  # noqa: BLE001
		frappe.log_error(
			title=f"Kingdee Sync: 自动创建自定义字段失败 ({doctype}.{fieldname})",
			message=frappe.get_traceback(),
		)
