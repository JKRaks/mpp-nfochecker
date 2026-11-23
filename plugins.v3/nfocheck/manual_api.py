"""MoviePilot endpoints for reviewing and saving one sidecar."""
import base64
import binascii
import io
import re
import threading
from contextlib import contextmanager
from typing import Literal

from fastapi import Depends, HTTPException
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_current_active_manage_user
from .core import ROOT_TAGS, identities
from .errors import CandidateRejected, FileConflict, SourceUnavailable, StorageError, TaskStopped, safe_message
from .manual import IMAGE_LIMIT, NFO_LIMIT, ManualRepair, read_asset, tmdb_ids, xml_document, xml_root


IMAGE_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "BMP": "image/bmp"}
XML_ENCODING = re.compile(r"""^(\ufeff?<\?xml\s+[^?]*?\bencoding\s*=\s*)(['"])[^'"]+\2(?=[^?]*\?>)""")


def utf8_declaration(text):
    return XML_ENCODING.sub(lambda m: m[1] + m[2] + "UTF-8" + m[2], text, count=1)


class ManualTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=32, max_length=32)
    item_id: str = Field(min_length=1, max_length=128)
    asset: str = Field(min_length=1, max_length=40)
    version: str = Field(min_length=1, max_length=256)


class ManualTmdbLookup(ManualTarget):
    asset: Literal["nfo"]
    tmdb_id: str = Field(min_length=1, max_length=32)


class ManualInput(ManualTarget):
    fields: dict[str, str] | None = Field(default=None, max_length=16)
    nfo: str | None = Field(default=None, max_length=NFO_LIMIT)
    image: str | None = Field(default=None, max_length=4 * ((IMAGE_LIMIT + 2) // 3) + 64)

    def prepare(self, repair):
        if sum(v is not None for v in (self.fields, self.nfo, self.image)) != 1:
            raise ValueError("每次只能提交一组字段、一份 NFO 或一张图片")
        if self.asset == "nfo" and self.image is None:
            if self.fields is not None:
                if not self.fields or sum(len(v.encode()) for v in self.fields.values()) > NFO_LIMIT:
                    raise ValueError("请提供要修改的字段，文字总量最多 2 MiB")
                return repair.prepare(self.version, fields=self.fields)
            data = utf8_declaration(self.nfo).encode("utf-8")
            if len(data) > NFO_LIMIT:
                raise ValueError("NFO 超过 2 MiB")
        elif self.asset != "nfo" and self.image is not None:
            encoded = self.image.partition(",")[2] if self.image.startswith("data:") else self.image
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                raise ValueError("图片数据不完整，请重新选择文件") from None
            if not data or len(data) > IMAGE_LIMIT:
                raise ValueError("请选择一张 20 MiB 以内的图片")
        else:
            raise ValueError("提交内容与所选文件类型不一致")
        return repair.prepare(self.version, content=data)


def data_url(mime, data):
    return "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")


def current_image(data):
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.thumbnail((640, 640))
            output = io.BytesIO()
            image.convert("RGBA").save(output, format="PNG")
            return data_url("image/png", output.getvalue())
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def xml_text(data):
    try:
        return utf8_declaration(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        return xml_document(data).toxml(encoding="utf-8").decode("utf-8")


def rejection_message(error):
    if isinstance(error, CandidateRejected):
        info = error.details
        if {"actual_width", "actual_height", "min_width", "min_height"} <= info.keys():
            return (f"图片为 {info['actual_width']} × {info['actual_height']} 像素，"
                    f"规则要求至少 {info['min_width']} × {info['min_height']} 像素")
    return safe_message(error)


def source_options(engine, repair, asset, tmdb_id=None):
    items = []
    total = 0
    message = ""
    try:
        candidates = (engine.source.iter_tmdb_nfo(repair.target, tmdb_id, engine.stop)
                      if tmdb_id is not None else engine.candidates(repair.target, asset))
        for candidate in candidates:
            if len(items) >= 8:
                message = "本次只显示前 8 个候选"
                break
            label = f"来源候选 {len(items) + 1}"
            if isinstance(candidate, Exception):
                items.append({"label": label, "error": safe_message(candidate)})
                continue
            _, data = candidate
            if len(data) > (NFO_LIMIT if asset == "nfo" else IMAGE_LIMIT):
                items.append({"label": label, "error": "候选文件超过大小上限"})
                continue
            if total + len(data) > IMAGE_LIMIT:
                message = "其余候选超过本次预览容量"
                break
            try:
                if asset == "nfo":
                    option = {"nfo": xml_text(data)}
                    xml = xml_root(data)
                    if xml.tag != ROOT_TAGS[repair.target.kind]:
                        raise CandidateRejected("候选 NFO 的媒体类型不符")
                    if repair.inspector.conflict(repair.target, xml):
                        raise CandidateRejected("候选 NFO 的媒体身份或季集编号不符")
                    incoming = identities(xml)
                    local = {**repair.expected_ids, **repair.current["local"]["ids"]}
                    if tmdb_id is not None:
                        primary, compatible = tmdb_ids(xml)
                        if (primary or compatible) != tmdb_id:
                            raise CandidateRejected("MoviePilot 返回的候选与填写的 TMDB 编号不一致")
                        incoming["tmdb"] = tmdb_id
                        local["tmdb"] = tmdb_id
                        label = " · ".join(filter(None, [f"TMDB {tmdb_id}", xml.findtext("title"), xml.findtext("year")]))
                    shared = local.keys() & incoming.keys()
                    if local and not shared:
                        raise CandidateRejected("候选 NFO 缺少可与本地核对的来源 ID")
                    if any(incoming[name] != local[name] for name in shared):
                        raise CandidateRejected("候选 NFO 的来源 ID 与本地记录不符")
                    if repair.target.kind in {"season", "episode"}:
                        numbers = {"seasonnumber": repair.target.season} if repair.target.kind == "season" else {
                            "season": repair.target.season, "episode": repair.target.episode}
                        if any(number is None or (xml.findtext(tag) or "").strip() != str(number)
                               for tag, number in numbers.items()):
                            raise CandidateRejected("候选 NFO 缺少可与路径核对的季集编号")
                    if repair.xml is None or repair.xml.tag != xml.tag:
                        repair.prepare(repair.version, content=option["nfo"].encode("utf-8"))
                else:
                    engine.validate_candidate(repair.target, asset, data, repair.current, repair.inspector)
                    with Image.open(io.BytesIO(data)) as image:
                        mime = IMAGE_TYPES.get(image.format)
                        if not mime:
                            raise ValueError("该图像格式不支持预览")
                        label += f" · {image.width} × {image.height}"
                    option = {"image": data_url(mime, data)}
            except (ValueError, OSError, Image.DecompressionBombError, SyntaxError) as exc:
                items.append({"label": label, "error": rejection_message(exc)})
                continue
            total += len(data)
            items.append({"label": label, **option})
    except SourceUnavailable as exc:
        message = safe_message(exc)
    return {"items": items, "message": message or ("" if items else "刮削来源没有提供候选")}


@contextmanager
def manual_errors():
    try:
        yield
    except FileConflict as exc:
        raise HTTPException(409, safe_message(exc)) from exc
    except TaskStopped as exc:
        raise HTTPException(409, "任务已停止，请重新打开条目") from exc
    except (ValueError, SyntaxError, Image.DecompressionBombError, UnidentifiedImageError) as exc:
        raise HTTPException(422, rejection_message(exc)) from exc
    except (StorageError, OSError) as exc:
        raise HTTPException(503, safe_message(exc)) from exc


@contextmanager
def read_engine(plugin):
    with plugin._lifecycle_lock:
        engine = plugin.engine
        if not engine.lock.acquire(False):
            raise HTTPException(409, "巡检任务正在执行，请稍后再试")
        engine.stop.clear()
    try:
        with manual_errors():
            engine.translation.overwrite = engine.translation.force = engine.translation.retry = False
            if hasattr(engine.source, "begin_run"):
                engine.source.begin_run()
            yield engine
    finally:
        try:
            engine.translation.close()
        finally:
            engine.lock.release()


class ManualAPI:
    def api_manual_detail(self, run_id: str, item_id: str, asset: str,
                          user=Depends(get_current_active_manage_user)):
        with read_engine(self) as engine:
            repair = ManualRepair(engine, run_id, item_id, asset)
            result = repair.detail()
            original = repair.original
            if original and asset == "nfo" and len(original) <= NFO_LIMIT:
                try:
                    result["nfo"] = xml_text(original)
                except (ValueError, SyntaxError):
                    result["nfo"] = original.decode("utf-8", errors="replace")
            elif original and asset != "nfo" and len(original) <= IMAGE_LIMIT:
                result["image_url"] = current_image(original)
            return result

    def api_manual_candidates(self, run_id: str, item_id: str, asset: str,
                              user=Depends(get_current_active_manage_user)):
        with read_engine(self) as engine:
            return source_options(engine, ManualRepair(engine, run_id, item_id, asset), asset)

    def api_manual_candidates_by_tmdb(self, payload: ManualTmdbLookup, user=Depends(get_current_active_manage_user)):
        with read_engine(self) as engine:
            repair = ManualRepair(engine, payload.run_id, payload.item_id, payload.asset)
            if payload.version != repair.version:
                raise FileConflict("文件或命中规则已变化，请重新打开后再读取候选")
            tmdb_id = repair.check_tmdb_id(payload.tmdb_id)
            return source_options(engine, repair, payload.asset, tmdb_id)

    def api_manual_preview(self, payload: ManualInput, user=Depends(get_current_active_manage_user)):
        with read_engine(self) as engine:
            repair = ManualRepair(engine, payload.run_id, payload.item_id, payload.asset)
            return repair.preview(payload.prepare(repair))

    def api_manual_save(self, payload: ManualInput, user=Depends(get_current_active_manage_user)):
        with self._lifecycle_lock:
            engine = self.engine
            if not engine.config.enabled:
                raise HTTPException(409, "请先启用修复")
            try:
                engine.reserve({"run_id": payload.run_id})
            except ValueError as exc:
                raise HTTPException(409, safe_message(exc)) from exc
        handed_off = False
        try:
            with manual_errors():
                repair = ManualRepair(engine, payload.run_id, payload.item_id, payload.asset)
                prepared = payload.prepare(repair)
                try:
                    result = repair.save(prepared)
                except (OSError, StorageError) as exc:
                    try:
                        written = prepared.data != repair.original and read_asset(
                            repair.path, NFO_LIMIT if payload.asset == "nfo" else IMAGE_LIMIT) == prepared.data
                    except (OSError, ValueError):
                        written = False
                    if written:
                        raise HTTPException(503, "文件已写入，后续记录未完成。请重新巡检并核对待同步记录。" + safe_message(exc)) from exc
                    raise
                keys = result.pop("_queued_keys", ())
                if keys and not engine.stop.is_set():
                    # The worker inherits the reservation so a second write cannot slip
                    # between commit and Emby verification. The client can return now.
                    def sync():
                        try:
                            engine._execute_locked("sync_manual", {"run_id": payload.run_id, "keys": keys})
                        except Exception:
                            pass  # _execute_locked records the error and releases the lock.
                    worker = threading.Thread(target=sync, name="NfoCheckManualSync", daemon=True)
                    with self._lifecycle_lock:
                        engine.thread = worker
                        try:
                            worker.start()
                        except RuntimeError:
                            engine.thread = None
                            result["message"] += "。Emby 待同步，可在待同步页重试"
                        else:
                            handed_off = True
                return result
        finally:
            if not handed_off:
                try:
                    engine.translation.close()
                    engine.store.release(payload.run_id)
                finally:
                    engine.live["busy"] = False
                    engine.lock.release()
