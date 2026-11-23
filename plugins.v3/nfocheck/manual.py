"""Preview and commit a user-supplied repair for one reported asset."""
import copy
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from xml.dom import Node, minidom
from xml.etree import ElementTree as ET
from xml.parsers.expat import ExpatError

from PIL import Image

from .config import ASSETS
from .core import (IMAGE_EXTS, ROOT_TAGS, Inspector, Target, applicable, digest,
                   fingerprint, identities, image_info, reclassify, within)
from .errors import CandidateRejected, FileConflict, TaskStopped
from .state import item_status


TEXT_FIELDS = ("title", "originaltitle", "sorttitle", "plot", "outline", "tagline")
TMDB_FIELD = "uniqueid[@type='tmdb']"
NFO_LIMIT = 2 * 1024 * 1024
IMAGE_LIMIT = 20 * 1024 * 1024


class ManualProtection(ValueError):
    pass


class _SafeTree(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError("NFO 不支持 DTD 或实体声明")


def xml_root(data):
    try:
        return ET.fromstring(data, parser=ET.XMLParser(target=_SafeTree()))
    except (ET.ParseError, LookupError) as exc:
        raise ValueError("无法读取 NFO XML") from exc


def xml_document(data):
    xml_root(data)
    try:
        return minidom.parseString(data)
    except (ExpatError, LookupError, ValueError) as exc:
        raise ValueError("无法读取 NFO XML") from exc


def children(root, tag):
    if tag == TMDB_FIELD:
        return [node for node in children(root, "uniqueid") if node.getAttribute("type").strip().lower() == "tmdb"]
    return [node for node in root.childNodes if node.nodeType == Node.ELEMENT_NODE and node.tagName == tag]


def tmdb_ids(xml):
    """Read both local representations without allowing one to hide a conflicting ID."""
    typed = [el for el in xml.findall("uniqueid") if (el.get("type") or "").strip().lower() == "tmdb"]
    legacy = xml.findall("tmdbid")
    if len(typed) > 1 or len(legacy) > 1 or any(len(el) for el in typed + legacy):
        raise CandidateRejected("TMDB ID 有重复节点或子元素，无法确定该使用哪一项")
    if typed and typed[0].get("type").lower() != "tmdb":
        raise CandidateRejected("TMDB 节点的 type 属性带有多余空格，请先核对文件")
    primary = (typed[0].text or "").strip() if typed else ""
    compatible = (legacy[0].text or "").strip() if legacy else ""
    for value in (primary, compatible):
        if value and not re.fullmatch(r"[1-9][0-9]*", value):
            raise CandidateRejected("NFO 中已有无效的 TMDB ID，请先核对文件")
    if primary and compatible and primary != compatible:
        raise CandidateRejected("NFO 中的 TMDB 来源 ID 与兼容字段 tmdbid 不一致")
    return primary, compatible


def eligible(result):
    code = result.get("error_code")
    if code in {"file_conflict", "io", "network", "internal", "needs_recheck",
                "identity_unknown", "translation_conflict"}:
        return False
    return (code in {"source_empty", "candidate_rejected", "manual_nfo"}
            or result.get("status") in {"unimproved", "manual", "cooldown"}
            or bool(result.get("translation_pending_fields") or result.get("manual")))


def read_asset(path, limit):
    if path.is_symlink():
        raise FileConflict("文件是符号链接，不能手动替换")
    try:
        with path.open("rb") as source:
            data = source.read(limit + 1)
    except FileNotFoundError:
        return None
    if len(data) > limit:
        raise ValueError(f"文件超过 {limit // (1024 * 1024)} MiB")
    return data


def preserve_manual_nfo(store, path, candidate, *, merge):
    """Preserve confirmed local fields before an automatic NFO write."""
    policy = store.read("manual_nfo", {}).get(str(path))
    if not policy or not path.is_file():
        return candidate
    old = path.read_bytes()
    if candidate == old:
        return candidate
    if hashlib.sha256(old).hexdigest() in policy.get("imports", []):
        raise ManualProtection("当前 NFO 是手动导入的版本，请在手动处理中修改")
    try:
        local = xml_document(old)
        output = xml_document(candidate)
    except ValueError as exc:
        raise ManualProtection("无法保留人工填写的字段，请检查 NFO") from exc
    modified = False
    for field, versions in policy["fields"].items():
        current = children(local.documentElement, field)
        value = "".join(n.data for node in current for n in node.childNodes
                        if n.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE))
        if len(current) != 1 or digest(value) not in versions:
            continue
        if field == TMDB_FIELD:
            try:
                current_xml = xml_root(old)
                candidate_xml = xml_root(candidate)
                tmdb_ids(current_xml)
                tmdb_ids(candidate_xml)
            except ValueError as exc:
                raise ManualProtection(str(exc)) from exc
            known, incoming_ids = identities(current_xml), identities(candidate_xml)
            shared = known.keys() & incoming_ids.keys()
            if not shared:
                raise ManualProtection("候选 NFO 缺少可与本地核对的来源 ID，无法确认属于同一媒体")
            if any(known[name] != incoming_ids[name] for name in shared):
                raise ManualProtection("候选 NFO 的来源 ID 与当前媒体不一致")
        incoming = children(output.documentElement, field)
        if [n.toxml() for n in incoming] == [n.toxml() for n in current]:
            continue
        if not merge:
            raise ManualProtection("翻译候选会覆盖人工填写的字段，请在手动处理中确认")
        for node in incoming:
            output.documentElement.removeChild(node)
        for node in current:
            output.documentElement.appendChild(output.importNode(node, True))
        modified = True
    return output.toxml(encoding="utf-8") if modified else candidate


@dataclass
class Prepared:
    data: bytes
    diff: dict
    remaining: list
    image: dict | None = None
    imported: bool = False


class ManualRepair:
    """Use within the same engine lock for lookup, validation and commit."""

    def __init__(self, engine, run_id, item_id, asset):
        self.engine = engine
        self.asset = asset
        self.report = engine.store.report(run_id)
        self.index = next((i for i, it in enumerate(self.report["items"]) if it["id"] == item_id), None)
        if self.index is None:
            raise ValueError("这条运行记录中没有该条目")
        old = self.report["items"][self.index]
        self.previous = old
        self.config = engine.scoped(self.report["set_ids"])
        original_target = Target(**old["target"])
        if not Path(original_target.media).is_file() or not any(
            applicable(original_target, rs) for rs in self.config.rule_sets
        ):
            raise FileConflict("媒体已移走或不在启用的规则范围内")
        target = reclassify(original_target, engine.source.parse)
        if not target or target.key != item_id or target.classification_error:
            raise FileConflict("媒体层级已变化，请重新巡检")
        self.target = target
        if asset != "nfo" and asset not in ASSETS[target.kind]:
            raise ValueError("此媒体层级不支持该资产")
        result = old.get("results", {}).get(asset, {})
        if not eligible(result):
            raise ValueError("该资产没有需要手动处理的刮削结果")
        self.inspector = Inspector(self.config, translation=engine.translation)
        self.path = target.nfo() if asset == "nfo" else Path(engine.source.destination(
            target, asset, asset + (".png" if asset in {"logo", "clearart", "disc"} else ".jpg")))
        self._check_destination()
        self.expected = fingerprint(self.path)
        self.original = read_asset(self.path, NFO_LIMIT if asset == "nfo" else IMAGE_LIMIT)
        if fingerprint(self.path) != self.expected:
            raise FileConflict("读取时文件发生变化，请重新打开")
        self.current = engine.current_item(old, self.inspector)
        if self.current.get("status") == "excluded" or self.current.get("conflicts") or self.current.get("translation_conflict") and asset == "nfo":
            raise FileConflict("目标不在范围内，或媒体身份、翻译规则存在冲突")
        ignored = engine.store.read_state("ignored").get(item_id, {})
        if ignored and (ignored.get("legacy") or ignored.get("signature") == self.current["ignore_signature"]):
            raise FileConflict("请先取消忽略，再处理这个条目")
        same_rule = (self.current["asset_signatures"].get(asset)
                     and self.current["asset_signatures"].get(asset) == old.get("asset_signatures", {}).get(asset))
        if asset not in self.current["remaining_assets"] and not (same_rule and result.get("translation_pending_fields")):
            raise FileConflict("当前规则已不需要处理该资产，请重新巡检")
        if old.get("needs_recheck") or result.get("error_code") == "needs_recheck":
            raise FileConflict("旧记录的媒体身份尚未确认，请重新巡检")
        previous_ids = old.get("local", {}).get("ids", {})
        current_ids = self.current["local"]["ids"]
        if any(current_ids[k] != v for k, v in previous_ids.items() if k in current_ids):
            raise FileConflict("媒体来源 ID 与巡检记录不一致")
        self.expected_ids = dict(previous_ids)
        self.version = digest([str(self.path), self.expected, self.current["signature"],
                               hashlib.sha256(self.original).hexdigest() if self.original is not None else None])
        self.xml = None
        if asset == "nfo" and self.original:
            try:
                self.xml = xml_root(self.original)
            except ValueError:
                pass

    def _check_destination(self):
        target = self.target
        parents = {target.directory().resolve()}
        if self.asset != "nfo" and target.kind == "season":
            parents.add(Path(target.series).resolve())
        if self.path.parent.resolve() not in parents or self.path.is_symlink():
            raise FileConflict("文件不在该媒体目录内，或是符号链接")
        if self.asset != "nfo" and self.path.suffix.lower() not in IMAGE_EXTS:
            raise FileConflict("未找到受支持的图片目标路径")
        if not any(applicable(target, rs) and any(within(self.path, root) for root in rs.roots)
                   and not any(within(self.path, path) for path in rs.excludes)
                   and not (rs.exclude_regex and re.search(rs.exclude_regex, str(self.path)))
                   for rs in self.config.rule_sets):
            raise FileConflict("文件不在启用的规则范围内")

    def _reasons(self, current):
        return [reason for hit in current["remaining_hits"] if self.asset in hit.get("actions", [])
                and self.asset in hit.get("affected", []) for reason in hit["reasons"]]

    def check_tmdb_id(self, tmdb_id):
        """Validate the operator's ID against the current sidecar, without a remote lookup."""
        if self.asset != "nfo" or self.xml is None or self.xml.tag != ROOT_TAGS[self.target.kind]:
            raise CandidateRejected("请在当前媒体层级的有效 NFO 中补填 TMDB ID")
        value = tmdb_id.strip() if isinstance(tmdb_id, str) else ""
        if not re.fullmatch(r"[1-9][0-9]{0,31}", value):
            raise CandidateRejected("请输入 1 到 32 位的 TMDB 正整数编号，例如 12345")
        primary, compatible = tmdb_ids(self.xml)
        if primary:
            raise CandidateRejected("NFO 已有 TMDB 来源 ID，不能在这里覆盖")
        expected = [compatible, self.expected_ids.get("tmdb")]
        if self.target.kind in {"movie", "tv"}:
            expected.extend(re.findall(r"(?i)\{tmdb[-=](\d+)\}", self.target.path))
        conflicts = self.inspector.conflict(self.target, self.xml)
        if conflicts:
            raise CandidateRejected("；".join(conflicts))
        if any(known and str(known) != value for known in expected):
            raise CandidateRejected("填写的 TMDB ID 与文件、路径或巡检记录中的编号不一致")
        return value

    def detail(self):
        fields, blocked, image = {}, [], None
        if self.asset == "nfo":
            for key in TEXT_FIELDS:
                nodes = self.xml.findall(key) if self.xml is not None else []
                if len(nodes) > 1 or any(len(n) for n in nodes):
                    blocked.append(key)
                fields[key] = (nodes[0].text or "") if nodes else ""
            if self.xml is not None and self.xml.tag == ROOT_TAGS[self.target.kind]:
                try:
                    fields[TMDB_FIELD], _ = tmdb_ids(self.xml)
                    if fields[TMDB_FIELD]:
                        blocked.append(TMDB_FIELD)
                except CandidateRejected:
                    fields[TMDB_FIELD] = ""
                    blocked.append(TMDB_FIELD)
        elif self.original:
            try:
                image = image_info(self.original)
            except (ValueError, OSError, SyntaxError, Image.DecompressionBombError):
                image = {"damaged": True}
        return {"asset": self.asset, "path": str(self.path), "kind": self.target.kind, "version": self.version,
                "exists": self.original is not None, "fields": fields, "blocked_fields": blocked,
                "nfo_valid": self.xml is not None and self.xml.tag == ROOT_TAGS[self.target.kind],
                "requirements": self.current["requirements"].get(self.asset, []),
                "reasons": self._reasons(self.current), "image": image}

    def _nfo_rules(self, xml, changed):
        remaining = []
        for rs in self.config.rule_sets:
            if not applicable(self.target, rs):
                continue
            for rule in rs.rules:
                if not rule.enabled or rule.category != "nfo" or rule.action not in {"nfo", "both", "translate", "nfo_translate"}:
                    continue
                hit, why = self.inspector.nfo_matches(self.target, rule, xml, "", candidate=True)
                if not hit:
                    continue
                remaining.extend(why)
                for cond in rule.conditions:
                    if cond.field in changed and cond.op in {"empty", "min_length", "regex"}:
                        single = rule.model_copy(update={"conditions": [cond]})
                        bad, why = self.inspector.nfo_matches(self.target, single, xml, "", candidate=True)
                        if bad:
                            raise CandidateRejected("；".join(why))
        if self.current.get("translation"):
            remaining.append("保存后重新检查字段语言")
        return list(dict.fromkeys(remaining))

    def _check_import_identity(self, xml):
        tmdb_ids(xml)
        expected = dict(self.expected_ids)
        if self.target.kind in {"movie", "tv"}:
            markers = set(re.findall(r"(?i)\{tmdb[-=](\d+)\}", self.target.path))
            if markers:
                if len(markers) != 1 or expected.get("tmdb") and expected["tmdb"] not in markers:
                    raise CandidateRejected("路径标记与巡检记录中的 TMDB ID 不一致")
                expected["tmdb"] = markers.pop()
            if not expected:
                _, info = self.engine.source.resolve(self.target)
                for name in ("tmdb", "imdb", "tvdb", "douban", "bangumi"):
                    value = getattr(info, name + "_id", None)
                    if value:
                        expected[name] = str(value)
        else:
            numbers = {"seasonnumber": self.target.season} if self.target.kind == "season" else {
                "season": self.target.season, "episode": self.target.episode}
            if any(number is None or (xml.findtext(tag) or "").strip() != str(number)
                   for tag, number in numbers.items()):
                raise CandidateRejected("导入 NFO 的季集编号缺失或不一致")
            # A series ID cannot establish the identity of an episode/season NFO.
            if not expected:
                for candidate in self.engine.candidates(self.target, "nfo"):
                    if isinstance(candidate, Exception):
                        continue
                    _, content = candidate
                    try:
                        source = xml_root(content) if len(content) <= NFO_LIMIT else None
                        if source is not None:
                            tmdb_ids(source)
                    except ValueError:
                        continue
                    if source is not None and source.tag == xml.tag and all(
                        (source.findtext(tag) or "").strip() == str(num) for tag, num in numbers.items()
                    ):
                        expected = identities(source)
                        if expected:
                            break
        incoming = identities(xml)
        if not expected.keys() & incoming.keys():
            raise CandidateRejected("无法从来源 ID 确认导入文件属于该媒体")
        if any(incoming[k] != expected[k] for k in expected.keys() & incoming.keys()):
            raise CandidateRejected("导入 NFO 的来源 ID 与当前媒体不一致")

    def prepare(self, expected_version, fields=None, content=None):
        if expected_version != self.version:
            raise FileConflict("文件或命中规则已变化，请重新打开后再修改")
        if (fields is None) == (content is None):
            raise ValueError("请选择一种修改方式")
        if self.asset != "nfo":
            if not content or fields is not None or len(content) > IMAGE_LIMIT:
                raise ValueError("请选择 20 MiB 以内的图片")
            self.engine.validate_candidate(self.target, self.asset, content, self.current, self.inspector)
            data = self.engine.encode_image(self.path, content)
            if len(data) > IMAGE_LIMIT:
                raise ValueError("转换后的图片超过 20 MiB")
            return Prepared(data, {}, [], image_info(data))
        valid = self.xml is not None and self.xml.tag == ROOT_TAGS[self.target.kind]
        diff = {}
        if fields is not None:
            if not valid:
                raise ValueError("原 NFO 缺失或损坏，请导入完整文件")
            if not fields or set(fields) - {*TEXT_FIELDS, TMDB_FIELD}:
                raise ValueError("包含不支持的 NFO 字段")
            document = xml_document(self.original)
            root = document.documentElement
            for key, value in fields.items():
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("请输入非空字段值")
                nodes = children(root, key)
                if len(nodes) > 1 or any(n.nodeType == Node.ELEMENT_NODE for el in nodes for n in el.childNodes):
                    raise ValueError(f"{key} 有重复项或子元素，不能作为单值修改")
                if key == TMDB_FIELD:
                    value = self.check_tmdb_id(value)
                before = self.xml.findtext(key, "")
                if before == value:
                    continue
                tag = "uniqueid" if key == TMDB_FIELD else key
                node = nodes[0] if nodes else root.appendChild(document.createElement(tag))
                if key == TMDB_FIELD:
                    node.setAttribute("type", "tmdb")
                for child in list(node.childNodes):
                    if child.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
                        node.removeChild(child)
                node.appendChild(document.createTextNode(value))
                diff[key] = {"before": before, "after": value}
            data = document.toxml(encoding="utf-8") if diff else self.original
        else:
            if valid:
                raise ValueError("已有有效 NFO，请按字段修改")
            data = content
        if not data or len(data) > NFO_LIMIT:
            raise ValueError("请选择 2 MiB 以内的 NFO")
        xml = xml_root(data)
        if xml.tag != ROOT_TAGS[self.target.kind]:
            raise CandidateRejected("NFO 根元素与当前媒体层级不符")
        conflicts = self.inspector.conflict(self.target, xml)
        if conflicts:
            raise CandidateRejected("；".join(conflicts))
        if fields is None:
            self._check_import_identity(xml)
        return Prepared(data, diff, self._nfo_rules(xml, diff), imported=fields is None)

    def preview(self, prepared):
        return {"changed": self.original != prepared.data, "fields": prepared.diff,
                "remaining_reasons": prepared.remaining, "image": prepared.image}

    def save(self, prepared):
        if not self.engine.config.enabled:
            raise ValueError("请先启用修复")
        if self.engine.stop.is_set():
            raise TaskStopped()
        latest = self.engine.current_item(self.previous, self.inspector)
        if latest.get("status") == "excluded" or latest["signature"] != self.current["signature"]:
            raise FileConflict("媒体或规则已变化，请重新打开")
        if not latest["stable"]:
            raise FileConflict("媒体或旁挂文件仍在变化，请等待文件稳定后重试")
        self._check_destination()
        engine, report = self.engine, self.report
        saved_hash = hashlib.sha256(prepared.data).hexdigest()
        response = self.preview(prepared)
        limit = NFO_LIMIT if self.asset == "nfo" else IMAGE_LIMIT
        if fingerprint(self.path) != self.expected or read_asset(self.path, limit) != self.original:
            raise FileConflict("文件发生变化，请重新打开")
        if not response["changed"]:
            return {**response, "sync": [], "run_id": report["id"], "_queued_keys": set(), "message": "内容相同，文件没有变化"}
        if self.asset == "nfo":
            # Persist protection before publishing the file, including a crash between the two writes.
            policies = engine.store.read("manual_nfo", {})
            previous = policies.get(str(self.path), {})
            policy = copy.deepcopy(previous) or {"fields": {}, "imports": []}
            for key, diff in prepared.diff.items():
                versions = policy["fields"].setdefault(key, [])
                checksum = digest(diff["after"])
                if checksum not in versions:
                    versions.append(checksum)
            old_hash = hashlib.sha256(self.original).hexdigest() if self.original is not None else None
            if prepared.imported or old_hash in policy["imports"]:
                if saved_hash not in policy["imports"]:
                    policy["imports"].append(saved_hash)
            policies[str(self.path)] = policy
            engine.store.write("manual_nfo", policies)
        try:
            backup, changed = engine.store.commit(self.path, prepared.data, self.asset, self.config.backup,
                                                   report["id"], self.expected,
                                                   {"target": self.current["target"], "set_ids": report["set_ids"]})
        except Exception:
            if self.asset == "nfo" and read_asset(self.path, NFO_LIMIT) != prepared.data:
                if previous:
                    policies[str(self.path)] = previous
                else:
                    policies.pop(str(self.path), None)
                engine.store.write("manual_nfo", policies)
            raise
        if read_asset(self.path, NFO_LIMIT if self.asset == "nfo" else IMAGE_LIMIT) != prepared.data:
            raise FileConflict("保存后文件已被其他任务修改，请重新巡检")
        engine.translation.cache.clear()
        self.inspector.invalidate(self.path)
        fresh = self.inspector.inspect(self.target)
        if not fresh:
            raise FileConflict("文件已写入，复查时条目已离开巡检范围")
        remaining = self._reasons(fresh)
        previous_result = self.previous.get("results", {}).get(self.asset, {})
        pending_fields = []
        if self.asset == "nfo" and self.current.get("translation") and not prepared.imported:
            pending_fields = [field for field in previous_result.get("translation_pending_fields", [])
                              if field not in prepared.diff]
            if pending_fields:
                fresh["translation"] = fresh.get("translation") or self.current["translation"]
                remaining.append("仍有待处理的翻译字段：" + "、".join(pending_fields))
        result = {"status": "repaired" if changed else "unchanged", "manual": True, "path": str(self.path),
                  "backup_id": backup, "version": saved_hash, "file_signature": fingerprint(self.path),
                  "attempted_at": time.time(), "details": {"remaining_reasons": remaining},
                  "message": "已手动保存，仍有规则命中" if remaining else "已手动保存"}
        if self.asset == "nfo" and not prepared.imported:
            result["changed_fields"] = list(prepared.diff)
            if pending_fields:
                result["translation_pending_fields"] = pending_fields
            if not set(prepared.diff) & {"title", "plot", "tagline"}:
                result["message"] += "；这些字段仅保存到本地 NFO"
        if not previous_result.get("manual"):
            result["details"]["previous_result"] = {k: previous_result[k] for k in ("status", "error_code", "message") if k in previous_result}
        else:
            result["details"]["previous_result"] = previous_result.get("details", {}).get("previous_result", {})
        fresh["results"] = {**self.previous.get("results", {}), self.asset: result}
        fresh["sync"] = copy.deepcopy(self.previous.get("sync", []))
        fresh["hits"] = self.previous.get("hits", fresh["hits"])
        fresh["actions"] = sorted(set(self.previous.get("actions", [])) | set(fresh["actions"]))
        outstanding = set(self.current["remaining_assets"]) | set(fresh["remaining_assets"])
        completed = set(self.current.get("completed_assets", []))
        if not remaining:
            completed.add(self.asset)
        for asset in completed:
            record = fresh["results"][asset]
            if asset in fresh["asset_signatures"] and fingerprint(record["path"]) == record.get("file_signature"):
                record["completed_signature"] = fresh["asset_signatures"][asset]
                outstanding.discard(asset)
        fresh["completed_assets"] = sorted(completed - outstanding)
        fresh["remaining_assets"] = sorted(outstanding)
        owned = {v["path"] for v in fresh["results"].values() if v.get("path") and v.get("file_signature")
                 and v["file_signature"] == fresh["files"].get(v["path"]) and v["status"] in {"repaired", "unchanged"}}
        fresh["stable"] = all(path in owned or sig is None or time.time() - sig[0] / 1e9 >= self.config.stable_seconds
                              for path, sig in fresh["files"].items())
        fresh["status"] = item_status(fresh)
        report["items"][self.index] = fresh
        report["dry_run"] = False
        attempts = engine.store.read_state("attempts")
        attempts[fresh["id"] + ":" + self.asset] = {
            "signature": fresh["asset_signatures"].get(self.asset), "count": 0, "next": 0,
            "target": fresh["target"], "run_id": report["id"], "result": result,
            "resume": {k: fresh.get(k) for k in ("remaining_assets", "asset_signatures", "completed_assets", "translation", "translation_conflict")}}
        engine.store.write_state("attempts", attempts)
        scoped_item = {**fresh, "results": {self.asset: result}, "emby_mode": "off" if fresh["emby_mode"] == "off" else "changed"}
        keys = engine.queue_sync(scoped_item, report, self.config, manual_asset=self.asset) if changed else set()
        fresh["sync"] = scoped_item["sync"]
        if any(sync.get("message") == "该条目另有待同步内容，请在待同步页一起重试" for sync in fresh["sync"]):
            result["message"] += "；该条目另有待同步内容，请在待同步页一起重试"
        fresh["status"] = item_status(fresh)
        engine.store.prune_backups(self.config.backup)
        engine.done(report, "batch_limit" if report.get("exit_reason") == "batch_limit" else "completed")
        return {"changed": changed, "remaining_reasons": remaining, "sync": fresh["sync"], "_queued_keys": keys,
                "run_id": report["id"], "message": result["message"]}
