"""Emby read/refresh only. Never uploads images or replaces all images."""

import hashlib
import threading
import time
from pathlib import Path, PurePosixPath
from urllib.parse import urlencode

import requests

from .core import Target, within
from .errors import StorageError, TaskStopped, failure, safe_message

IMAGE_TYPES = {
    "poster": "Primary",
    "thumb": "Thumb",
    "backdrop": "Backdrop",
    "logo": "Logo",
    "banner": "Banner",
    "landscape": "Thumb",
    "clearart": "Art",
    "disc": "Disc",
}
ITEM_TYPES = {"movie": "Movie", "tv": "Series", "season": "Season", "episode": "Episode"}


def image_type(target, asset):
    return "Primary" if target.kind == "episode" and asset == "thumb" else IMAGE_TYPES[asset]


def has_image(item, kind):
    return (
        bool(item.get("BackdropImageTags"))
        if kind == "Backdrop"
        else bool(item.get("ImageTags", {}).get(kind))
    )


def map_path(path, mappings):
    for mapping in sorted(mappings, key=lambda m: len(m["local"]), reverse=True):
        if within(path, mapping["local"]):
            relative = Path(path).resolve().relative_to(Path(mapping["local"]).resolve())
            return (
                (PurePosixPath(mapping["remote"].replace("\\", "/")) / relative.as_posix())
                .as_posix()
                .rstrip("/")
            )
    return str(path).replace("\\", "/").rstrip("/")


class EmbyGateway:
    def __init__(self, config, services=None):
        self.config = config
        if services is None:
            from app.sdk.services import MediaServerHelper

            services = {
                name: service.instance
                for name, service in MediaServerHelper().get_services(type_filter="emby").items()
            }
        self.services = services
        self.indexes = {}
        self.stop = threading.Event()
        self.on_submitted = None

    def request(self, server, method, path, params=None):
        if self.stop.is_set():
            raise TaskStopped()
        service = self.services.get(server)
        if service is None:
            raise ConnectionError("所选 Emby 服务未启用或不在线")
        params = {**(params or {}), "api_key": "[APIKEY]"}
        url = (
            "[HOST]"
            + path.lstrip("/")
            + "?"
            + urlencode(params).replace("%5BAPIKEY%5D", "[APIKEY]")
        )
        response = (
            service.get_data(url)
            if method == "GET"
            else service.post_data(url, data="{}", headers={"Content-Type": "application/json"})
        )
        if response is None:
            raise ConnectionError("Emby 请求未返回结果")
        try:
            if response.status_code not in {200, 202, 204}:
                raise ConnectionError(f"Emby HTTP {response.status_code}")
            return response.json() if method == "GET" else None
        finally:
            response.close()

    def inventory(self, server):
        if server.name in self.indexes:
            return self.indexes[server.name]
        entries = {}
        for library in server.libraries or [""]:
            start = 0
            while True:
                if self.stop.is_set():
                    raise TaskStopped()
                params = {
                    "Recursive": "true",
                    "IncludeItemTypes": "Movie,Series,Season,Episode",
                    "StartIndex": start,
                    "Limit": 500,
                    "Fields": "Path,Overview,Taglines,ProviderIds,LockedFields,MediaSources",
                }
                if library:
                    params["ParentId"] = library
                page = self.request(server.name, "GET", "Items", params)
                rows = page.get("Items", [])
                for item in rows:
                    entries[str(item["Id"])] = item
                start += len(rows)
                if not rows or start >= page.get("TotalRecordCount", start):
                    break
        index = {}
        for item in entries.values():
            paths = {
                str(p).replace("\\", "/").rstrip("/")
                for p in [item.get("Path", "")]
                + [source.get("Path", "") for source in item.get("MediaSources", [])]
                if p
            }
            for path in paths:
                index.setdefault((item.get("Type"), path), []).append(item)
        self.indexes[server.name] = index
        return self.indexes[server.name]

    def locate(self, server, record):
        target = Target(**record["target"])
        path = map_path(target.path, server.mappings)
        items = self.inventory(server).get((ITEM_TYPES[target.kind], path), [])
        if len(items) != 1:
            raise ValueError("未匹配 Emby 条目" if not items else "Emby 路径匹配不唯一")
        item = items[0]
        self.validate_item(server, record, item)
        return item

    def detail(self, server, item_id):
        # Emby exposes global item lookup through the Items query. Its single-item
        # /Items/{id} route is not available on all supported Emby versions.
        page = self.request(
            server,
            "GET",
            "Items",
            {
                "Ids": str(item_id),
                "Limit": 2,
                "Fields": "Path,ProviderIds,MediaSources,Overview,Taglines,LockedFields",
            },
        )
        rows = page.get("Items", []) if isinstance(page, dict) else []
        if not isinstance(rows, list) or len(rows) != 1 or str(rows[0].get("Id")) != str(item_id):
            raise ValueError("Emby 最新条目查询未返回唯一的目标 ID")
        return rows[0]

    @staticmethod
    def validate_item(server, record, item, expected_id=None):
        """Validate the actual item used for a refresh, including fresh GET responses."""
        target = Target(**record["target"])
        if not item.get("Id") or expected_id is not None and str(item["Id"]) != str(expected_id):
            raise ValueError("Emby 条目 ID 与定位结果冲突")
        if item.get("Type") != ITEM_TYPES[target.kind]:
            raise ValueError("Emby 条目类型与本地媒体层级冲突")
        paths = {
            str(p).replace("\\", "/").rstrip("/")
            for p in [item.get("Path", "")]
            + [source.get("Path", "") for source in (item.get("MediaSources") or [])]
            if p
        }
        if map_path(target.path, server.mappings) not in paths:
            raise ValueError("Emby 条目路径与本地映射不一致或缺失")
        if target.kind in {"episode", "season"}:
            for field, expected in [
                ("IndexNumber", target.episode if target.kind == "episode" else target.season),
                ("ParentIndexNumber", target.season if target.kind == "episode" else None),
            ]:
                if expected is not None and item.get(field) is not None and item[field] != expected:
                    raise ValueError("Emby 季集编号与本地路径冲突")
        if target.kind in {"movie", "tv"}:
            ids = {k.lower(): str(v) for k, v in (item.get("ProviderIds") or {}).items()}
            if any(k in ids and ids[k] != v for k, v in record["local"]["ids"].items()):
                raise ValueError("Emby 媒体身份与本地冲突")

    def missing(self, item, record, inspector):
        target = Target(**record["target"])
        fields, assets = [], []
        # Only use fields for which the local NFO contains a value.
        for local, remote in [("title", "Name"), ("plot", "Overview"), ("tagline", "Taglines")]:
            present = item.get(remote) or ""
            if isinstance(present, list):
                present = " ".join(str(x) for x in present)
            if record["local"].get(local) and not present.strip():
                fields.append(remote)
        remote_ids = {k.lower(): v for k, v in item.get("ProviderIds", {}).items()}
        if any(not remote_ids.get(k) for k in record["local"].get("ids", {})):
            fields.append("ProviderIds")
        for asset, checks in record["requirements"].items():
            from .config import ImageCheck

            files = inspector.candidates(target, asset)
            usable = files and all(
                not inspector.image_matches(target, ImageCheck(**check))[0] for check in checks
            )
            if usable and not has_image(item, image_type(target, asset)):
                assets.append(asset)
        return fields, assets

    def compare(self, record, inspector):
        results = []
        for server in self.config.emby_servers:
            try:
                item = self.locate(server, record)
                fields, assets = self.missing(item, record, inspector)
                locked = bool(
                    item.get("LockData")
                    or item.get("IsLocked")
                    or set(item.get("LockedFields", [])) & set(fields)
                )
                results.append(
                    {
                        "server": server.name,
                        "item_id": str(item["Id"]),
                        "fields": fields,
                        "assets": assets,
                        "status": (
                            "locked"
                            if locked and fields
                            else "pending" if fields or assets else "complete"
                        ),
                    }
                )
            except (ConnectionError, ValueError) as exc:
                results.append(
                    {"server": server.name, "status": "failed", "message": safe_message(exc)}
                )
        return results

    @staticmethod
    def image_tag(item, kind):
        return (
            item.get("BackdropImageTags", [])
            if kind == "Backdrop"
            else item.get("ImageTags", {}).get(kind)
        )

    def image_matches_version(self, server, item, record, asset):
        result = record.get("results", {}).get(asset, {})
        path, version = result.get("path"), result.get("version")
        if not path or not version:
            return False
        target = Target(**record["target"])
        key = (
            server,
            str(item["Id"]),
            asset,
            version,
            str(self.image_tag(item, image_type(target, asset))),
        )
        limit = 20 * 1024 * 1024
        try:
            local = Path(path)
            if not within(local, target.root) or local.stat().st_size > limit:
                return False
            if hashlib.sha256(local.read_bytes()).hexdigest() != version:
                return False
            if key in self.image_verified:
                return True
            budget_key = (server, str(item["Id"]), asset)
            if (
                self.image_reads.get(budget_key, 0) >= 8
                or self.image_reads.get(key, 0) >= 4
                or self.stop.is_set()
            ):
                return False
            remaining = self.image_deadline - time.monotonic()
            if remaining <= 0:
                return False
            service = self.services.get(server)
            host, token = getattr(service, "_host", None), getattr(service, "_apikey", None)
            if not host or not token:
                return False
            self.image_reads[budget_key] = self.image_reads.get(budget_key, 0) + 1
            self.image_reads[key] = self.image_reads.get(key, 0) + 1
            # Read the original image, without resizing or lossy comparison. Never log credentials.
            url = host.rstrip("/") + f"/Items/{item['Id']}/Images/{image_type(target, asset)}/0"
            with requests.get(
                url,
                params={"api_key": token},
                stream=True,
                timeout=(min(5, remaining), min(10, remaining)),
                allow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    return False
                digest, size = hashlib.sha256(), 0
                for chunk in response.iter_content(65536):
                    if self.stop.is_set():
                        raise TaskStopped()
                    if time.monotonic() >= self.image_deadline:
                        return False
                    size += len(chunk)
                    if size > limit:
                        return False
                    digest.update(chunk)
                if (
                    size
                    and digest.hexdigest() == version
                    and hashlib.sha256(local.read_bytes()).hexdigest() == version
                ):
                    self.image_verified.add(key)
                    return True
        except (OSError, requests.RequestException):
            return False
        return False

    def verified(self, updated, record, nfo, images, baseline, locked, server=None):
        target = Target(**record["target"])
        selected_fields = record.get("results", {}).get("nfo", {}).get("changed_fields")
        nfo_ok = not nfo or (
            not locked
            and all(
                not record["local"].get(local)
                or (updated.get(remote) or "").strip() == record["local"][local]
                for local, remote in [("title", "Name"), ("plot", "Overview")]
                if selected_fields is None or local in selected_fields
            )
        )
        if (
            nfo
            and record["local"].get("tagline")
            and (selected_fields is None or "tagline" in selected_fields)
        ):
            taglines = updated.get("Taglines") or []
            if isinstance(taglines, str):
                taglines = [taglines]
            nfo_ok = nfo_ok and record["local"]["tagline"] in [str(t).strip() for t in taglines]
        ids = {k.lower(): str(v) for k, v in updated.get("ProviderIds", {}).items()}
        if nfo and any(ids.get(k) != v for k, v in record["local"].get("ids", {}).items()):
            nfo_ok = False
        images_ok = all(has_image(updated, image_type(target, a)) for a in images)
        if locked:
            return "locked"
        if not nfo_ok or not images_ok:
            return "unimproved"
        tracked = {a for a in images if record.get("results", {}).get(a, {}).get("version")}
        if tracked and (
            server is None
            or not all(
                self.image_matches_version(server, updated, record, a) for a in sorted(tracked)
            )
        ):
            return "unconfirmed"
        if any(
            baseline.get(a) and baseline[a] == self.image_tag(updated, image_type(target, a))
            for a in images - tracked
        ):
            return "unconfirmed"
        return "verified"

    def refresh(self, record, inspector, stop):
        self.stop = stop
        self.image_verified, self.image_reads = set(), {}
        target = Target(**record["target"])
        results = []
        changed = {
            asset for asset, value in record["results"].items() if value["status"] == "repaired"
        }
        for server in self.config.emby_servers:
            if stop.is_set():
                break
            prior = next(
                (
                    s
                    for s in record.get("sync", [])
                    if s.get("server") == server.name and s.get("signature") == record["signature"]
                ),
                {},
            )
            receipt = dict(prior)
            try:
                if prior.get("status") in {"verified", "complete"}:
                    results.append(prior)
                    continue
                located = self.locate(server, record)
                item = self.detail(server.name, located["Id"])
                self.validate_item(server, record, item, expected_id=located["Id"])
                fields, assets = (
                    self.missing(item, record, inspector)
                    if record["emby_mode"] == "compare"
                    else ([], [])
                )
                nfo = prior.get("nfo", "nfo" in changed or bool(fields))
                images = set(prior.get("assets", (changed - {"nfo"}) | set(assets)))
                locked = bool(
                    nfo
                    and (item.get("LockData") or item.get("IsLocked") or item.get("LockedFields"))
                )
                if not nfo and not images:
                    results.append(
                        {
                            "server": server.name,
                            "status": "complete",
                            "signature": record["signature"],
                            "message": "无需刷新",
                        }
                    )
                    continue
                baseline = prior.get(
                    "baseline", {a: self.image_tag(item, image_type(target, a)) for a in images}
                )
                self.image_deadline = time.monotonic() + self.config.emby_timeout
                status = "pending"
                if (
                    prior.get("submitted")
                    or images
                    and all(record.get("results", {}).get(a, {}).get("version") for a in images)
                ):
                    # Verify an existing submission before considering any new write request.
                    status = self.verified(item, record, nfo, images, baseline, locked, server.name)
                if locked and not images:
                    results.append(
                        {
                            "server": server.name,
                            "status": "locked",
                            "signature": record["signature"],
                            "message": "条目存在锁定字段，未刷新文字元数据",
                        }
                    )
                    continue
                if status != "verified" and (not prior.get("submitted") or status == "unimproved"):
                    params = {
                        "Recursive": "false",
                        "MetadataRefreshMode": (
                            "FullRefresh" if nfo and not locked else "ValidationOnly"
                        ),
                        "ImageRefreshMode": "FullRefresh" if images else "ValidationOnly",
                        "ReplaceAllMetadata": "true" if nfo and not locked else "false",
                        "ReplaceAllImages": "false",
                    }
                    receipt = {
                        "server": server.name,
                        "item_id": str(item["Id"]),
                        "status": "submitted",
                        "signature": record["signature"],
                        "submitted": True,
                        "submitted_at": time.time(),
                        "nfo": nfo,
                        "assets": sorted(images),
                        "baseline": baseline,
                    }
                    # Persist intent before POST: a lost response/restart must not cause a blind duplicate.
                    if self.on_submitted:
                        self.on_submitted(receipt)
                    self.request(server.name, "POST", f"Items/{item['Id']}/Refresh", params)
                    status = "submitted"
                deadline = self.image_deadline
                while (
                    status not in {"verified", "locked"}
                    and not stop.is_set()
                    and time.monotonic() < deadline
                ):
                    if stop.wait(min(self.config.emby_poll, max(0, deadline - time.monotonic()))):
                        break
                    updated = self.detail(server.name, item["Id"])
                    self.validate_item(server, record, updated, expected_id=located["Id"])
                    status = self.verified(
                        updated, record, nfo, images, baseline, locked, server.name
                    )
                receipt.update(
                    server=server.name,
                    item_id=str(item["Id"]),
                    signature=record["signature"],
                    status=status,
                    message={
                        "unconfirmed": "图片内容尚未核实为本地提交版本，已保留待同步；重试将先复查",
                        "locked": "条目存在锁定字段，文字元数据未刷新",
                        "unimproved": "已提交版本尚未在 Emby 中确认；再次重试将先复查",
                    }.get(status, ""),
                )
                results.append(receipt)
            except (StorageError, TaskStopped):
                raise
            except Exception as exc:
                results.append(
                    {
                        **receipt,
                        **failure(exc),
                        "server": server.name,
                        "signature": record["signature"],
                    }
                )
        return results
