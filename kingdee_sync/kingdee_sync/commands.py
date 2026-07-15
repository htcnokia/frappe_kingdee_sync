import click
import frappe


@click.command("kingdee-sync-run")
@click.argument("profile")
def kingdee_sync_run(profile):
	"""手动执行一个 Kingdee Sync Profile。用法: bench --site <site> kingdee-sync-run <profile名>"""
	from kingdee_sync.sync_engine import run_profile as _run

	result = _run(profile, manual=True)
	click.echo(result)


@click.command("kingdee-sync-list")
def kingdee_sync_list():
	"""列出所有 Kingdee Sync Profile 及其最近同步状态。"""
	rows = frappe.get_all(
		"Kingdee Sync Profile",
		fields=["name", "enabled", "form_id", "target_doctype", "last_sync_status", "last_sync_time"],
	)
	for r in rows:
		click.echo(
			f"{r.name} | enabled={r.enabled} | {r.form_id} -> {r.target_doctype} | "
			f"{r.last_sync_status or '-'} | {r.last_sync_time or '-'}"
		)


commands = [kingdee_sync_run, kingdee_sync_list]
