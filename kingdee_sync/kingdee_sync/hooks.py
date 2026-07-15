from . import __version__ as app_version  # noqa: F401

app_name = "kingdee_sync"
app_title = "Kingdee Sync"
app_publisher = "Your Company"
app_description = "从金蝶云星空(K3Cloud) WebApi 同步基础资料/单据到 Frappe，支持前端配置 FormId/FieldKeys/FilterString/OrderString/Limit 及定时任务"
app_email = "admin@example.com"
app_license = "MIT"
app_version = "0.1.0"

required_apps = ["frappe"]

# 安装完成后的初始化
after_install = "kingdee_sync.install.after_install"

# ------------------------------------------------------------------
# 定时任务：每 5 分钟检查一次各 Kingdee Sync Profile 的 Cron 表达式是否到期。
# 到期的方案会通过 frappe.enqueue 异步执行，不阻塞 scheduler。
# ------------------------------------------------------------------
scheduler_events = {
	"cron": {
		"*/5 * * * *": [
			"kingdee_sync.tasks.run_due_profiles",
		]
	}
}

# 如果以后需要在特定 DocType 表单里加自定义 JS/CSS，可以用 doctype_js = {...}
# doctype_js = {}

# fixtures（如果以后需要导出自定义角色/字段等，可在此声明）
# fixtures = []
