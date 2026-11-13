"""MoviePilot V3 元数据巡检 plugin."""

import copy
import threading
from functools import wraps
from typing import Literal

from app.api.deps import get_current_active_manage_user
from app.sdk.logging import logger
from app.sdk.plugin import _PluginBase
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .adapters import MoviePilotSource
from .config import ASSETS, Config, defaults
from .emby import EmbyGateway
from .engine import Engine
from .errors import safe_message
from .fields import NFO_FIELDS
from .translation import TranslationBridge


def lifecycle(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lifecycle_lock:
            return method(self, *args, **kwargs)

    return wrapped


class Operation(BaseModel):
    operation: Literal[
        "inspect", "run", "repair", "resume", "refresh", "refresh_pending", "restore", "ignore"
    ] = "inspect"
    run_id: str | None = None
    set_ids: list[str] | None = None
    ids: list[str] | None = None
    dry_run: bool = True
    retry: bool = False
    undo: bool = False
    backup_id: str | None = None
    sync: bool = False
    translation_overwrite: bool = False
    translation_force: bool = False


class DeleteRuns(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=1000)


class NfoCheck(_PluginBase):
    plugin_name = "元数据巡检"
    plugin_desc = "按多套规则巡检 NFO 与图片，选择性补刮并通知 Emby 刷新。"
    plugin_icon = "scraper.png"
    plugin_version = "1.2.0"
    _lifecycle_lock = threading.RLock()
    plugin_author = "NfoCheck Contributors"
    author_url = ""
    plugin_config_prefix = "nfocheck_"
    plugin_order = 50
    auth_level = 1

    @lifecycle
    def init_plugin(self, config=None):
        self.stop_service()
        self._raw_config = copy.deepcopy(config or defaults())
        parsed = Config.model_validate(self._raw_config)
        self.engine = Engine(
            parsed.model_dump(), self.get_data_path(), MoviePilotSource(), EmbyGateway, self._notify
        )

    @lifecycle
    def stop_service(self):
        engine = getattr(self, "engine", None)
        if not engine:
            return
        engine.stop.set()
        if engine.thread and engine.thread.is_alive():
            engine.thread.join(timeout=35)
        if engine.lock.locked():
            raise RuntimeError("巡检任务仍在退出，请稍后重载，避免同时写入")

    def get_state(self):
        return bool(getattr(self, "engine", None) and self.engine.config.enabled)

    @staticmethod
    def get_render_mode():
        return "vue", "dist/assets"

    def get_form(self):
        return [], defaults()

    def get_page(self):
        return []

    @staticmethod
    def get_command():
        return []

    def get_service(self):
        return []

    def _notify(self, text, report):
        config = self.engine.config
        if config.notify == "off":
            return
        issues = report["errors"] or any(
            i["hits"]
            or i["conflicts"]
            or any(s["status"] not in {"complete", "verified"} for s in i["sync"])
            for i in report["items"]
        )
        if config.notify == "issues" and not issues:
            return
        from app.schemas.types import MessageType, NotificationChannel

        examples = [i["target"]["path"] for i in report["items"] if i["hits"] or i["conflicts"]][:5]
        for channel in config.notify_channels or [None]:
            try:
                self.post_message(
                    channel=NotificationChannel(channel) if channel else None,
                    mtype=MessageType.Plugin,
                    title="元数据巡检" + ("（试运行）" if report["dry_run"] else ""),
                    text=text + ("\n" + "\n".join(examples) if examples else ""),
                )
            except Exception as exc:
                logger.warning(f"元数据巡检通知失败：{type(exc).__name__}")

    def api_settings(self, user=Depends(get_current_active_manage_user)):
        from app.schemas.types import NotificationChannel
        from app.sdk.services import MediaServerHelper

        return {
            "config": self.engine.config.model_dump(),
            "assets": ASSETS,
            "nfo_fields": NFO_FIELDS,
            "translation": TranslationBridge.describe(),
            "servers": list(MediaServerHelper().get_services(type_filter="emby")),
            "channels": [{"title": c.value, "value": c.value} for c in NotificationChannel],
        }

    @lifecycle
    def api_save(self, payload: Config, user=Depends(get_current_active_manage_user)):
        if self.engine.lock.locked():
            raise HTTPException(409, "任务运行中，请停止后保存设置")
        if self._raw_config.get("version", 1) < 2:
            store = self.engine.store
            (store.directory / "migration-1.1.0").mkdir(exist_ok=True)
            if not (store.directory / "migration-1.1.0/config.json").exists():
                store.write("migration-1.1.0/config", self._raw_config)
        if self._raw_config.get("version", 1) < 3:
            directory = self.engine.store.directory / "migration-1.2.0"
            directory.mkdir(exist_ok=True)
            if not (directory / "config.json").exists():
                self.engine.store.write("migration-1.2.0/config", self._raw_config)
        payload.version = 3
        self.update_config(payload.model_dump())
        self.init_plugin(payload.model_dump())
        return {"ok": True}

    def api_status(
        self, include_backups: bool = False, user=Depends(get_current_active_manage_user)
    ):
        result = {
            "live": dict(self.engine.live),
            "runs": self.engine.store.reports(),
            "pending_count": len(self.engine.store.read_state("pending_sync")),
        }
        if include_backups:
            result["backups"] = self.engine.store.read("backups", [])
        return result

    def api_report(
        self,
        run_id: str,
        page: int = 1,
        page_size: int = 100,
        query: str = "",
        status: str = "",
        kind: str = "",
        rule_set: str = "",
        ids_only: bool = False,
        user=Depends(get_current_active_manage_user),
    ):
        try:
            return self.engine.store.report_page(
                run_id, page, page_size, query, status, kind, rule_set, ids_only
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @lifecycle
    def api_delete_runs(self, payload: DeleteRuns, user=Depends(get_current_active_manage_user)):
        if not self.engine.lock.acquire(False):
            raise HTTPException(409, "任务运行中，请结束后删除运行记录")
        try:
            deleted = self.engine.store.delete_reports(payload.ids)
            if self.engine.live.get("run_id") in payload.ids:
                self.engine.live["run_id"] = None
            return {"deleted": deleted}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            self.engine.lock.release()

    @lifecycle
    def api_start(self, payload: Operation, user=Depends(get_current_active_manage_user)):
        params = payload.model_dump(exclude={"operation"})
        if (payload.translation_overwrite or payload.translation_force) and (
            payload.operation != "repair" or not payload.ids
        ):
            raise HTTPException(422, "覆盖本地字段或强制重译只允许用于明确选中的修复任务")
        if payload.operation in {"repair", "resume", "refresh", "ignore"} and not payload.run_id:
            raise HTTPException(422, "缺少运行编号")
        if payload.operation == "restore" and not payload.backup_id:
            raise HTTPException(422, "缺少备份编号")
        if (
            payload.operation in {"repair", "resume", "refresh", "refresh_pending", "restore"}
            or payload.operation == "run"
            and not payload.dry_run
        ):
            if not self.get_state():
                raise HTTPException(409, "请先启用插件")
        if payload.operation == "resume":
            try:
                if self.engine.store.report(payload.run_id)["dry_run"]:
                    raise HTTPException(422, "试运行记录不能继续执行")
            except ValueError as exc:
                raise HTTPException(404, str(exc)) from exc
        try:
            return self.engine.start(
                payload.operation, **params, notify=payload.operation != "ignore"
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    def api_pending(
        self, page: int = 1, page_size: int = 100, user=Depends(get_current_active_manage_user)
    ):
        return self.engine.store.pending_page(page, page_size)

    def api_stop(self, user=Depends(get_current_active_manage_user)):
        self.engine.stop.set()
        return {"ok": True, "message": "将在当前文件操作结束后停止"}

    def get_api(self):
        return [
            {
                "path": "/" + name,
                "endpoint": endpoint,
                "methods": [method],
                "auth": "bear",
                "summary": name,
            }
            for name, endpoint, method in [
                ("settings", self.api_settings, "GET"),
                ("settings", self.api_save, "POST"),
                ("status", self.api_status, "GET"),
                ("report", self.api_report, "GET"),
                ("start", self.api_start, "POST"),
                ("stop", self.api_stop, "POST"),
                ("delete_runs", self.api_delete_runs, "POST"),
                ("pending", self.api_pending, "GET"),
            ]
        ]

    def get_actions(self):
        return [
            {
                "id": "inspect",
                "name": "巡检 NFO 和图片",
                "func": self.workflow_inspect,
                "kwargs": {"source": "workflow", "dry_run": False},
            },
            {
                "id": "repair",
                "name": "选择性补刮并复查",
                "func": self.workflow_repair,
                "kwargs": {},
            },
            {
                "id": "refresh_emby",
                "name": "刷新 Emby 并复查",
                "func": self.workflow_refresh,
                "kwargs": {},
            },
            {
                "id": "refresh_pending",
                "name": "重试独立 Emby 待同步队列",
                "func": self.workflow_refresh_pending,
                "kwargs": {},
            },
        ]

    def _workflow(self, context, operation, **kwargs):
        try:
            with self._lifecycle_lock:
                engine = self.engine
                engine.reserve(kwargs)
            report = engine._execute_locked(operation, kwargs)
            if context.workflow_context is None:
                context.workflow_context = {}
            context.workflow_context["nfocheck"] = {
                "run_id": report["id"],
                "summary": report["summary"],
            }
            context.content = report["summary"]
            from app.schemas.workflow import ActionExecution

            if context.execute_history is None:
                context.execute_history = []
            context.execute_history.append(
                ActionExecution(
                    action="元数据巡检", result=not report["errors"], message=report["summary"]
                )
            )
            return not report["errors"], context
        except Exception as exc:
            context.content = "元数据巡检失败：" + safe_message(exc)
            return False, context

    def workflow_inspect(self, context, source="workflow", set_ids=None, dry_run=False):
        if source not in {"workflow", "configured"}:
            raise ValueError("source 仅支持 workflow 或 configured")
        files = (
            [item.path for item in (context.fileitems or []) if item.storage == "local"]
            if source == "workflow"
            else None
        )
        return self._workflow(context, "inspect", files=files, set_ids=set_ids, dry_run=dry_run)

    def workflow_repair(self, context):
        run_id = (context.workflow_context or {}).get("nfocheck", {}).get("run_id")
        if self.engine.store.report(run_id)["dry_run"]:
            return True, context
        return self._workflow(context, "repair", run_id=run_id)

    def workflow_refresh(self, context):
        run_id = (context.workflow_context or {}).get("nfocheck", {}).get("run_id")
        if self.engine.store.report(run_id)["dry_run"]:
            return True, context
        return self._workflow(context, "refresh", run_id=run_id)

    def workflow_refresh_pending(self, context):
        return self._workflow(context, "refresh_pending")
