"""
kingdee_sync.tasks

由 hooks.py 中的 scheduler_events["cron"]["*/5 * * * *"] 每 5 分钟调用一次：
遍历所有启用的 Kingdee Sync Profile，用 croniter 判断其 cron_expression
是否已经到期（自 last_sync_time 起下一次触发时间 <= 现在），到期则异步执行。

注意：由于分发器本身只有 5 分钟粒度，若某个方案的 cron 表达式精度细于
5 分钟（例如 "* * * * *" 每分钟），实际效果会退化为每 5 分钟执行一次。
"""

import frappe
from frappe.utils import add_days, get_datetime, now_datetime


def run_due_profiles():
	try:
		from croniter import croniter
	except ImportError:
		frappe.log_error(
			title="Kingdee Sync",
			message="未安装 croniter，无法执行定时同步。请运行: ./env/bin/pip install croniter",
		)
		return

	profiles = frappe.get_all(
		"Kingdee Sync Profile",
		filters={"enabled": 1},
		fields=["name", "cron_expression", "last_sync_time"],
	)

	now = now_datetime()
	for p in profiles:
		cron_expr = (p.cron_expression or "").strip()
		if not cron_expr:
			continue

		base = get_datetime(p.last_sync_time) if p.last_sync_time else add_days(now, -1)
		try:
			itr = croniter(cron_expr, base)
			next_fire = itr.get_next(type(now))
		except Exception:  # noqa: BLE001
			frappe.log_error(
				title="Kingdee Sync",
				message=f"方案 {p.name} 的 Cron 表达式无效: {cron_expr}",
			)
			continue

		if next_fire <= now:
			frappe.enqueue(
				"kingdee_sync.tasks.run_profile_job",
				queue="long",
				job_name=f"kingdee_sync_{p.name}",
				profile_name=p.name,
			)


def run_profile_job(profile_name: str):
	from kingdee_sync.sync_engine import run_profile

	run_profile(profile_name)
