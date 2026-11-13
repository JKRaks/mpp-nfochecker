"""Shared report/asset states, legacy projections and incremental accounting."""
from collections import Counter
from typing import TypedDict

SCHEMA_VERSION = 2
ACTIVE_PHASES = {"discovering", "scanning", "repairing", "syncing"}
SYNC_DONE = {"complete", "verified"}


class AssetResult(TypedDict, total=False):
    status: str
    message: str
    error_code: str
    details: dict
    path: str
    version: str
    next_retry_at: float
    attempts: int


def sync_for_server(value, server=None):
    """Project legacy multi-server receipts to the single-server queue format."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list) and server is not None:
        return next((dict(receipt) for receipt in value
                     if isinstance(receipt, dict) and receipt.get("server") == server), {})
    return {}


def normalize_pending(entry):
    result = dict(entry)
    value = entry.get("sync")
    if isinstance(value, list):
        # Keep every original receipt until the target and its servers can be recovered.
        result.setdefault("legacy_sync", value)
    result["sync"] = sync_for_server(value, entry.get("server"))
    if entry.get("legacy") and not entry.get("target"):
        result.setdefault("status", "needs_recheck")
        result.setdefault("message", "旧待同步记录的目标尚未确认；记录已保留")
    return result


def remaining_assets(item):
    if "remaining_assets" in item:
        return item["remaining_assets"]
    if "remaining_hits" in item:
        return sorted({a for h in item["remaining_hits"] for a in h.get("actions", [])})
    return [a for a in item.get("actions", [])
            if item.get("results", {}).get(a, {}).get("status") not in {"repaired", "unchanged"}]


def item_status(item):
    if item.get("status") == "excluded":
        return "excluded"
    if item.get("ignored") or item.get("status") == "ignored":
        return "ignored"
    if item.get("conflicts") or item.get("needs_recheck"):
        return "manual"
    if item.get("stable") is False or "stable" not in item and item.get("status") == "unstable":
        return "unstable"
    remaining = remaining_assets(item)
    if remaining:
        states = [item.get("results", {}).get(a, {}).get("status", "pending") for a in remaining]
        if all(s == "manual" for s in states):
            return "manual"
        if all(s in {"manual", "cooldown"} for s in states):
            return "cooldown"
        if any(s in {"failed", "unimproved"} for s in states) or any(item.get("results", {}).get(a, {}).get("translation_pending_fields") for a in remaining):
            return "partial"
        return "pending"
    if any(s.get("status") not in SYNC_DONE for s in item.get("sync", [])):
        return "sync_pending"
    if item.get("remaining_hits", item.get("hits", [])):
        return "report"
    return "repaired" if any(r.get("status") == "repaired" for r in item.get("results", {}).values()) else "complete"


def contribution(item):
    remaining = remaining_assets(item)
    status = item.get("status", "pending")
    return Counter({"items": 1, "matched": int(bool(item.get("hits") or item.get("conflicts"))),
                    "pending": int(status == "pending"), "partial": int(status == "partial"),
                    "cooldown": int(status == "cooldown"), "manual": int(status == "manual"),
                    "unstable": int(status == "unstable"), "failed": int(status == "failed"),
                    "ignored": int(status == "ignored"), "excluded": int(status == "excluded"),
                    "resolved": int(status in {"complete", "repaired", "report"} and not remaining),
                    "remaining_assets": 0 if status in {"ignored", "excluded"} else len(remaining),
                    "attempted": int(bool(item.get("attempted") or any(r.get("attempted_at") for r in item.get("results", {}).values()))),
                    "repaired_assets": sum(r.get("status") == "repaired" for r in item.get("results", {}).values()),
                    "failed_assets": sum(item.get("results", {}).get(a, {}).get("status") in {"failed", "unimproved"} for a in remaining),
                    "sync_pending": sum(s.get("status") not in SYNC_DONE for s in item.get("sync", [])),
                    "sync_verified": sum(s.get("status") == "verified" for s in item.get("sync", []))})


def summary(report):
    c = report.get("counts", {})
    return (f"检查 {c.get('items', 0)} 项，命中 {c.get('matched', 0)} 项；"
            f"待处理 {c.get('pending', 0)}，部分完成 {c.get('partial', 0)}，冷却 {c.get('cooldown', 0)}，"
            f"待人工 {c.get('manual', 0)}，等待稳定 {c.get('unstable', 0)}；"
            f"修复资产 {c.get('repaired_assets', 0)}，剩余资产 {c.get('remaining_assets', 0)}；"
            f"Emby 已验证 {c.get('sync_verified', 0)}，待处理 {c.get('sync_pending', 0)}；"
            f"运行错误 {len(report.get('errors', []))}。")


def finish(report, reason="completed"):
    report["phase"] = "done"
    report["exit_reason"] = reason
    c = report.get("counts", {})
    unresolved = any(c.get(k, 0) for k in ("remaining_assets", "manual", "unstable", "failed", "sync_pending")) or bool(report.get("errors"))
    if reason in {"stop", "interrupted", "error"}:
        status = {"stop": "cancelled", "interrupted": "interrupted", "error": "failed"}[reason]
    elif reason == "inspected":
        status = "inspected"
    elif reason == "batch_limit" and unresolved:
        status = "batch_limited"
    else:
        status = "partial" if unresolved else "finished"
    report["status"] = status
    report["outcome"] = "partial" if status == "batch_limited" else "complete" if status == "finished" else status
    report["summary"] = summary(report)


def adapt_report(report, interrupted=False):
    legacy = report.get("schema_version", 1) < SCHEMA_VERSION
    if legacy:
        report["legacy_status"] = report.get("status")
        for item in report.get("items", []):
            item["remaining_assets"] = remaining_assets(item)
            item["status"] = item_status(item)
    if legacy or "counts" not in report:
        counts = Counter()
        for item in report.get("items", []):
            counts.update(contribution(item))
        report["counts"] = dict(counts)
    report["schema_version"] = SCHEMA_VERSION
    if interrupted and (report.get("phase") in ACTIVE_PHASES or report.get("status") in ACTIVE_PHASES):
        finish(report, "interrupted")
    elif legacy and report.get("legacy_status") in ACTIVE_PHASES:
        report.update(status=report["legacy_status"], phase=report["legacy_status"], outcome="running", exit_reason="")
        report["summary"] = summary(report)
    elif legacy:
        old = report.get("legacy_status")
        finish(report, "inspected" if report.get("dry_run") or old == "inspected" else
               "stop" if old == "cancelled" else "error" if old == "failed" else "completed")
    return report
