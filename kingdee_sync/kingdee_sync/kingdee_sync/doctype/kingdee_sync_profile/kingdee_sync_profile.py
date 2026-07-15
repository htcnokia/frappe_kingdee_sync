import frappe
from frappe.model.document import Document


class KingdeeSyncProfile(Document):
	def validate(self):
		key_rows = [m for m in self.sync_field_mapping if m.is_key]
		if len(key_rows) > 1:
			frappe.throw("字段映射中只能有一行设置为匹配键 (Is Key)")
		if self.sync_field_mapping and len(key_rows) == 0:
			frappe.msgprint(
				"建议设置一行匹配键 (Is Key)，否则同步时无法判断记录是否已存在，同步将会失败。",
				indicator="orange",
				alert=True,
			)

		self._sync_field_keys()

		if self.page_size and self.page_size > 10000:
			frappe.throw("Limit (Page Size) 不能超过 10000")

		if self.is_variant_material and self.target_doctype:
			meta = frappe.get_meta(self.target_doctype)
			if not (meta.has_field("attributes") and meta.has_field("has_variants")):
				frappe.msgprint(
					f"目标 DocType 「{self.target_doctype}」没有 has_variants / attributes 字段，"
					"变体识别通常只对 Item 生效，其他 DocType 上该配置不会起作用。",
					indicator="orange",
					alert=True,
				)

	def _sync_field_keys(self):
		"""确保 Field Keys 中包含: 字段映射所需字段 + 变体辅助属性子字段 + 母件字段。
		不会覆盖用户手工填写的内容，只做"缺什么补什么"。
		"""
		existing = [k.strip() for k in (self.field_keys or "").split(",") if k.strip()]
		existing_set = set(existing)

		def _add(key):
			if key and key not in existing_set:
				existing.append(key)
				existing_set.add(key)

		for m in self.sync_field_mapping:
			_add(m.kingdee_field)

		if self.is_variant_material:
			for va in self.variant_attributes:
				if not va.kingdee_field:
					continue
				if va.key_subfield:
					_add(f"{va.kingdee_field}.{va.key_subfield}")
				else:
					_add(va.kingdee_field)
			_add(self.variant_of_kingdee_field)

		self.field_keys = ",".join(existing)


@frappe.whitelist()
def run_now(profile_name):
	"""前端「立即同步」按钮调用：同步执行一次（会阻塞到完成，适合小数据量的手动触发）。"""
	frappe.only_for("System Manager")
	from kingdee_sync.sync_engine import run_profile

	return run_profile(profile_name, manual=True)


@frappe.whitelist()
def preview(profile_name, rows=5):
	"""前端「预览数据」按钮调用：只查询不写入，用于核对 FieldKeys/FilterString 是否正确。"""
	frappe.only_for("System Manager")
	from kingdee_sync.kingdee_client import execute_bill_query

	profile = frappe.get_doc("Kingdee Sync Profile", profile_name)
	field_keys = profile.field_keys or ",".join(
		[m.kingdee_field for m in profile.sync_field_mapping if m.kingdee_field]
	)
	rows = int(rows) or 5
	return execute_bill_query(
		form_id=profile.form_id,
		field_keys=field_keys,
		filter_string=profile.filter_string,
		order_string=profile.order_string,
		limit=rows,
		top_row_count=rows,
		sub_system_id=profile.sub_system_id,
	)
