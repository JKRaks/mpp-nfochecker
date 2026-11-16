"""Atomic reports, bounded history and optional versioned sidecar backups."""

import copy
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

from .core import Target, fingerprint, within
from .errors import FileConflict, StorageError
from .state import ACTIVE_PHASES, SCHEMA_VERSION, adapt_report, item_status, normalize_pending


def atomic_bytes(path, data, mode=None):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=".nfocheck-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "runs").mkdir(exist_ok=True)
        (self.directory / "run_summaries").mkdir(exist_ok=True)
        self._report_lock = threading.RLock()
        self._summaries = {}
        # Only the currently viewed report is cached, independently of mutable worker data.
        self._view_cache = None
        self._active = {}
        self._checkpoints = {}

    def read(self, name, default=None):
        path = self.directory / (name + ".json")
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def backup_legacy(self, name):
        source = self.directory / (name + ".json")
        destination = self.directory / "migration-1.1.0" / (name + ".json")
        if source.exists() and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            atomic_bytes(destination, source.read_bytes())

    def read_state(self, name):
        value = self.read(name, {})
        if value.get("schema_version") == SCHEMA_VERSION and "entries" in value:
            entries = value["entries"]
        else:
            entries = {
                key: (
                    {**entry, "legacy": True}
                    if isinstance(entry, dict)
                    else {"signature": entry, "legacy": True}
                )
                for key, entry in value.items()
            }
        if name == "pending_sync":
            return {key: normalize_pending(entry) for key, entry in entries.items()}
        return entries

    def write_state(self, name, entries):
        self.write(name, {"schema_version": SCHEMA_VERSION, "entries": entries})

    def write(self, name, value):
        path = self.directory / (name + ".json")
        try:
            with self._report_lock:
                if name.startswith("runs/"):
                    self.validate_run_id(name[5:])
                if name.startswith("runs/") or name in {
                    "attempts",
                    "ignored",
                    "pending_sync",
                    "sync_receipts",
                }:
                    old = self.read(name)
                    if old is not None and old.get("schema_version", 1) < SCHEMA_VERSION:
                        self.backup_legacy(name)
                atomic_bytes(
                    path, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
                )
                if name.startswith("runs/"):
                    self._save_summary(path, value)
                    if self._view_cache and self._view_cache[0] == name[5:]:
                        self._view_cache = None
        except OSError as exc:
            raise StorageError("插件状态保存失败，任务已停止：" + str(path)) from exc

    @staticmethod
    def _summary(run):
        result = {
            k: copy.deepcopy(run[k])
            for k in (
                "id",
                "schema_version",
                "created",
                "updated",
                "status",
                "phase",
                "outcome",
                "exit_reason",
                "dry_run",
                "summary",
                "counts",
                "batches",
                "emby_enabled",
            )
            if k in run
        }
        result.update(item_count=len(run.get("items", [])), error_count=len(run.get("errors", [])))
        return result

    def checkpoint(self, run, index=None, force=False):
        """Publish only changed rows; persist full snapshots every 10 s or 200 changes."""
        with self._report_lock:
            run_id = run["id"]
            view = self._active.get(run_id)
            if view is None or index is None:
                view = copy.deepcopy(run)
                self._active[run_id] = view
            else:
                view.update({k: copy.deepcopy(v) for k, v in run.items() if k != "items"})
                if index == len(view["items"]):
                    view["items"].append(copy.deepcopy(run["items"][index]))
                else:
                    view["items"][index] = copy.deepcopy(run["items"][index])
            elapsed, changes = self._checkpoints.get(run_id, (0, 0))
            changes += 1
            if force or time.monotonic() - elapsed >= 10 or changes >= 200:
                self.write("runs/" + run_id, run)
                self._checkpoints[run_id] = (time.monotonic(), 0)
            else:
                self._checkpoints[run_id] = (elapsed, changes)

    def release(self, run_id):
        with self._report_lock:
            self._active.pop(run_id, None)
            self._checkpoints.pop(run_id, None)

    def recover_interrupted(self):
        """Only plugin JSON is updated on startup. Never resume media writes."""
        for row in self.reports():
            if row.get("phase") in ACTIVE_PHASES or row.get("status") in ACTIVE_PHASES:
                run = self.report(row["id"])
                journal = self.read_state("attempts")
                by_path = {}
                for key, entry in journal.items():
                    if (
                        entry.get("run_id") == run["id"]
                        and entry.get("result")
                        and entry.get("target")
                    ):
                        by_path.setdefault(entry["target"]["path"], []).append(
                            (key.rsplit(":", 1)[-1], entry)
                        )
                for item in run.get("items", []):
                    records = sorted(
                        by_path.get(item["target"]["path"], []),
                        key=lambda row: row[1]["result"].get("attempted_at", 0),
                    )
                    for asset, entry in records:
                        item.setdefault("results", {})[asset] = entry["result"]
                        item.update(entry.get("resume", {}))
                        item["target"] = entry["target"]
                        item["id"] = Target(**entry["target"]).key
                    item["needs_recheck"] = True
                    item["status"] = item_status(item)
                run.pop("counts", None)
                adapt_report(run, interrupted=True)
                run["updated"] = time.time()
                self.write("runs/" + run["id"], run)

    def pending_page(self, page=1, page_size=100):
        entries = self.read_state("pending_sync")
        rows = [
            {
                "key": key,
                "target_id": value.get("target_id"),
                "target": value.get("target"),
                "server": value.get("server", ""),
                "status": value.get("status", "needs_recheck"),
                "message": value.get("sync", {}).get("message")
                or value.get("message", "旧记录待重新确认" if value.get("legacy") else ""),
                "updated": value.get("updated", 0),
                "version": value.get("version"),
            }
            for key, value in entries.items()
        ]
        rows.sort(key=lambda row: row.get("updated", 0), reverse=True)
        page_size = max(1, min(page_size, 100))
        page = max(1, min(page, max(1, (len(rows) + page_size - 1) // page_size)))
        return {
            "items": rows[(page - 1) * page_size : page * page_size],
            "total": len(rows),
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    def validate_run_id(run_id):
        if not run_id or any(c not in "0123456789abcdef" for c in run_id) or len(run_id) != 32:
            raise ValueError("无效运行编号")

    def report(self, run_id):
        self.validate_run_id(run_id)
        with self._report_lock:
            result = (
                copy.deepcopy(self._active[run_id])
                if run_id in self._active
                else self.read("runs/" + run_id)
            )
        if result is None:
            raise ValueError("运行记录不存在")
        return adapt_report(result)

    @staticmethod
    def _signature(path):
        stat = path.stat()
        return [stat.st_mtime_ns, stat.st_size]

    def _save_summary(self, path, run):
        entry = {
            "schema_version": SCHEMA_VERSION,
            "signature": self._signature(path),
            "summary": self._summary(run),
        }
        self.write("run_summaries/" + path.stem, entry)
        self._summaries[path.stem] = entry
        return entry

    def reports(self):
        with self._report_lock:
            result = []
            for path in (self.directory / "runs").glob("*.json"):
                entry = self._summaries.get(path.stem) or self.read("run_summaries/" + path.stem)
                if (
                    not entry
                    or entry.get("schema_version") != SCHEMA_VERSION
                    or entry["signature"] != self._signature(path)
                ):
                    # One-time migration for old reports, and recovery after an interrupted save.
                    entry = self._save_summary(path, self.report(path.stem))
                self._summaries[path.stem] = entry
                result.append(
                    self._summary(self._active[path.stem])
                    if path.stem in self._active
                    else entry["summary"]
                )
            return sorted(result, key=lambda r: r.get("updated", r["created"]), reverse=True)

    def report_page(
        self,
        run_id,
        page=1,
        page_size=100,
        query="",
        status="",
        kind="",
        rule_set="",
        ids_only=False,
    ):
        self.validate_run_id(run_id)
        page_size = max(1, min(page_size, 100))
        with self._report_lock:
            path = self.directory / "runs" / (run_id + ".json")
            if not path.exists():
                raise ValueError("运行记录不存在")
            signature = self._signature(path)
            if run_id in self._active:
                run = self._active[run_id]
            elif not self._view_cache or self._view_cache[:2] != (run_id, signature):
                self._view_cache = (run_id, signature, self.report(run_id))
                run = self._view_cache[2]
            else:
                run = self._view_cache[2]
            needle = query.casefold()
            items = [
                i
                for i in run["items"]
                if (not needle or needle in i["target"]["path"].casefold())
                and (not status or i["status"] == status)
                and (not kind or i["target"]["kind"] == kind)
                and (not rule_set or any(h["set"] == rule_set for h in i["hits"]))
            ]
            if ids_only:
                return {"ids": [i["id"] for i in items]}
            total = len(items)
            page = max(1, min(page, max(1, (total + page_size - 1) // page_size)))
            result = {k: v for k, v in run.items() if k not in {"items", "errors"}}
            # Internal signatures, fingerprints and requirements are needed only by workers.
            fields = (
                "id",
                "target",
                "status",
                "hits",
                "remaining_hits",
                "remaining_assets",
                "conflicts",
                "actions",
                "results",
                "sync",
                "needs_recheck",
                "emby_mode",
            )
            result.update(
                items=[
                    {k: i[k] for k in fields if k in i}
                    for i in items[(page - 1) * page_size : page * page_size]
                ],
                page=page,
                page_size=page_size,
                total=total,
                item_count=len(run["items"]),
                statuses=sorted({i["status"] for i in run["items"]}),
                errors=run.get("errors", [])[:100],
                error_count=len(run.get("errors", [])),
            )
            return result

    def delete_reports(self, run_ids):
        for run_id in run_ids:
            self.validate_run_id(run_id)
        with self._report_lock:
            deleted = []
            for run_id in dict.fromkeys(run_ids):
                path = self.directory / "runs" / (run_id + ".json")
                if path.exists():
                    path.unlink()
                    deleted.append(run_id)
                (self.directory / "run_summaries" / (run_id + ".json")).unlink(missing_ok=True)
                self._summaries.pop(run_id, None)
                if self._view_cache and self._view_cache[0] == run_id:
                    self._view_cache = None
            return deleted

    def prune_runs(self, days):
        cutoff = time.time() - days * 86400
        with self._report_lock:
            self.delete_reports(
                [
                    path.stem
                    for path in (self.directory / "runs").glob("*.json")
                    if path.stat().st_mtime < cutoff
                ]
            )

    def commit(self, path, data, asset, config, run_id, expected, context=None):
        path = Path(path)
        if path.is_symlink():
            raise FileConflict("旁挂文件为符号链接，跳过写入")
        if fingerprint(path) != expected:
            raise FileConflict("文件已被其他任务修改，请重新巡检")
        if path.exists() and path.read_bytes() == data:
            return None, False
        backup = None
        enabled = config.nfo if asset == "nfo" else config.images
        if path.exists() and enabled:
            directory = Path(config.directory) if config.directory else self.directory / "backups"
            directory.mkdir(parents=True, exist_ok=True)
            backup_id = uuid.uuid4().hex
            backup_path = directory / (backup_id + path.suffix)
            shutil.copy2(path, backup_path)
            backup = {
                "id": backup_id,
                "path": str(path),
                "backup": str(backup_path),
                "asset": asset,
                "run_id": run_id,
                "created": time.time(),
                "after": hashlib.sha256(data).hexdigest(),
                "committed": False,
                "context": context or {},
            }
            index = self.read("backups", [])
            index.append(backup)
            self.write("backups", index)
        if fingerprint(path) != expected:
            raise FileConflict("备份期间文件发生变化，请重新巡检")
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        atomic_bytes(path, data, mode)
        if backup:
            index = self.read("backups", [])
            next(b for b in index if b["id"] == backup["id"])["committed"] = True
            self.write("backups", index)
        return backup["id"] if backup else None, True

    def prune_backups(self, config):
        if not config.cleanup:
            return
        index, keep, counts = self.read("backups", []), [], {}
        for entry in sorted(index, key=lambda e: e["created"], reverse=True):
            count = counts.get(entry["path"], 0) + 1
            counts[entry["path"]] = count
            expired = config.days > 0 and time.time() - entry["created"] > config.days * 86400
            excess = config.versions > 0 and count > config.versions
            if expired or excess:
                Path(entry["backup"]).unlink(missing_ok=True)
            else:
                keep.append(entry)
        self.write("backups", keep)

    def restore(self, backup_id, config, run_id):
        entry = next(
            (b for b in self.read("backups", []) if b["id"] == backup_id and b.get("committed")),
            None,
        )
        if not entry:
            raise ValueError("备份不存在或未完成提交")
        path = Path(entry["path"])
        roots = [p for s in config.rule_sets if s.enabled for p in s.roots]
        if not any(within(path, root) for root in roots):
            raise ValueError("原文件已不在启用的巡检范围内")
        current = path.read_bytes() if path.exists() else b""
        if hashlib.sha256(current).hexdigest() != entry["after"]:
            raise FileConflict("文件在备份后又被修改，不能直接恢复；请手动比较备份")
        self.commit(
            path,
            Path(entry["backup"]).read_bytes(),
            entry["asset"],
            config.backup,
            run_id,
            fingerprint(path),
            entry["context"],
        )
        return entry
