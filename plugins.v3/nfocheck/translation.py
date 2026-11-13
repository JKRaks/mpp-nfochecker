"""Optional integration; no import dependency on the translation plugin package."""

import hashlib
from pathlib import Path

from .core import ROOT_TAGS, digest, fingerprint
from .errors import TaskStopped

FIELDS = {
    "title": "标题(title)",
    "plot": "剧情简介(plot)",
    "outline": "简短摘要(outline)",
    "tagline": "宣传语(tagline)",
}
LANGUAGE_OPS = {"language_missing", "language_mismatch", "language_unknown"}
TRANSLATE_ACTIONS = {"translate", "nfo_translate"}


class TranslationBridge:
    def __init__(self, source, store, stop):
        self.source, self.store, self.stop = source, store, stop
        self.service, self.token = None, None
        self.cache = {}
        self.overwrite = self.force = False
        self.retry = False

    def revision(self):
        try:
            return self.open().revision
        except Exception:
            return "unavailable"

    @staticmethod
    def locate():
        from app.sdk.plugin import PluginManager

        getter = PluginManager().get_plugin_attr("MetadataTranslate", "translation_service")
        service = getter() if callable(getter) else None
        if service is None or service.describe().get("contract_version") != 1:
            raise ValueError("元数据翻译插件未安装或接口版本不兼容")
        return service

    @classmethod
    def describe(cls):
        try:
            return cls.locate().describe()
        except Exception:
            return {
                "enabled": False,
                "policies": [],
                "fields": FIELDS,
                "message": "元数据翻译插件不可用",
            }

    def open(self):
        if self.service is None:
            service = self.locate()
            token = service.begin_batch()
            self.service, self.token = service, token
        return self.service

    def close(self):
        if self.service is not None:
            self.service.end_batch(self.token)
        self.service, self.token = None, None
        self.cache.clear()

    def provenance(self, target):
        key = str(target.nfo())
        intents = self.store.read("translation_intents", {})
        intent = intents.get(key)
        if (
            intent
            and target.nfo().is_file()
            and hashlib.sha256(target.nfo().read_bytes()).hexdigest() == intent["file_version"]
        ):
            entries = self.store.read("translation_writes", {})
            entries[key] = intent
            self.store.write("translation_writes", entries)
            intents.pop(key, None)
            self.store.write("translation_intents", intents)
        return self.store.read("translation_writes", {}).get(key, {}).get("fields", {})

    def identity(self, target):
        meta, info = self.source.resolve(target)
        # The provider plugin owns the host compatibility boundary.
        from app.sdk.plugin import PluginManager

        callback = PluginManager().get_plugin_attr("MetadataTranslate", "identify")
        if not callable(callback):
            raise ValueError("翻译插件缺少媒体身份接口")
        return callback(
            meta,
            info,
            target.season if target.kind in {"season", "episode"} else None,
            target.episode if target.kind == "episode" else None,
        )

    def assess(self, target, rule):
        key = digest(
            [
                target.key,
                fingerprint(target.nfo()),
                rule.translation_policy,
                rule.translation_fields,
                self.provenance(target),
                self.overwrite,
                self.force,
            ]
        )
        if key in self.cache:
            return self.cache[key]
        try:
            if self.stop.is_set():
                raise TaskStopped()
            service = self.open()
            nfo = (
                target.nfo().read_bytes()
                if target.nfo().exists()
                else f"<{ROOT_TAGS[target.kind]}/>".encode()
            )
            result = service.assess(
                self.identity(target),
                nfo,
                rule.translation_policy,
                rule.translation_fields,
                self.provenance(target),
                self.token,
                self.overwrite,
                self.force,
            )
        except TaskStopped:
            raise
        except Exception as exc:
            result = {
                "fields": {
                    f: {
                        "status": "failed",
                        "error_code": getattr(exc, "code", "translation_unavailable"),
                        "message": (
                            str(exc)
                            if hasattr(exc, "code") or isinstance(exc, ValueError)
                            else "翻译检查不可用"
                        ),
                    }
                    for f in rule.translation_fields
                }
            }
        self.cache[key] = result
        return result

    def match(self, target, rule, condition):
        value = (
            self.assess(target, rule)
            .get("fields", {})
            .get(condition.field, {"status": "not_applicable"})
        )
        status = value.get("status")
        if condition.op == "language_unknown":
            hit = status in {"language_unknown", "protected"}
        elif condition.op == "language_mismatch":
            hit = bool(value.get("before")) and status in {"source_available", "needs_translation"}
        else:
            hit = status in {"source_available", "needs_translation", "no_source_text", "failed"}
        return hit, value

    def prepare(self, target, plan, item):
        service = self.open()
        if self.stop.is_set():
            raise TaskStopped()
        prior = item.get("results", {}).get("nfo", {})
        generated = plan["mode"] == "generate" and not (
            prior.get("translation_generated")
            and prior.get("translation_plan_signature") == digest(plan)
            and prior.get("file_signature") == fingerprint(target.nfo())
        )
        if generated:
            meta, info = self.source.resolve(target)
            from app.sdk.plugin import PluginManager

            callback = PluginManager().get_plugin_attr("MetadataTranslate", "base_nfo")
            raw = callback(
                meta,
                info,
                target.season if target.kind in {"season", "episode"} else None,
                target.episode if target.kind == "episode" else None,
            )
            if not raw:
                raise ValueError("官方来源未生成 NFO")
        else:
            if not target.nfo().is_file():
                raise ValueError("仅翻译需要有效 NFO，请选择重新生成 NFO 并翻译")
            raw = target.nfo().read_bytes()
        result = service.prepare_nfo(
            self.identity(target),
            raw,
            plan["policy"],
            plan["fields"],
            self.provenance(target),
            self.token,
            self.stop,
            self.overwrite,
            self.force,
            generated,
            deferred=(
                prior.get("details", {}).get("fields", {})
                if not self.retry
                and prior.get("translation_revision") == service.revision
                and prior.get("file_signature") == fingerprint(target.nfo())
                else None
            ),
        )
        result["generated"] = generated or bool(prior.get("translation_generated"))
        if self.stop.is_set():
            raise TaskStopped()
        return result

    def intent(self, target, result, file_version):
        entries = self.store.read("translation_writes", {})
        key = str(target.nfo())
        previous = entries.get(key, {}).get("fields", {})
        entries[key] = {
            "fields": {**previous, **result["provenance"]},
            "file_version": file_version,
            "revision": result["revision"],
        }
        intents = self.store.read("translation_intents", {})
        intents[key] = entries[key]
        self.store.write("translation_intents", intents)

    def committed(self, target, result, file_version):
        self.provenance(target)  # Promote the durable intent only after the file hash matches.
        self.cache.clear()

    def restored(self, path):
        entries = self.store.read("translation_writes", {})
        entries.pop(str(path), None)
        self.store.write("translation_writes", entries)
        intents = self.store.read("translation_intents", {})
        intents.pop(str(path), None)
        self.store.write("translation_intents", intents)
        self.cache.clear()
