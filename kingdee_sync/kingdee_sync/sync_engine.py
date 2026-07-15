"""
kingdee_sync.sync_engine

按 `Kingdee Sync Profile` 的配置执行一次同步：
    K3 ExecuteBillQuery -> (可选)自动建 Frappe 自定义字段 -> 按字段映射转换
    -> (可选)解析变体属性 -> upsert 到目标 Frappe DocType

结果记录写入 `Kingdee Sync Log`，并回写 Profile 上的 last_sync_* 字段。
"""

import json

import frappe
from frappe.utils import cint, cstr, flt, now_datetime

from kingdee_sync.custom_field_utils import ensure_custom_field
from kingdee_sync.kingdee_client import execute_bill_query_all


def run_profile(profile_name: str, manual: bool = False) -> dict:
	profile = frappe.get_doc("Kingdee Sync Profile", profile_name)

	if not profile.enabled and not manual:
		return {"status": "Skipped", "message": "方案未启用"}

	log = frappe.new_doc("Kingdee Sync Log")
	log.profile = profile.name
	log.start_time = now_datetime()
	log.status = "Failed"

	created = updated = failed = 0
	total = 0
	messages: list[str] = []

	try:
		mapping = profile.sync_field_mapping
		if not mapping:
			frappe.throw("请先在方案中配置字段映射 (Field Mapping)")

		key_rows = [m for m in mapping if cint(m.is_key)]
		if len(key_rows) != 1:
			frappe.throw("字段映射中必须且只能有一行设置为匹配键 (Is Key)")
		key_map = key_rows[0]

		if cint(profile.auto_create_custom_fields):
			_ensure_profile_custom_fields(profile, mapping)

		field_keys = profile.field_keys or ",".join([m.kingdee_field for m in mapping if m.kingdee_field])

		log.request_params = json.dumps(
			{
				"FormId": profile.form_id,
				"FieldKeys": field_keys,
				"FilterString": profile.filter_string,
				"OrderString": profile.order_string,
				"Limit": profile.page_size,
				"TopRowCount": profile.top_row_count,
			},
			ensure_ascii=False,
			indent=2,
		)

		rows = execute_bill_query_all(
			form_id=profile.form_id,
			field_keys=field_keys,
			filter_string=profile.filter_string,
			order_string=profile.order_string,
			page_size=cint(profile.page_size) or 2000,
			top_row_count=cint(profile.top_row_count),
			sub_system_id=profile.sub_system_id,
		)
		total = len(rows)

		meta = frappe.get_meta(profile.target_doctype)

		# 变体属性的辅助资料字典只需按方案预取一次，避免逐行查询 K3
		lookup_maps = _build_variant_lookup_maps(profile) if cint(profile.is_variant_material) else {}

		for row in rows:
			try:
				result = _upsert_row(profile, meta, mapping, key_map, row, lookup_maps)
				if result == "created":
					created += 1
				elif result == "updated":
					updated += 1
			except Exception as row_exc:  # noqa: BLE001
				failed += 1
				messages.append(f"[{row.get(key_map.kingdee_field)}] {row_exc}")
				frappe.log_error(
					title=f"Kingdee Sync 行失败: {profile.name}",
					message=frappe.get_traceback(),
				)

		frappe.db.commit()
		log.status = "Success" if failed == 0 else "Partial Success"

	except Exception as exc:  # noqa: BLE001
		messages.insert(0, str(exc))
		log.status = "Failed"
		frappe.log_error(title=f"Kingdee Sync 失败: {profile_name}", message=frappe.get_traceback())
		frappe.db.rollback()

	log.end_time = now_datetime()
	log.total_rows = total
	log.created_count = created
	log.updated_count = updated
	log.failed_count = failed
	log.message = "\n".join(messages)[:140000] if messages else ("同步成功" if log.status == "Success" else "")
	log.insert(ignore_permissions=True)
	frappe.db.commit()

	frappe.db.set_value(
		"Kingdee Sync Profile",
		profile.name,
		{
			"last_sync_time": log.end_time,
			"last_sync_status": log.status,
			"last_sync_message": (log.message or "")[:1000],
		},
		update_modified=False,
	)
	frappe.db.commit()

	return {
		"status": log.status,
		"total": total,
		"created": created,
		"updated": updated,
		"failed": failed,
		"log": log.name,
	}


# ----------------------------------------------------------------------
# 自动建 Frappe 自定义字段
#
# 管理员在字段映射/匹配键/变体属性里填的 Frappe 字段名，只要目标 DocType 上
# 还没有（标准字段或已建过的自定义字段都算），就自动用 create_custom_field 建出来。
# 这样 K3 内码（FMATERIALID/FCUSTID/FSupplierId/FEntryID 等，字段名完全由管理员
# 在界面上配置，不写死）都能落地保存，不需要提前手工 Customize Form。
# ----------------------------------------------------------------------


def _ensure_profile_custom_fields(profile, mapping):
	for m in mapping:
		label = f"K3: {m.kingdee_field}"
		if m.is_key:
			label += "（K3内码/匹配键）"
		ensure_custom_field(profile.target_doctype, m.frappe_field, m.value_type, label=label)

	if cint(profile.is_variant_material):
		for va in profile.variant_attributes:
			if va.frappe_id_fieldname:
				ensure_custom_field(
					"Item Attribute Value",
					va.frappe_id_fieldname,
					"Text",
					label=f"K3 内码 ({va.lookup_id_field or 'FEntryID'})",
				)


def _cast_value(fieldtype: str | None, value_type: str, value):
	"""按字段映射里指定的 value_type（或目标字段的 fieldtype 自动推断）做类型转换。"""
	if value is None:
		return None

	vt = (value_type or "Auto").strip()
	if vt == "Auto":
		vt = {
			"Check": "Check",
			"Date": "Date",
			"Datetime": "Datetime",
			"Int": "Number",
			"Float": "Number",
			"Currency": "Number",
			"Percent": "Number",
		}.get(fieldtype or "", "Text")

	if vt == "Check":
		return 1 if str(value).strip().lower() in ("true", "1", "yes") else 0
	if vt == "Number":
		try:
			return flt(value)
		except Exception:  # noqa: BLE001
			return 0
	if vt in ("Date", "Datetime"):
		v = cstr(value).strip()
		# K3 常用 "1900-01-01" 表示空日期，转换为 None 避免污染 Frappe 日期字段
		if not v or v.startswith("1900-01-01"):
			return None
		return v
	if vt == "Link":
		return cstr(value).strip()
	return cstr(value) if value is not None else ""


def _upsert_row(profile, meta, mapping, key_map, row: dict, lookup_maps: dict) -> str:
	target_doctype = profile.target_doctype
	key_value = row.get(key_map.kingdee_field)
	if key_value in (None, ""):
		frappe.throw(f"匹配键字段 {key_map.kingdee_field} 为空，跳过该行")

	values = {}
	for m in mapping:
		if not m.frappe_field or m.kingdee_field not in row:
			continue
		field_meta = meta.get_field(m.frappe_field)
		fieldtype = field_meta.fieldtype if field_meta else None
		values[m.frappe_field] = _cast_value(fieldtype, m.value_type, row.get(m.kingdee_field))

	variant_attrs = (
		_extract_variant_attributes(profile, row, lookup_maps) if cint(profile.is_variant_material) else []
	)

	existing_name = frappe.db.get_value(target_doctype, {key_map.frappe_field: key_value}, "name")

	if existing_name:
		doc = frappe.get_doc(target_doctype, existing_name)
		doc.update(values)
	else:
		doc = frappe.new_doc(target_doctype)
		doc.update(values)

	if cint(profile.is_variant_material):
		_apply_variant_fields(doc, profile, row, variant_attrs)

	doc.flags.ignore_mandatory = True
	if existing_name:
		doc.save(ignore_permissions=True)
		return "updated"

	doc.insert(ignore_permissions=True)
	return "created"


# ----------------------------------------------------------------------
# 变体（物料多规格 / 辅助属性）支持
#
# 金蝶用"辅助资料"类自定义字段（字段名由管理员在 variant_attributes 里配置，
# 不写死，例如 F_WSDY_Assistant_peima）在物料上存一个引用键（如 FId）。
# 这个引用键本身不带编码/名称，需要拿它去辅助资料明细（默认 FormId =
# BOS_ASSISTANTDATA_DETAIL，同样可配置）里按匹配字段（默认 FId）查出对应的
# 具体明细行，取其编码(FNumber)/值(FDataValue)/内码(FEntryID)。
#
# 翻译成 Frappe/ERPNext 的变体体系：
#   - Item Attribute       <- variant_attributes 行里配置的 attribute_name
#   - Item Attribute Value <- 明细行的"值字段"(默认 FDataValue)
#   - Item.attributes 子表行 <- {attribute, attribute_value}
#   - Item.has_variants = 0（解析出变体属性即视为具体规格物料，非母件模板）
#   - Item.variant_of  <- 可选，按 variant_of_kingdee_field 配置反查母件
# 辅助资料明细字典按方案预取一次（而非逐行查询），显著减少对 K3 的请求次数。
# ----------------------------------------------------------------------


def _build_variant_lookup_maps(profile) -> dict:
	"""为每个变体属性配置预取一次辅助资料明细字典。
	返回: {variant_attribute行.name: {引用键(str): 明细行dict}}"""
	maps = {}
	for va in profile.variant_attributes:
		if not (va.kingdee_field and va.lookup_form_id and va.lookup_match_field):
			continue

		field_keys = ",".join(
			filter(None, [va.lookup_match_field, va.lookup_code_field, va.lookup_value_field, va.lookup_id_field])
		)
		try:
			rows = execute_bill_query_all(form_id=va.lookup_form_id, field_keys=field_keys, page_size=2000)
		except Exception:  # noqa: BLE001
			frappe.log_error(
				title=f"Kingdee Sync: 变体属性字典预取失败 ({va.attribute_name})",
				message=frappe.get_traceback(),
			)
			rows = []

		lookup = {}
		for r in rows:
			match_val = r.get(va.lookup_match_field)
			if match_val not in (None, ""):
				lookup[cstr(match_val).strip()] = r
		maps[va.name] = lookup

	return maps


def _extract_variant_attributes(profile, row: dict, lookup_maps: dict) -> list[dict]:
	"""从一行 K3 物料数据中解析出变体属性（attribute/attribute_value），
	并顺带确保对应的 Item Attribute / Item Attribute Value（含内码）已存在。"""
	result = []
	for va in profile.variant_attributes:
		if not va.kingdee_field:
			continue

		raw_key = row.get(f"{va.kingdee_field}.{va.key_subfield}") if va.key_subfield else row.get(va.kingdee_field)
		if raw_key in (None, ""):
			# 该物料未使用此辅助属性
			continue
		raw_key = cstr(raw_key).strip()

		entry = (lookup_maps.get(va.name) or {}).get(raw_key)
		if not entry:
			# 引用键在辅助资料明细字典中未找到匹配项，跳过该属性，不阻断整行同步
			continue

		value_label = entry.get(va.lookup_value_field) or entry.get(va.lookup_code_field)
		if not value_label:
			continue
		value_label = cstr(value_label).strip()
		code_val = entry.get(va.lookup_code_field)
		id_val = entry.get(va.lookup_id_field)

		_ensure_item_attribute_value(
			va.attribute_name,
			value_label,
			abbr=code_val,
			id_fieldname=va.frappe_id_fieldname,
			id_value=id_val,
		)
		result.append({"attribute": va.attribute_name, "attribute_value": value_label})

	return result


def _ensure_item_attribute_value(attribute_name: str, value_label: str, abbr=None, id_fieldname=None, id_value=None):
	"""确保 Item Attribute 及其下的 Item Attribute Value 存在（不存在则自动创建），
	并把辅助资料明细的内码(如 FEntryID)写入 id_fieldname 指定的自定义字段。"""
	if not frappe.db.exists("DocType", "Item Attribute"):
		frappe.throw(
			"当前站点未安装 Item Attribute DocType（通常来自 ERPNext）。"
			"变体识别功能依赖 ERPNext 的物料变体体系，请先安装 ERPNext 或关闭 Is Variant Material。"
		)

	if frappe.db.exists("Item Attribute", attribute_name):
		attr_doc = frappe.get_doc("Item Attribute", attribute_name)
	else:
		attr_doc = frappe.new_doc("Item Attribute")
		attr_doc.attribute_name = attribute_name
		attr_doc.flags.ignore_mandatory = True
		attr_doc.insert(ignore_permissions=True)

	value_row = next(
		(v for v in attr_doc.get("item_attribute_values", []) if (v.attribute_value or "").strip() == value_label),
		None,
	)
	dirty = False
	if not value_row:
		value_row = attr_doc.append(
			"item_attribute_values",
			{
				"attribute_value": value_label,
				"abbr": cstr(abbr or value_label).strip()[:30] or value_label[:30],
			},
		)
		dirty = True

	if id_fieldname and id_value not in (None, ""):
		if frappe.get_meta("Item Attribute Value").has_field(id_fieldname):
			if cstr(value_row.get(id_fieldname) or "") != cstr(id_value):
				value_row.set(id_fieldname, cstr(id_value))
				dirty = True

	if dirty:
		attr_doc.flags.ignore_mandatory = True
		attr_doc.save(ignore_permissions=True)


def _apply_variant_fields(doc, profile, row: dict, variant_attrs: list[dict]):
	"""把解析出的变体属性写入目标单据（仅对支持 has_variants/attributes 的 DocType 生效，
	通常是 Item）。"""
	if not (doc.meta.has_field("attributes") and doc.meta.has_field("has_variants")):
		return
	if not variant_attrs:
		return

	doc.has_variants = 0

	# 同名 attribute 先清掉旧值再写入新值，支持重复同步时刷新
	attr_names = {a["attribute"] for a in variant_attrs}
	doc.set("attributes", [r for r in doc.get("attributes") if r.attribute not in attr_names])
	for a in variant_attrs:
		doc.append("attributes", a)

	if profile.variant_of_kingdee_field:
		parent_val = row.get(profile.variant_of_kingdee_field)
		if parent_val:
			lookup_field = profile.variant_of_frappe_field
			if not lookup_field:
				key_rows = [m for m in profile.sync_field_mapping if m.is_key]
				lookup_field = key_rows[0].frappe_field if key_rows else None
			if lookup_field and doc.meta.has_field("variant_of"):
				parent_name = frappe.db.get_value(profile.target_doctype, {lookup_field: parent_val}, "name")
				if parent_name and parent_name != doc.name:
					doc.variant_of = parent_name
