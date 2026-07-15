"""
kingdee_client — 金蝶云星空 K3Cloud WebApi 封装。

与老版本（读环境变量 K3_*）不同，本版本所有连接参数都从
`Kingdee Settings` 单据读取（管理员在前端界面配置），
方便非开发人员维护，也便于对接多套 K3 账套（未来可扩展为多 Settings）。

同时兼容两种社区常见的第三方 SDK 包，自动探测：
  - kingdee.cdp.webapi.sdk    (K3CloudApiSdk.Init(config_path, config_node) 方式)
  - k3cloud_webapi_sdk.main   (K3CloudApiSdk.InitConfig(...) 方式)
"""

import configparser
import datetime
import json
import logging
import tempfile

import frappe

logger = logging.getLogger(__name__)

# 按登录用户名缓存 conf.ini 临时文件路径，避免每次查询都重新写文件
_conf_path_cache: dict[str, str] = {}


class KingdeeError(Exception):
	pass


def get_settings() -> dict:
	"""读取 Kingdee Settings 单据，返回连接参数 dict（密码已解密）。"""
	settings = frappe.get_single("Kingdee Settings")
	if not settings.server_url:
		frappe.throw("请先在 [Kingdee Settings] 中配置金蝶云星空连接参数")

	return {
		"server_url": (settings.server_url or "").rstrip("/") + "/",
		"account_id": settings.account_id,
		"app_id": settings.app_id,
		"app_secret": settings.get_password("app_secret", raise_exception=False),
		"username": settings.username,
		"password": settings.get_password("password", raise_exception=False),
		"language": int(settings.language or 2052),
		"org_num": settings.org_num or "0",
	}


def _get_conf_path(cfg: dict) -> str:
	"""把连接参数写入临时 conf.ini，供 kingdee.cdp.webapi.sdk 使用。"""
	cache_key = f"{cfg['server_url']}::{cfg['username']}"
	cached = _conf_path_cache.get(cache_key)
	if cached:
		return cached

	parser = configparser.ConfigParser()
	parser["config"] = {
		"ServerUrl": cfg["server_url"],
		"AccId": cfg["account_id"] or "",
		"AppId": cfg["app_id"] or "",
		"AppSec": cfg["app_secret"] or "",
		"UserName": cfg["username"] or "",
		"Password": cfg["password"] or "",
		"Language": str(cfg["language"]),
		"OrgNum": str(cfg["org_num"]),
	}
	tmp = tempfile.NamedTemporaryFile(suffix=".ini", mode="w", delete=False, encoding="utf-8")
	parser.write(tmp)
	tmp.close()
	_conf_path_cache[cache_key] = tmp.name
	logger.info("K3 conf.ini written to %s", tmp.name)
	return tmp.name


def get_client():
	"""返回已初始化好的 K3CloudApiSdk 实例（自动探测可用的 SDK 包）。"""
	cfg = get_settings()

	try:
		from kingdee.cdp.webapi.sdk import K3CloudApiSdk  # type: ignore  # noqa: PLC0415

		api = K3CloudApiSdk(cfg["server_url"])
		api.Init(config_path=_get_conf_path(cfg), config_node="config")
		return api
	except ImportError:
		pass

	try:
		from k3cloud_webapi_sdk.main import K3CloudApiSdk  # type: ignore  # noqa: PLC0415
	except ImportError:
		frappe.throw(
			"未找到金蝶 WebApi SDK。请在 bench 的 python 环境中安装 "
			"kingdee.cdp.webapi.sdk 或 k3cloud_webapi_sdk 包，例如：<br>"
			"<code>./env/bin/pip install k3cloud_webapi_sdk</code>"
		)

	api = K3CloudApiSdk(cfg["server_url"])
	api.InitConfig(
		cfg["account_id"],
		cfg["username"],
		cfg["app_id"],
		cfg["app_secret"],
		cfg["server_url"],
		cfg["language"],
		int(cfg["org_num"] or 0),
	)
	return api


def verify_login() -> tuple[bool, str]:
	"""调用 ValidateUser 校验 Kingdee Settings 中配置的账号密码是否可登录。"""
	import requests

	cfg = get_settings()
	if not (cfg["account_id"] and cfg["username"] and cfg["password"]):
		return False, "账套ID / 用户名 / 密码 未填写完整"

	try:
		login_url = cfg["server_url"] + "Kingdee.BOS.WebApi.ServicesStub.AuthService.ValidateUser.common.kdsvc"
		payload = {
			"format": 1,
			"useragent": "ApiClient",
			"rid": str(datetime.datetime.now().timestamp()),
			"timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
			"v": "1.0",
			"parameters": [cfg["account_id"], cfg["username"], cfg["password"], str(cfg["language"])],
		}
		resp = requests.post(login_url, json=payload, timeout=15)
		resp.raise_for_status()
		body = resp.json() if resp.content else {}
		if int(body.get("LoginResultType", 0) or 0) == 1:
			return True, "连接成功"
		return False, str(body.get("Message") or body.get("message") or "账号或密码错误")
	except Exception as e:  # noqa: BLE001
		logger.warning("verify_login failed: %s", e)
		return False, str(e)


def _normalize_rows(raw, field_keys: list[str]) -> list[dict]:
	"""
	ExecuteBillQuery 标准返回格式是 [[v1,v2,...], [v1,v2,...], ...]（无字段名，
	按 FieldKeys 顺序对应）。部分 SDK/网关封装可能已经转成 [{"F1": v1, ...}]，
	这里做兼容处理，统一返回 list[dict]。
	"""
	if isinstance(raw, str):
		try:
			raw = json.loads(raw)
		except Exception:  # noqa: BLE001
			logger.error("K3 ExecuteBillQuery 返回内容无法解析为 JSON: %s", raw[:500])
			return []

	if not isinstance(raw, list):
		return []

	rows = []
	for item in raw:
		if isinstance(item, dict):
			rows.append(item)
		elif isinstance(item, list):
			rows.append(dict(zip(field_keys, item)))
	return rows


def execute_bill_query(
	form_id: str,
	field_keys: str,
	filter_string: str = "",
	order_string: str = "",
	limit: int = 2000,
	start_row: int = 0,
	top_row_count: int = 0,
	sub_system_id: str = "",
) -> list[dict]:
	"""
	调用金蝶 ExecuteBillQuery。

	Args:
		form_id:        业务对象表单 Id，如 "BD_MATERIAL"、"BD_Customer"、"BD_Supplier"
		field_keys:     逗号分隔字符串，如 "FMATERIALID,FNumber,FName"
		filter_string:  原样透传的过滤条件字符串（支持 SQL Server 表达式），
		                如 "FCreateOrgId.FNumber='10'"，留空表示不过滤
		order_string:   排序字段
		limit:          单次最大返回行数，不能超过 10000
		start_row:      分页起始行（配合 limit 做翻页）
		top_row_count:  返回总行数上限，0 表示不限制
		sub_system_id:  子系统内码（一般留空）

	Returns:
		list[dict]，key 为 field_keys 中的字段名，按顺序对应。
	"""
	keys = [k.strip() for k in (field_keys or "").split(",") if k.strip()]
	if not keys:
		frappe.throw("Field Keys 不能为空")

	api = get_client()
	data = {
		"FormId": form_id,
		"FieldKeys": ",".join(keys),
		"FilterString": filter_string or "",
		"OrderString": order_string or "",
		"TopRowCount": int(top_row_count or 0),
		"StartRow": int(start_row or 0),
		"Limit": int(limit or 2000),
		"SubSystemId": sub_system_id or "",
	}

	method = getattr(api, "ExecuteBillQuery", None) or getattr(api, "BillQuery", None)
	if method is None:
		frappe.throw("当前 SDK 不支持 ExecuteBillQuery / BillQuery 方法")

	logger.info("K3 ExecuteBillQuery [%s] start_row=%s limit=%s", form_id, start_row, limit)
	resp = method(json.dumps(data, ensure_ascii=False))
	return _normalize_rows(resp, keys)


def execute_bill_query_all(
	form_id: str,
	field_keys: str,
	filter_string: str = "",
	order_string: str = "",
	page_size: int = 2000,
	top_row_count: int = 0,
	sub_system_id: str = "",
	max_pages: int = 200,
) -> list[dict]:
	"""自动分页拉取全部数据（受 top_row_count / max_pages 保护，防止死循环）。"""
	all_rows: list[dict] = []
	start_row = 0
	page_size = min(int(page_size or 2000), 10000)

	while True:
		rows = execute_bill_query(
			form_id,
			field_keys,
			filter_string,
			order_string,
			limit=page_size,
			start_row=start_row,
			top_row_count=top_row_count,
			sub_system_id=sub_system_id,
		)
		all_rows.extend(rows)

		if len(rows) < page_size:
			break
		start_row += page_size
		if top_row_count and start_row >= top_row_count:
			break
		if start_row // page_size >= max_pages:
			logger.warning(
				"K3 ExecuteBillQuery [%s] 达到 max_pages=%s 保护限制，提前停止翻页", form_id, max_pages
			)
			break

	return all_rows
