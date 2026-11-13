"""Serialized, resumable inspection and repair; durable asset and Emby queues."""
import copy
import hashlib
import io
import logging
import threading
import time
import traceback
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from PIL import Image
from .config import Config
from .core import (Inspector, ROOT_TAGS, Target, applicable, digest, fingerprint, identities,
                   image_info, iter_discover, parse_nfo, reclassify, within)
from .errors import (CandidateRejected, FileConflict, SourceUnavailable, StorageError,
                     TaskStopped, failure, safe_message)
from .state import SCHEMA_VERSION, SYNC_DONE, contribution, finish, item_status, summary, sync_for_server
from .store import Store
from .translation import TranslationBridge

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, config, directory, source, emby_factory=None, notify=None):
        self.config = Config.model_validate(config)
        self.store = Store(directory)
        self.source = source
        self.emby_factory = emby_factory
        self.notify = notify
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = None
        self.live = {"busy": False, "run_id": None, "error": ""}
        self._accounting = {}
        self.translation = TranslationBridge(self.source, self.store, self.stop)
        self.store.recover_interrupted()

    def _begin(self, params):
        self.stop.clear()  # Clear exactly once, before a worker can receive a stop request.
        self.live = {"busy": True, "run_id": params.get("run_id"), "error": ""}
        self._accounting = {}
        self.translation.overwrite = bool(params.get("translation_overwrite"))
        self.translation.force = bool(params.get("translation_force"))
        self.translation.retry = bool(params.get("retry"))
        if hasattr(self.source, "begin_run"):
            self.source.begin_run()

    def reserve(self, params):
        if not self.lock.acquire(False):
            raise ValueError("已有任务正在运行")
        try:
            self._begin(params)
        except Exception:
            self.lock.release()
            raise

    def execute(self, operation, **params):
        self.reserve(params)
        return self._execute_locked(operation, params)

    def start(self, operation, **params):
        self.reserve(params)
        def work():
            try:
                self._execute_locked(operation, params)
            except Exception:
                pass  # _execute_locked persists and logs the diagnostic.
        self.thread = threading.Thread(target=work, name="NfoCheck", daemon=True)
        try:
            self.thread.start()
        except Exception:
            self.live["busy"] = False
            self.lock.release()
            raise
        return dict(self.live)

    def _execute_locked(self, operation, params):
        try:
            if operation in {"repair", "resume", "refresh", "refresh_pending", "restore"} or (operation == "run" and not params.get("dry_run", True)):
                if not self.config.enabled:
                    raise ValueError("请先启用插件，再执行修复或刷新")
            if operation in {"inspect", "run"}:
                report = self.inspect(params.get("files"), params.get("set_ids"), params.get("dry_run", True))
                if operation == "run" and not report["dry_run"] and not self.stop.is_set():
                    report = self.repair(report["id"], params.get("ids"), params.get("retry", False))
                    if not self.stop.is_set():
                        report = self.refresh(report["id"])
            elif operation in {"repair", "resume"}:
                if operation == "resume" and self.store.report(params["run_id"])["dry_run"]:
                    raise ValueError("试运行记录不能继续执行；请先执行修复或正式运行")
                report = self.repair(params["run_id"], params.get("ids"), params.get("retry", False), operation == "resume")
                if operation == "resume" and not self.stop.is_set():
                    report = self.refresh(report["id"])
            elif operation == "refresh":
                report = self.refresh(params["run_id"])
            elif operation == "refresh_pending":
                report = self.refresh_pending()
            elif operation == "restore":
                report = self.restore(params["backup_id"], params.get("sync", False))
            elif operation == "ignore":
                report = self.ignore(params["run_id"], params.get("ids") or [], params.get("undo", False))
            else:
                raise ValueError("未知操作")
            if self.notify and params.get("notify", False) and operation != "ignore":
                self.notify(summary(report), report)
            return report
        except TaskStopped:
            report = self.store.report(self.live["run_id"])
            finish(report, "stop")
            self.save(report, force=True)
            return report
        except Exception as exc:
            self.live["error"] = safe_message(exc)
            log.error("NfoCheck task failed: %s", safe_message(traceback.format_exc()))
            if self.live.get("run_id") in self._accounting:
                try:
                    report = self.store.report(self.live["run_id"])
                    report["errors"].append(safe_message(exc))
                    finish(report, "error")
                    self.save(report, force=True)
                except (OSError, ValueError, StorageError):
                    # Live status still exposes a storage failure when even the final snapshot cannot be written.
                    pass
            raise
        finally:
            self.translation.close()
            self.live["busy"] = False
            if self.live.get("run_id"):
                self.store.release(self.live["run_id"])
            self.lock.release()

    def scoped(self, set_ids):
        config = self.config.model_copy(deep=True)
        if set_ids is not None:
            config.rule_sets = [s for s in config.rule_sets if s.id in set(set_ids)]
        return config

    def new_report(self, config, dry_run=False, operation="inspect"):
        report = {"id": uuid.uuid4().hex, "schema_version": SCHEMA_VERSION, "created": time.time(),
                  "status": "scanning", "phase": "scanning", "outcome": "running", "exit_reason": "",
                  "dry_run": dry_run, "set_ids": [s.id for s in config.rule_sets], "items": [], "errors": [],
                  "operation": operation, "batches": 0, "emby_enabled": any(s.enabled and s.emby != "off" for s in config.rule_sets)}
        self.live["run_id"] = report["id"]
        self.save(report, force=True)
        return report

    def save(self, report, index=None, force=False):
        run_id = report["id"]
        accounting = self._accounting.get(run_id)
        if accounting is None or index is None:
            rows = [contribution(item) for item in report["items"]]
            counts = Counter()
            for row in rows:
                counts.update(row)
            self._accounting[run_id] = (counts, rows)
        else:
            counts, rows = accounting
            value = contribution(report["items"][index])
            if index < len(rows):
                counts.subtract(rows[index])
                rows[index] = value
            else:
                rows.append(value)
            counts.update(value)
        report["counts"] = dict(counts)
        report["updated"] = time.time()
        report["summary"] = summary(report)
        self.store.checkpoint(report, index, force)

    summary = staticmethod(summary)

    def done(self, report, reason="completed"):
        self.save(report)
        finish(report, "stop" if self.stop.is_set() else reason)
        self.save(report, force=True)
        return report

    def ignored(self, item, entries):
        entry = entries.get(item["id"], {})
        if not entry:
            return
        if entry.get("signature") == item["ignore_signature"] or entry.get("legacy") and entry.get("signature") == item["legacy_signature"]:
            if entry.get("legacy"):
                entries[item["id"]] = {"signature": item["ignore_signature"]}
                self.store.write_state("ignored", entries)
            item["ignored"] = True
            item["status"] = "ignored"
        elif entry.get("legacy"):
            item["needs_recheck"] = True
            item["conflicts"].append("旧忽略状态无法可靠匹配，请取消忽略后重新判断")
            item["status"] = "manual"

    def inspect(self, files, set_ids, dry_run):
        config = self.scoped(set_ids)
        if set_ids is not None and set(set_ids) - {s.id for s in self.config.rule_sets}:
            raise ValueError("选定规则集不存在，请重新选择")
        if not any(s.enabled and s.roots for s in config.rule_sets):
            raise ValueError("请配置至少一个启用的规则集和检查目录")
        report = self.new_report(config, dry_run)
        inspector = Inspector(config, self.store.read("cache", {}), self.translation)
        ignored = self.store.read_state("ignored")
        pending = self.store.read_state("pending_sync")
        emby = self.emby_factory(config) if report["emby_enabled"] and config.emby_servers and self.emby_factory else None
        if emby:
            emby.stop = self.stop
        try:
            for target in iter_discover(config, files, self.source.parse, self.stop, report["errors"]):
                try:
                    item = inspector.inspect(target)
                    if not item:
                        continue
                    self.ignored(item, ignored)
                    if emby and item["emby_mode"] == "compare" and item["status"] not in {"manual", "unstable", "ignored"}:
                        item["sync"] = emby.compare(item, inspector)
                    existing = [v for v in pending.values() if v.get("target_id") == item["id"]]
                    if existing:
                        item["sync"] = [v.get("sync") or {"server": v.get("server", ""), "status": v.get("status", "pending"), "message": v.get("message", "")} for v in existing]
                    item["status"] = item_status(item)
                    report["items"].append(item)
                    self.save(report, len(report["items"]) - 1)
                except (OSError, ValueError) as exc:
                    report["errors"].append(f"{target.path}：{safe_message(exc)}")
        except TaskStopped:
            pass
        self.store.write("cache", inspector.cache)
        self.store.prune_runs(config.history_days)
        return self.done(report, "inspected")

    def validate_candidate(self, target, asset, data, item, inspector):
        if asset == "nfo":
            try:
                xml = parse_nfo(data)
            except (ValueError, ET.ParseError) as exc:
                raise CandidateRejected("候选 XML 无效", {"parse_error": safe_message(exc)}) from exc
            if xml.tag != ROOT_TAGS[target.kind]:
                raise CandidateRejected("候选 NFO 根元素不正确", {"expected_root": ROOT_TAGS[target.kind], "actual_root": xml.tag})
            conflicts = inspector.conflict(target, xml)
            if conflicts:
                raise CandidateRejected("候选 NFO 身份或季集编号冲突", {"conflicts": conflicts})
            old, _ = inspector.xml(target.nfo())
            old_ids, new_ids = identities(old), identities(xml)
            if any(k in new_ids and v != new_ids[k] for k, v in old_ids.items()):
                raise CandidateRejected("候选 NFO 媒体身份发生变化", {"expected_ids": old_ids, "actual_ids": new_ids})
            if (item.get("translation") or {}).get("mode") == "patch":
                return  # Partial text edits do not claim to repair unrelated NFO fields.
            rejected = []
            for ruleset in inspector.config.rule_sets:
                if applicable(target, ruleset):
                    for rule in ruleset.rules:
                        if rule.enabled and rule.category == "nfo" and rule.action in {"nfo", "both", "nfo_translate"}:
                            hit, reasons = inspector.nfo_matches(target, rule, xml, "", candidate=True)
                            if hit:
                                rejected.append({"set": ruleset.id, "rule": rule.id, "reasons": reasons,
                                                 "fields": [c.field for c in rule.conditions if c.op in {"empty", "min_length", "regex"}]})
            if rejected:
                raise CandidateRejected("候选 NFO 仍不满足修复规则", {"rules": rejected})
        else:
            try:
                info = image_info(data)
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                raise CandidateRejected("候选图片无法解码", {"decode_error": safe_message(exc)}) from exc
            checks = [check.model_dump() for ruleset in inspector.config.rule_sets if applicable(target, ruleset)
                      for rule in ruleset.rules if rule.enabled and rule.category == "image" and
                      (rule.action in {"matched_images", "both"} or rule.action == "selected_images" and asset in rule.selected_images)
                      for check in rule.images if check.type == asset]
            for check in checks:
                if info["width"] < check["min_width"] or info["height"] < check["min_height"]:
                    raise CandidateRejected("候选图片尺寸仍不合格", {"actual_width": info["width"], "actual_height": info["height"],
                                            "min_width": check["min_width"], "min_height": check["min_height"]})

    @staticmethod
    def encode_image(path, data):
        formats = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".bmp": "BMP", ".tbn": "JPEG"}
        expected = formats.get(path.suffix.lower())
        with Image.open(io.BytesIO(data)) as img:
            if not expected or img.format == expected:
                return data
            output = io.BytesIO()
            if expected == "JPEG":
                img = img.convert("RGB")
            img.save(output, format=expected)
            return output.getvalue()

    def candidates(self, target, asset):
        if hasattr(self.source, "iter_candidates"):
            yield from self.source.iter_candidates(target, asset, self.stop)
        else:
            yield from self.source.candidates(target, [asset]).get(asset, [])

    def repair_asset(self, target, asset, item, inspector, config, report):
        if asset == "nfo" and item.get("translation"):
            return self.repair_translation(target, item, inspector, config, report)
        errors = []
        for candidate in self.candidates(target, asset):
            if self.stop.is_set():
                raise TaskStopped()
            try:
                if isinstance(candidate, Exception):
                    raise candidate
                path, data = candidate
                path = Path(path)
                if asset == "nfo" and path.resolve() != target.nfo().resolve():
                    raise FileConflict("NFO 目标路径不一致")
                if asset != "nfo" and not (path.parent.resolve() == target.directory().resolve() or
                         target.kind == "season" and path.parent.resolve() == Path(target.series).resolve()):
                    raise FileConflict("图片路径超出当前媒体目录")
                if not within(path, target.root):
                    raise FileConflict("目标路径超出巡检根目录")
                self.validate_candidate(target, asset, data, item, inspector)
                if asset != "nfo":
                    data = self.encode_image(path, data)
                if self.stop.is_set():
                    raise TaskStopped()
                backup, changed = self.store.commit(path, data, asset, config.backup, report["id"], item["files"].get(str(path)),
                                                    {"target": item["target"], "set_ids": report["set_ids"]})
                inspector.invalidate(path)
                actual = path.read_bytes()
                if actual != data:
                    raise FileConflict("落盘后内容被其他任务修改，请重新巡检")
                self.validate_candidate(target, asset, actual, item, inspector)
                return {"status": "repaired" if changed else "unchanged", "path": str(path), "backup_id": backup,
                        "version": hashlib.sha256(data).hexdigest(), "file_signature": fingerprint(path)}
            except (StorageError, TaskStopped):
                raise
            except FileConflict:
                raise  # A conflicting destination is not a reason to write a different alias.
            except Exception as exc:
                errors.append(exc)
        if not errors:
            raise SourceUnavailable("来源没有可用内容")
        # Transient/IO/internal failures do not consume the no-improvement budget.
        error = next((e for e in errors if not isinstance(e, (CandidateRejected, SourceUnavailable))), errors[-1])
        raise error

    def repair_translation(self, target, item, inspector, config, report):
        plan = item["translation"]
        if item.get("translation_conflict"):
            return {"status": "manual", "error_code": "translation_conflict", "message": item["translation_conflict"], "translation_pending_fields": plan["fields"]}
        try:
            output = self.translation.prepare(target, plan, item)
        except (StorageError, TaskStopped): raise
        except Exception as exc:
            if getattr(exc, "code", "") == "cancelled": raise TaskStopped() from None
            detail = exc.result() if hasattr(exc, "result") else {"status": "failed", "error_code": "translation_unavailable", "message": safe_message(exc)}
            if detail.get("error_code") in {"identity_unknown", "unsupported_source", "policy_missing", "unsupported_field"}:
                detail["status"] = "manual"
            return {**detail, "field_retry_at": detail.get("next_retry_at", 0), "translation_pending_fields": plan["fields"],
                    "details": {"fields": {field: copy.deepcopy(detail) for field in plan["fields"]}}}
        data = output["nfo"].encode("utf-8")
        path = target.nfo()
        self.validate_candidate(target, "nfo", data, item, inspector)
        if not within(path, target.root): raise FileConflict("NFO 目标超出检查目录")
        if self.stop.is_set(): raise TaskStopped()
        version = hashlib.sha256(data).hexdigest()
        self.translation.intent(target, output, version)
        backup, changed = self.store.commit(path, data, "nfo", config.backup, report["id"], item["files"].get(str(path)),
                                            {"target": item["target"], "set_ids": report["set_ids"]})
        inspector.invalidate(path)
        if path.read_bytes() != data: raise FileConflict("翻译提交后文件发生变化")
        self.translation.committed(target, output, version)
        pending = output["pending_fields"]
        values = [output["fields"][f] for f in pending]
        next_at = min((v.get("next_retry_at", 0) for v in values), default=0)
        status = "repaired" if changed else "unchanged"
        if pending and not changed:
            status = "manual" if all(v["status"] in {"protected", "language_unknown"} for v in values) else "cooldown" if next_at else "failed"
        return {"status": status, "path": str(path), "backup_id": backup, "version": version, "file_signature": fingerprint(path),
                "translation_pending_fields": pending, "translation_generated": output["generated"], "translation_plan_signature": digest(plan),
                "translation_revision": output["revision"],
                "changed_fields": output["changed_fields"] if plan["mode"] == "patch" or not output["generated"] else None,
                "field_retry_at": next_at, "error_code": "translation_pending" if pending else "",
                "message": f"{len(output['changed_fields'])} 个文字字段变化；{len(pending)} 个字段待处理",
                "details": {"fields": output["fields"], "record_id": output["record_id"], "local_only_fields": ["outline"] if "outline" in output["changed_fields"] else []}}

    def current_item(self, previous, inspector):
        target = reclassify(Target(**previous["target"]), self.source.parse)
        current = inspector.inspect(target) if target is not None else None
        if current is None:
            return {**previous, "status": "excluded", "remaining_assets": [], "remaining_hits": [], "sync": [],
                    "results": previous.get("results", {})}
        current["hits"] = previous.get("hits", current["hits"])
        current["actions"] = sorted(set(previous.get("actions", [])) | set(current["actions"]))
        current["results"] = copy.deepcopy(previous.get("results", {}))
        current["sync"] = copy.deepcopy(previous.get("sync", []))
        same_nfo_rules = bool(current["asset_signatures"].get("nfo")) and current["asset_signatures"].get("nfo") == previous.get("asset_signatures", {}).get("nfo")
        if self.translation.force and same_nfo_rules and previous.get("translation") and not current.get("translation"):
            current["translation"] = previous["translation"]
            current["remaining_assets"] = sorted(set(current["remaining_assets"]) | {"nfo"})
        prior_nfo = previous.get("results", {}).get("nfo", {})
        if prior_nfo.get("translation_pending_fields") and same_nfo_rules and previous.get("translation") and not current.get("translation"):
            current["translation"] = previous["translation"]
            current["remaining_assets"] = sorted(set(current["remaining_assets"]) | {"nfo"})
        current["completed_assets"] = []
        for asset in previous.get("remaining_assets", []):
            if asset in current["asset_signatures"] and previous.get("asset_signatures", {}).get(asset) == current["asset_signatures"][asset]:
                current["remaining_assets"] = sorted(set(current["remaining_assets"]) | {asset})
        for asset, result in current["results"].items():
            if (not result.get("translation_pending_fields") and not (asset == "nfo" and self.translation.force) and result.get("status") in {"repaired", "unchanged"} and result.get("completed_signature") == current["asset_signatures"].get(asset)
                    and result.get("path") and fingerprint(result["path"]) == result.get("file_signature")):
                current["remaining_assets"] = [a for a in current["remaining_assets"] if a != asset]
                current["completed_assets"].append(asset)
        owned = {r.get("path") for r in current["results"].values() if r.get("status") in {"repaired", "unchanged"}
                 and r.get("path") and fingerprint(r["path"]) == r.get("file_signature")}
        current["stable"] = all(sig is None or path in owned or time.time() - sig[0] / 1e9 >= inspector.config.stable_seconds
                                for path, sig in current["files"].items())
        current["status"] = "pending"
        current["status"] = item_status(current)
        return current

    def repair(self, run_id, ids=None, retry=False, resume=False):
        report = self.store.report(run_id)
        self.live["run_id"] = run_id
        config = self.scoped(report["set_ids"])
        inspector = Inspector(config, self.store.read("cache", {}), self.translation)
        attempts, ignored = self.store.read_state("attempts"), self.store.read_state("ignored")
        report.update(status="repairing", phase="repairing", outcome="running", dry_run=False, exit_reason="", batches=0)
        self.save(report, force=True)
        selected = set(ids) if ids is not None else None
        indexes = [i for i, item in enumerate(report["items"]) if selected is None or item["id"] in selected]
        indexes.sort(key=lambda i: bool(report["items"][i].get("attempted") or any(
            r.get("attempted_at") for r in report["items"][i].get("results", {}).values())))
        max_batches = 1 if resume or not config.auto_continue else config.max_batches_per_run
        count, limited = 0, False
        for index in indexes:
            if self.stop.is_set():
                break
            previous = report["items"][index]
            try:
                current = self.current_item(previous, inspector)
                report["items"][index] = current
                if current["status"] == "excluded":
                    self.save(report, index)
                    continue
                self.ignored(current, ignored)
                if current["status"] in {"unstable", "ignored"} or current.get("conflicts") or current.get("needs_recheck") or not current["remaining_assets"]:
                    self.save(report, index)
                    continue
                eligible, priors = [], {}
                for asset in current["remaining_assets"]:
                    entry = copy.deepcopy(attempts.get(current["id"] + ":" + asset, attempts.get(previous["id"] + ":" + asset, {})))
                    signature = current["asset_signatures"].get(asset)
                    field_retry_at = entry.get("result", {}).get("field_retry_at", 0)
                    if not retry and not self.translation.force and field_retry_at > time.time() and entry.get("signature") == signature:
                        current["results"][asset] = {**entry["result"], "status": "cooldown", "message": "等待翻译服务或来源复查"}
                        continue
                    if retry:
                        entry = {}
                    elif entry.get("legacy"):
                        if entry.get("signature") == current["legacy_signature"]:
                            entry.update(signature=signature, legacy=False)
                            attempts[current["id"] + ":" + asset] = entry
                            self.store.write_state("attempts", attempts)
                        else:
                            current["results"][asset] = {"status": "manual", "error_code": "needs_recheck",
                                "message": "旧重试状态无法可靠匹配；可使用清除冷却并重试", "attempts": entry.get("count", 0), "next_retry_at": entry.get("next", 0)}
                            continue
                    elif entry.get("signature") != signature:
                        entry = {}
                    if entry.get("result", {}).get("translation_pending_fields"):
                        current["results"][asset] = copy.deepcopy(entry["result"])
                    priors[asset] = entry
                    if entry.get("count", 0) >= config.max_no_improvement:
                        current["results"][asset] = {"status": "manual", "message": "连续未改善达到上限", "attempts": entry["count"], "next_retry_at": entry.get("next", 0)}
                    elif time.time() < entry.get("next", 0):
                        current["results"][asset] = {"status": "cooldown", "message": "等待来源更新", "attempts": entry.get("count", 0), "next_retry_at": entry["next"]}
                    else:
                        eligible.append(asset)
                if retry:
                    for asset in current["remaining_assets"]:
                        attempts.pop(current["id"] + ":" + asset, None)
                        attempts.pop(previous["id"] + ":" + asset, None)
                    self.store.write_state("attempts", attempts)
                if not eligible:
                    current["status"] = item_status(current)
                    self.save(report, index)
                    continue
                if count >= config.batch_limit * max_batches:
                    limited = True
                    self.save(report, index)
                    break
                count += 1
                report["batches"] = (count - 1) // config.batch_limit + 1
                current["attempted"] = True
                target = Target(**current["target"])
                for asset in eligible:
                    if self.stop.is_set():
                        break
                    prior = priors[asset]
                    try:
                        result = self.repair_asset(target, asset, current, inspector, config, report)
                    except TaskStopped:
                        break
                    except StorageError:
                        raise
                    except Exception as exc:
                        result = failure(exc)
                        if result["error_code"] == "internal":
                            log.error("NfoCheck asset failed: %s", safe_message(traceback.format_exc()))
                    result["attempted_at"] = time.time()
                    current["results"][asset] = result
                    # Re-read after every asset; stopping between assets cannot mark the item complete.
                    verified = inspector.inspect(target)
                    if verified:
                        for key in ("signature", "ignore_signature", "asset_signatures", "files", "local", "requirements"):
                            current[key] = verified[key]
                        current["remaining_hits"] = verified["hits"]
                        current["remaining_assets"] = sorted(set(current["remaining_assets"]) | set(verified["actions"]))
                        if result["status"] in {"repaired", "unchanged"} and not result.get("translation_pending_fields"):
                            current["completed_assets"] = sorted(set(current.get("completed_assets", [])) | {asset})
                        for completed, value in current["results"].items():
                            if not value.get("translation_pending_fields") and completed in current.get("completed_assets", []) and value.get("status") in {"repaired", "unchanged"} and value.get("path") and fingerprint(value["path"]) == value.get("file_signature"):
                                value["completed_signature"] = current["asset_signatures"].get(completed)
                                current["remaining_assets"] = [a for a in current["remaining_assets"] if a != completed]
                    no_improvement = result.get("error_code") in {"candidate_rejected", "source_empty"}
                    failures = prior.get("count", 0) + 1 if no_improvement else 0 if result["status"] in {"repaired", "unchanged"} else prior.get("count", 0)
                    next_at = time.time() + config.cooldown_days * 86400 if no_improvement else prior.get("next", 0)
                    result.update(attempts=failures, next_retry_at=result.get("field_retry_at") or next_at)
                    attempts[current["id"] + ":" + asset] = {"signature": current["asset_signatures"].get(asset), "count": failures,
                        "next": next_at, "result": copy.deepcopy(result), "target": current["target"], "run_id": run_id,
                        "resume": {key: copy.deepcopy(current.get(key)) for key in ("remaining_assets", "asset_signatures", "completed_assets", "translation", "translation_conflict")}}
                    self.store.write_state("attempts", attempts)
                    if result["status"] == "repaired":
                        self.queue_sync(current, report, config)
                    current["stable"] = True  # Only our confirmed commits bypass the current round's stability delay.
                    current["status"] = item_status(current)
                    self.save(report, index)
                if count % config.batch_limit == 0:
                    self.save(report, force=True)
                if self.stop.wait(config.interval):
                    break
            except StorageError:
                raise
            except (OSError, ValueError) as exc:
                report["items"][index]["status"] = "failed"
                report["errors"].append(f"{previous['target']['path']}：{safe_message(exc)}")
                self.save(report, index)
        self.store.write("cache", inspector.cache)
        self.store.prune_backups(config.backup)
        return self.done(report, "batch_limit" if limited else "completed")

    def queue_sync(self, item, report, config, force=False):
        if item["emby_mode"] == "off" and not force:
            return
        results = {a: copy.deepcopy(v) for a, v in item["results"].items() if v.get("status") == "repaired" and v.get("version")}
        if not results and item["emby_mode"] != "compare":
            return
        pending = self.store.read_state("pending_sync")
        receipts = self.store.read_state("sync_receipts")
        servers = [s.name for s in config.emby_servers] or [""]
        for server in servers:
            key = item["id"] + ":" + server
            old = pending.get(key, {})
            receipt = receipts.get(key, {})
            merged = {**old.get("results", {}), **results}
            if "nfo" in results and results["nfo"].get("changed_fields") is not None:
                new_fields = set(results["nfo"]["changed_fields"])
                old_nfo = old.get("results", {}).get("nfo")
                merged["nfo"] = copy.deepcopy(results["nfo"])
                if old_nfo and old_nfo.get("changed_fields") is None:
                    merged["nfo"]["changed_fields"] = None
                else:
                    new_fields.update((old_nfo or {}).get("changed_fields") or [])
                    merged["nfo"]["changed_fields"] = sorted(new_fields)
                    if not new_fields & {"title", "plot", "tagline"}: merged.pop("nfo", None)
            merged = {a: v for a, v in merged.items() if receipt.get("versions", {}).get(a) != v.get("version")}
            if not merged and item["emby_mode"] != "compare":
                if receipt.get("sync"):
                    item["sync"] = [s for s in item["sync"] if s.get("server") != server] + [receipt["sync"]]
                pending.pop(key, None)
                continue
            version = digest({a: v.get("version") for a, v in merged.items()}) if merged else item["signature"]
            if receipt.get("version") == version and not any(s.get("server") == server and s.get("status") not in SYNC_DONE for s in item.get("sync", [])):
                item["sync"] = [s for s in item["sync"] if s.get("server") != server] + [receipt["sync"]]
                pending.pop(key, None)
                continue
            if old.get("version") == version:
                item["sync"] = [s for s in item["sync"] if s.get("server") != server] + [old["sync"]]
                continue
            sync = {"server": server, "status": "pending" if server else "paused", "signature": version,
                    "message": "" if server else "尚未配置 Emby 服务"}
            entry = {"target_id": item["id"], "target": item["target"], "server": server, "set_ids": report["set_ids"],
                     "version": version, "results": merged, "sync": sync, "status": sync["status"], "updated": time.time(),
                     "local": item["local"], "requirements": item["requirements"], "mode": item["emby_mode"],
                     "run_id": report["id"], "force": force or old.get("force", False)}
            pending[key] = entry
            item["sync"] = [s for s in item["sync"] if s.get("server") != server] + [sync]
        item["status"] = item_status(item)
        self.store.write_state("pending_sync", pending)

    def migrate_pending(self):
        pending = self.store.read_state("pending_sync")
        legacy = [(key, entry) for key, entry in pending.items() if entry.get("legacy")]
        if not legacy:
            return pending
        contexts = {}
        for row in self.store.reports():
            run = self.store.report(row["id"])
            for item in run["items"]:
                contexts.setdefault(item["id"], []).append((item, run["set_ids"]))
        backups = self.store.read("backups", [])
        for key, entry in legacy:
            matches = [(item, sets) for item, sets in contexts.get(key, []) if item.get("signature") == entry.get("signature")]
            if not matches:
                for backup in backups:
                    ctx = backup.get("context", {})
                    if ctx.get("target") and Target(**ctx["target"]).key == key:
                        inspector = Inspector(self.scoped(ctx.get("set_ids", [])))
                        item = inspector.inspect(Target(**ctx["target"]))
                        if item and item["legacy_signature"] == entry.get("signature"):
                            matches.append((item, ctx.get("set_ids", [])))
                            break
            if not matches:
                entry.update(status="needs_recheck", message="旧待同步记录缺少可确认的目标；请重新巡检，记录已保留")
                continue
            item, sets = matches[0]
            results = copy.deepcopy(entry.get("results", {}))
            valid = True
            for result in results.values():
                path = result.get("path")
                if result.get("status") == "repaired":
                    backup = next((b for b in reversed(backups) if b.get("path") == path and b.get("committed")), None)
                    if not path or not Path(path).is_file() or not backup or hashlib.sha256(Path(path).read_bytes()).hexdigest() != backup.get("after"):
                        valid = False
                        break
                    result.update(version=backup["after"], file_signature=fingerprint(path))
            if not valid:
                entry.update(status="needs_recheck", message="旧本地修改版本无法确认；请重新巡检，记录已保留")
                continue
            for server in self.scoped(sets).emby_servers or [None]:
                name = server.name if server else ""
                version = digest({a: v.get("version") for a, v in results.items()})
                prior = sync_for_server(entry.get("legacy_sync", entry.get("sync")), name)
                pending[key + ":" + name] = {"target_id": key, "target": item["target"], "server": name, "set_ids": sets,
                    "results": results, "local": item.get("local", {}), "requirements": item.get("requirements", {}),
                    "mode": item.get("emby_mode", "changed"), "version": version, "status": "pending", "updated": time.time(),
                    "sync": {**prior, "server": name, "signature": version, "status": prior.get("status", "pending")}}
            pending.pop(key, None)
        self.store.write_state("pending_sync", pending)
        return pending

    def sync_entry(self, entry, gateways, inspectors):
        server = entry.get("server", "")
        paused = lambda status, message: {"server": server, "status": status, "message": message, "signature": entry.get("version")}
        if not entry.get("target"):
            return paused("needs_recheck", entry.get("message", "缺少可确认的目标"))
        config = self.scoped(entry.get("set_ids", []))
        selected = [s for s in config.emby_servers if s.name == server]
        if not selected or not self.emby_factory:
            return paused("paused", "Emby 服务未配置或已移除")
        key = tuple(entry.get("set_ids", []))
        if key not in inspectors:
            inspectors[key] = Inspector(config)
        inspector = inspectors[key]
        target = reclassify(Target(**entry["target"]), self.source.parse)
        current = inspector.inspect(target) if target is not None else None
        if not current or current["conflicts"]:
            return paused("needs_recheck", "目标已离开规则范围或媒体层级存在冲突")
        if current["emby_mode"] == "off" and not entry.get("force"):
            return paused("paused", "当前规则已关闭 Emby 联动")
        for result in entry.get("results", {}).values():
            if result.get("status") == "repaired":
                path = result.get("path")
                if not path or not Path(path).is_file() or hashlib.sha256(Path(path).read_bytes()).hexdigest() != result.get("version"):
                    return paused("needs_recheck", "本地文件版本发生变化，请重新巡检")
        owned = {r.get("path") for r in entry.get("results", {}).values() if r.get("status") == "repaired"}
        stable = all(sig is None or path in owned or time.time() - sig[0] / 1e9 >= config.stable_seconds
                     for path, sig in current["files"].items())
        if not stable:
            return paused("paused", "等待本地文件稳定")
        current.update(results=entry.get("results", {}), signature=entry["version"], sync=[entry.get("sync", {})],
                       emby_mode=entry.get("mode", "changed"))
        gateway_key = (key, server)
        if gateway_key not in gateways:
            scoped = config.model_copy(deep=True)
            scoped.emby_servers = selected
            gateways[gateway_key] = self.emby_factory(scoped)
        gateway = gateways[gateway_key]
        gateway.stop = self.stop
        def checkpoint(sync):
            pending = self.store.read_state("pending_sync")
            pending_key = entry["target_id"] + ":" + server
            if pending_key in pending:
                pending[pending_key].update(sync=sync, status=sync["status"], updated=time.time())
                self.store.write_state("pending_sync", pending)
        gateway.on_submitted = checkpoint
        responses = gateway.refresh(current, inspector, self.stop)
        return responses[-1] if responses else paused("pending", "已请求停止，等待下次重试")

    def drain_pending(self, report, allowed=None):
        pending = self.migrate_pending()
        # Expand a queue created before any server was configured when configuration becomes available.
        for pending_key, entry in list(pending.items()):
            if entry.get("target") and not entry.get("server"):
                servers = self.scoped(entry.get("set_ids", [])).emby_servers
                for server in servers:
                    new_key = entry["target_id"] + ":" + server.name
                    pending.setdefault(new_key, {**entry, "server": server.name,
                        "sync": {"server": server.name, "status": "pending", "signature": entry["version"]}})
                if servers:
                    pending.pop(pending_key)
        self.store.write_state("pending_sync", pending)
        gateways, inspectors = {}, {}
        indexes = {item["id"]: i for i, item in enumerate(report["items"])}
        for key, entry in list(pending.items()):
            if self.stop.is_set():
                break
            target_id = entry.get("target_id", key)
            if allowed is not None and target_id not in allowed:
                continue
            try:
                sync = self.sync_entry(entry, gateways, inspectors)
            except TaskStopped:
                break
            except StorageError:
                raise
            except Exception as exc:
                sync = {"server": entry.get("server", ""), **failure(exc)}
            # Reload after the submission checkpoint, retaining its durable POST receipt.
            pending = self.store.read_state("pending_sync")
            entry = pending.get(key, entry)
            if sync["status"] in SYNC_DONE:
                receipts = self.store.read_state("sync_receipts")
                versions = {**receipts.get(key, {}).get("versions", {}),
                            **{a: r["version"] for a, r in entry.get("results", {}).items() if r.get("version")}}
                receipts[key] = {"version": entry.get("version"), "versions": versions, "sync": sync, "updated": time.time()}
                self.store.write_state("sync_receipts", receipts)
                pending.pop(key, None)
            else:
                sync = {**entry.get("sync", {}), **sync}
                entry.update(sync=sync, status=sync["status"], updated=time.time())
                pending[key] = entry
            self.store.write_state("pending_sync", pending)
            if target_id in indexes:
                index = indexes[target_id]
                item = report["items"][index]
            else:
                index = len(report["items"])
                item = {"id": target_id, "target": entry.get("target") or {"path": "旧记录：" + key, "kind": "unknown"},
                        "hits": [], "remaining_hits": [], "remaining_assets": [], "actions": [], "conflicts": [],
                        "results": {}, "sync": [], "emby_mode": entry.get("mode", "changed")}
                report["items"].append(item)
                indexes[target_id] = index
            item["sync"] = [s for s in item.get("sync", []) if s.get("server") != sync.get("server")
                            and (s.get("server") or not sync.get("server"))] + [sync]
            item["status"] = item_status(item)
            self.save(report, index)

    def refresh(self, run_id):
        report = self.store.report(run_id)
        self.live["run_id"] = run_id
        if report["dry_run"]:
            raise ValueError("试运行记录不能直接刷新 Emby")
        previous_reason = report.get("exit_reason", "completed")
        config = self.scoped(report["set_ids"])
        if not any(s.enabled and s.emby != "off" for s in config.rule_sets) and not any(i.get("force_sync") for i in report["items"]):
            return report
        report.update(phase="syncing", status="syncing", outcome="running")
        self.save(report, force=True)
        for index, item in enumerate(report["items"]):
            if self.stop.is_set():
                break
            if item.get("status") not in {"ignored", "excluded", "manual"}:
                self.queue_sync(item, report, config, item.get("force_sync", False))
                self.save(report, index)
        if not self.stop.is_set():
            self.drain_pending(report, {item["id"] for item in report["items"]})
        return self.done(report, "batch_limit" if previous_reason == "batch_limit" else "completed")

    def refresh_pending(self):
        report = self.new_report(self.config, operation="refresh_pending")
        report.update(phase="syncing", status="syncing")
        self.save(report, force=True)
        self.drain_pending(report)
        return self.done(report)

    def restore(self, backup_id, sync):
        entry = next((b for b in self.store.read("backups", []) if b["id"] == backup_id), None)
        if not entry:
            raise ValueError("备份不存在")
        config = self.scoped(entry["context"]["set_ids"])
        inspector = Inspector(config)
        target = reclassify(Target(**entry["context"]["target"]), self.source.parse)
        item = inspector.inspect(target) if target is not None else None
        if item is None or item["conflicts"]:
            raise ValueError("该备份对象已不在启用规则范围内或存在层级冲突")
        report = self.new_report(config, operation="restore")
        if self.stop.is_set():
            return self.done(report, "stop")
        self.store.restore(backup_id, self.config, report["id"])
        if entry["asset"] == "nfo": self.translation.restored(entry["path"])
        inspector.invalidate(entry["path"])
        item = inspector.inspect(target)
        data = Path(entry["path"]).read_bytes()
        item["results"] = {entry["asset"]: {"status": "repaired", "restored": True, "path": entry["path"],
                           "version": hashlib.sha256(data).hexdigest(), "file_signature": fingerprint(entry["path"])}}
        item["stable"] = True
        item["force_sync"] = sync
        self.queue_sync(item, report, config, force=sync)
        item["status"] = item_status(item)
        report["items"].append(item)
        self.save(report, force=True)
        return self.refresh(report["id"]) if sync and not self.stop.is_set() else self.done(report)

    def ignore(self, run_id, ids, undo):
        report = self.store.report(run_id)
        self.live["run_id"] = run_id
        ignored = self.store.read_state("ignored")
        inspector = Inspector(self.scoped(report["set_ids"]))
        selected = set(ids)
        for index, previous in enumerate(report["items"]):
            if previous["id"] not in selected:
                continue
            current = self.current_item(previous, inspector)
            ignored.pop(previous["id"], None)
            if not undo and current["status"] != "excluded":
                ignored[current["id"]] = {"signature": current["ignore_signature"]}
                current.update(ignored=True, status="ignored")
            elif undo:
                current.pop("ignored", None)
                current["status"] = item_status(current)
            report["items"][index] = current
            self.save(report, index)
        self.store.write_state("ignored", ignored)
        return self.done(report, "inspected" if report["dry_run"] else "completed")
