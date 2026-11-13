"""Local inspection. No MoviePilot imports, network access or media writes."""

import hashlib
import io
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

from .config import ASSETS, Config
from .errors import TaskStopped
from .fields import FIELD_LABELS

VIDEO_EXTS = {
    ".strm",
    ".mkv",
    ".mp4",
    ".avi",
    ".mov",
    ".ts",
    ".m2ts",
    ".wmv",
    ".iso",
    ".mpg",
    ".mpeg",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tbn"}
ALIASES = {
    "poster": ["poster", "folder"],
    "backdrop": ["backdrop", "fanart", "background"],
    "logo": ["logo", "clearlogo"],
    "disc": ["disc", "cdart"],
    "banner": ["banner"],
    "thumb": ["thumb", "landscape"],
    "landscape": ["landscape", "thumb"],
    "clearart": ["clearart"],
}
ROOT_TAGS = {"movie": "movie", "tv": "tvshow", "season": "season", "episode": "episodedetails"}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def within(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def fingerprint(path):
    try:
        st = Path(path).stat()
        return [st.st_mtime_ns, st.st_size, st.st_ino]
    except FileNotFoundError:
        return None


def parse_nfo(data):
    if len(data) > 8 * 1024 * 1024 or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("不支持包含 DTD/实体或超过 8 MiB 的 NFO")
    return ET.fromstring(data)


def identities(xml):
    if xml is None:
        return {}
    values = {}
    for el in xml.findall("uniqueid"):
        key = (el.get("type") or "").lower()
        if key and (el.text or "").strip():
            values[key] = el.text.strip()
    for name in ["tmdb", "imdb", "tvdb", "douban", "bangumi"]:
        value = (xml.findtext(name + "id") or "").strip()
        if value:
            values.setdefault(name, value)
    return {
        k: v
        for k, v in values.items()
        if v.lower() not in {"none", "null", "0", "unknown"}
        and (k not in {"tmdb", "tvdb", "douban", "bangumi"} or (v.isdigit() and int(v) > 0))
    }


@dataclass
class Target:
    path: str
    kind: str
    root: str
    media: str
    series: str = ""
    season: int | None = None
    episode: int | None = None
    classification_error: str = ""

    @property
    def key(self):
        return digest([self.path, self.kind])[:24]

    def nfo(self):
        p = Path(self.path)
        if self.kind in {"tv", "season"}:
            return p / ("tvshow.nfo" if self.kind == "tv" else "season.nfo")
        candidates = [p.with_suffix(".nfo")]
        if self.kind == "movie":
            candidates += [p.parent / "movie.nfo", p.parent / (p.parent.name + ".nfo")]
        return next((c for c in candidates if c.is_file()), candidates[0])

    def directory(self):
        return Path(self.path) if self.kind in {"tv", "season"} else Path(self.path).parent


def fallback_parse(path):
    m = re.search(r"(?i)S(\d+)E(\d+)", path.stem)
    return (int(m[1]), int(m[2])) if m else (None, None)


def classify(path, root, parser=fallback_parse):
    """A parser's guessed episode number alone is not evidence of television."""
    p = Path(path).resolve()
    explicit_season, explicit_episode = fallback_parse(p)
    season_match = re.fullmatch(r"(?i)(?:season\s*|s)(\d+)|specials|特别篇|特典", p.parent.name)
    season_dir = season_match is not None
    series = p.parent.parent if season_dir else p.parent
    series_nfo = False
    try:
        if (series / "tvshow.nfo").is_file():
            series_nfo = parse_nfo((series / "tvshow.nfo").read_bytes()).tag == "tvshow"
    except (OSError, ValueError, ET.ParseError):
        pass
    strong_tv = explicit_episode is not None or season_dir or series_nfo
    probe = Target(str(p), "movie", root, str(p))
    xml = None
    try:
        if probe.nfo().is_file():
            xml = parse_nfo(probe.nfo().read_bytes())
    except (OSError, ValueError, ET.ParseError):
        pass
    xml_kind = xml.tag if xml is not None else ""
    is_episode = strong_tv or xml_kind == "episodedetails"
    conflict = ""
    if xml_kind == "movie" and strong_tv:
        conflict = "电影 NFO 与明确的剧集路径或 tvshow.nfo 冲突，请人工确认层级"
    if not is_episode:
        return probe
    season, episode = parser(p)
    season = explicit_season if explicit_season is not None else season
    episode = explicit_episode if explicit_episode is not None else episode
    if season_dir:
        folder_season = int(season_match[1]) if season_match[1] else 0
        if season is not None and season != folder_season:
            conflict = "文件季号与季目录冲突，请人工确认"
        season = folder_season
    if xml_kind == "episodedetails":
        for field in ("season", "episode"):
            value = (xml.findtext(field) or "").strip()
            if value.isdigit():
                current = season if field == "season" else episode
                if current is not None and current != int(value):
                    conflict = "NFO 季集号与路径冲突，请人工确认"
                elif field == "season":
                    season = int(value)
                else:
                    episode = int(value)
    if not within(series, root):
        conflict = "剧目录超出规则根目录"
    if season is None or episode is None:
        conflict = conflict or "剧集季集号不完整，请人工确认"
    return Target(str(p), "episode", root, str(p), str(series), season, episode, conflict)


def iter_discover(config: Config, files=None, parser=fallback_parse, stop=None, errors=None):
    """Stream media and deduplicated parents. An explicit [] stays empty."""
    errors = errors if errors is not None else []
    roots = sorted(
        {str(Path(p).resolve()) for s in config.rule_sets if s.enabled for p in s.roots},
        key=len,
        reverse=True,
    )
    seen, emitted = set(), set()

    def cancelled():
        if stop is not None and stop.is_set():
            raise TaskStopped()

    def prunable(directory):
        relevant = [
            s
            for s in config.rule_sets
            if s.enabled and any(within(directory, r) or within(r, directory) for r in s.roots)
        ]
        # A regex matching a parent need not match every descendant; only prefix exclusions prune.
        return bool(relevant) and all(
            any(within(directory, e) for e in s.excludes) for s in relevant
        )

    def walk():
        walked = set()
        for root in roots:
            cancelled()
            if not Path(root).is_dir():
                errors.append(f"目录不存在或不可读：{root}")
                continue

            def onerror(exc):
                errors.append(f"目录读取失败：{exc.filename}")

            for parent, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
                cancelled()
                if parent in walked or prunable(parent):
                    dirs[:] = []
                    continue
                walked.add(parent)
                dirs[:] = [
                    d
                    for d in dirs
                    if not d.startswith((".", "@"))
                    and not d.endswith(".trickplay")
                    and d not in {"#recycle", "$RECYCLE.BIN"}
                    and not prunable(Path(parent) / d)
                ]
                for name in names:
                    cancelled()
                    if Path(name).suffix.lower() in VIDEO_EXTS:
                        yield str(Path(parent) / name)

    for name in walk() if files is None else files:
        cancelled()
        p = Path(name)
        if p.suffix.lower() not in VIDEO_EXTS or not p.is_file():
            continue
        root = next((r for r in roots if within(p, r)), None)
        if not root or str(p.resolve()) in seen:
            continue
        seen.add(str(p.resolve()))
        try:
            t = classify(p, root, parser)
        except (OSError, ValueError) as exc:
            errors.append(f"无法判断媒体层级：{p}：{exc}")
            continue
        targets = [t]
        if t.kind == "episode" and not t.classification_error:
            targets.append(Target(t.series, "tv", root, t.media, t.series))
            if Path(t.path).parent != Path(t.series):
                targets.append(
                    Target(str(Path(t.path).parent), "season", root, t.media, t.series, t.season)
                )
        for target in targets:
            if target.key not in emitted:
                emitted.add(target.key)
                yield target


def discover(config: Config, files=None, parser=fallback_parse):
    errors = []
    return list(iter_discover(config, files, parser, errors=errors)), errors


def reclassify(target, parser=fallback_parse):
    """Recheck old reports without deleting false parent objects from the filesystem."""
    current = classify(target.media, target.root, parser)
    if target.kind in {"movie", "episode"}:
        return current
    if current.kind != "episode" or current.classification_error:
        return None
    if target.kind == "tv" and current.series == target.path:
        return Target(target.path, "tv", target.root, target.media, current.series)
    if target.kind == "season" and str(Path(current.path).parent) == target.path:
        return Target(
            target.path, "season", target.root, target.media, current.series, current.season
        )
    return None


def applicable(target, ruleset):
    return (
        ruleset.enabled
        and target.kind in ruleset.kinds
        and any(within(target.path, root) for root in ruleset.roots)
        and not any(within(target.path, p) for p in ruleset.excludes)
        and not (ruleset.exclude_regex and re.search(ruleset.exclude_regex, target.path))
        and not (ruleset.exclude_season_zero and target.season == 0)
    )


def image_candidates(target, asset, listing=None):
    listing = listing or (lambda directory: Path(directory).iterdir())
    directory = target.directory()
    stem = Path(target.path).stem
    aliases = ALIASES[asset]
    if target.kind == "episode":
        stems = {stem.lower(), (stem + "-thumb").lower(), (stem + "-poster").lower()}
    else:
        stems = set(aliases)
        if target.kind == "movie":
            stems.update((stem + "-" + a).lower() for a in aliases)
    candidates = [
        p for p in listing(directory) if p.suffix.lower() in IMAGE_EXTS and p.stem.lower() in stems
    ]
    if target.kind == "movie":
        specific = [p for p in candidates if p.stem.lower().startswith(stem.lower() + "-")]
        if specific:
            candidates = specific
    if target.kind == "season" and target.season is not None:
        prefixes = [f"season{target.season:02d}", f"season{target.season}"]
        if target.season == 0:
            prefixes += ["season-specials"]
        names = {f"{prefix}-{a}" for prefix in prefixes for a in aliases}
        candidates += [
            p
            for p in listing(Path(target.series))
            if p.suffix.lower() in IMAGE_EXTS and p.stem.lower() in names
        ]
    return sorted(set(candidates))


def image_info(data):
    with Image.open(io.BytesIO(data)) as img:
        img.verify()
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        return {"width": img.width, "height": img.height, "format": img.format}


class Inspector:
    def __init__(self, config, cache=None, translation=None):
        self.config = config
        self.cache = cache if cache is not None else {}
        self._xml = {}
        self._directories = {}
        self.translation = translation

    def listing(self, directory):
        key = str(directory)
        sig = fingerprint(directory)
        cached = self._directories.get(key)
        if cached is None or cached[0] != sig:
            cached = (sig, list(Path(directory).iterdir()))
            self._directories[key] = cached
        return cached[1]

    def candidates(self, target, asset):
        return image_candidates(target, asset, self.listing)

    def invalidate(self, path):
        self._xml.pop(str(path), None)
        self.cache.pop(str(path), None)
        self._directories.pop(str(Path(path).parent), None)

    def xml(self, path):
        key = str(path)
        sig = fingerprint(path)
        parsed = self._xml.get(key)
        if parsed and parsed[0] == sig:
            return parsed[1], parsed[2]
        cached = self.cache.get(key)
        if cached and cached["signature"] == sig:
            text = cached.get("xml")
            root, error = ET.fromstring(text) if text else None, cached.get("error", "")
            self._xml[key] = (sig, root, error)
            return root, error
        root, error = None, ""
        if sig is not None:
            try:
                root = parse_nfo(Path(path).read_bytes())
            except (ET.ParseError, ValueError, OSError) as exc:
                error = str(exc)
        self.cache[key] = {
            "signature": sig,
            "xml": ET.tostring(root, encoding="unicode") if root is not None else None,
            "error": error,
        }
        self._xml[key] = (sig, root, error)
        return root, error

    def image(self, path):
        key = str(path)
        sig = fingerprint(path)
        cached = self.cache.get(key)
        if cached and cached["signature"] == sig and "image" in cached:
            return cached["image"]
        try:
            info = image_info(Path(path).read_bytes())
        except (OSError, ValueError, Image.DecompressionBombError):
            info = {"damaged": True}
        self.cache[key] = {"signature": sig, "image": info}
        return info

    def conflict(self, target, xml):
        if xml is None:
            return []
        reasons = []
        if target.kind in {"episode", "season"}:
            for name, expected in [("season", target.season), ("episode", target.episode)]:
                actual = (
                    xml.findtext(
                        "seasonnumber" if target.kind == "season" and name == "season" else name
                    )
                    or ""
                ).strip()
                if actual and expected is not None and actual != str(expected):
                    reasons.append(f"{name} 与文件路径不一致")
        # Episode unique IDs identify the episode, not the series: never compare them to series IDs.
        if target.kind in {"movie", "tv"}:
            m = re.search(r"(?i)\{tmdb[-=](\d+)\}", target.path)
            local_id = identities(xml).get("tmdb")
            if m and local_id and m[1] != local_id:
                reasons.append("NFO TMDB ID 与路径标记冲突")
        return reasons

    def nfo_matches(self, target, rule, xml, error, candidate=False):
        results = []
        for cond in rule.conditions:
            if cond.op.startswith("language_"):
                if candidate:
                    continue  # Translation completion is validated per field, after NFO validation.
                hit, detail = (
                    self.translation.match(target, rule, cond)
                    if self.translation
                    else (True, {"message": "翻译服务不可用"})
                )
                names = {
                    "language_missing": "目标语言内容缺失",
                    "language_mismatch": "字段非目标语言",
                    "language_unknown": "语言无法确认",
                }
                results.append(
                    (
                        hit,
                        f"{FIELD_LABELS.get(cond.field, cond.field)}：{names[cond.op]}"
                        + ("；" + detail["message"] if detail.get("message") else ""),
                    )
                )
                continue
            values = (
                ["".join(e.itertext()).strip() for e in xml.findall(cond.field)]
                if xml is not None
                else []
            )
            text = " ".join(v for v in values if v)
            if cond.op == "missing":
                match = not candidate and not target.nfo().exists()
            elif cond.op == "invalid":
                match = bool(error) or (xml is not None and xml.tag != ROOT_TAGS[target.kind])
            elif cond.op == "empty":
                match = not text
            elif cond.op == "min_length":
                match = len(text) < int(cond.value)
            elif cond.op == "identity_missing":
                match = not identities(xml)
            elif cond.op == "conflict":
                match = bool(self.conflict(target, xml))
            else:
                match = bool(text and re.search(cond.value, text))
            descriptions = {
                "missing": "NFO 不存在",
                "invalid": "XML 损坏或根元素错误",
                "empty": "字段缺失或为空",
                "min_length": "字段长度小于 " + cond.value,
                "regex": "字段匹配正则",
                "identity_missing": "媒体来源 ID 缺失",
                "conflict": "身份／季集号冲突",
            }
            reason = descriptions[cond.op]
            if cond.op in {"empty", "min_length", "regex"}:
                reason = f"{FIELD_LABELS.get(cond.field, cond.field)}：{reason}"
            results.append((match, reason))
        hit = bool(results) and (
            all(r[0] for r in results) if rule.match == "all" else any(r[0] for r in results)
        )
        return hit, [r[1] for r in results if r[0]]

    def image_matches(self, target, check):
        files = self.candidates(target, check.type)
        if not files:
            return check.missing, "文件缺失", []
        issues = []
        for path in files:
            info = self.image(path)
            if info.get("damaged"):
                bad = check.damaged or check.min_width > 0 or check.min_height > 0
                reason = "图片损坏"
            else:
                bad = info["width"] < check.min_width or info["height"] < check.min_height
                reason = f"尺寸 {info['width']}×{info['height']} 不足"
            if not bad:
                return False, "", files
            issues.append(reason)
        return True, "; ".join(sorted(set(issues))), files

    def inspect(self, target):
        sets = [s for s in self.config.rule_sets if applicable(target, s)]
        if not sets:
            return None
        xml, error = self.xml(target.nfo())
        conflicts = self.conflict(target, xml)
        if target.classification_error:
            conflicts.append(target.classification_error)
        hits, actions, requirements = [], set(), {}
        translation_rules = []
        emby_mode = "off"
        files = {
            str(target.nfo()): fingerprint(target.nfo()),
            str(Path(target.media)): fingerprint(target.media),
        }
        for ruleset in sets:
            if ruleset.emby == "compare" or (ruleset.emby == "changed" and emby_mode == "off"):
                emby_mode = ruleset.emby
            for rule in ruleset.rules:
                if not rule.enabled:
                    continue
                image_hits = []
                if rule.category == "nfo":
                    hit, reasons = self.nfo_matches(target, rule, xml, error)
                    affected = ["nfo"]
                else:
                    checks = [c for c in rule.images if c.type in ASSETS[target.kind]]
                    values, reasons = [], []
                    for check in checks:
                        bad, reason, candidates = self.image_matches(target, check)
                        files.update({str(p): fingerprint(p) for p in candidates})
                        requirements.setdefault(check.type, []).append(check.model_dump())
                        values.append(bad)
                        if bad:
                            image_hits.append(check.type)
                            reasons.append(f"{check.type}: {reason}")
                    hit = bool(values) and (all(values) if rule.match == "all" else any(values))
                    affected = image_hits
                if hit:
                    additions = set()
                    if rule.action in {"nfo", "both", "translate", "nfo_translate"}:
                        additions.add("nfo")
                    if rule.action in {"translate", "nfo_translate"}:
                        translation_rules.append(rule)
                    if rule.action in {"matched_images", "both"}:
                        additions.update(image_hits)
                    if rule.action in {"selected_images", "both"}:
                        additions.update(
                            a for a in rule.selected_images if a in ASSETS[target.kind]
                        )
                    actions.update(additions)
                    hits.append(
                        {
                            "set": ruleset.id,
                            "rule": rule.id,
                            "name": ruleset.name + " / " + rule.name,
                            "reasons": reasons,
                            "affected": affected,
                            "actions": sorted(additions),
                        }
                    )
        if conflicts:
            actions.clear()
        translation_plan, translation_conflict = None, ""
        if translation_rules:
            policies = {r.translation_policy for r in translation_rules}
            if len(policies) > 1:
                translation_conflict = "同一 NFO 命中不同翻译策略，请统一策略后重试"
            translation_plan = {
                "policy": translation_rules[0].translation_policy,
                "fields": sorted({f for r in translation_rules for f in r.translation_fields}),
                "mode": (
                    "generate"
                    if any(r.action == "nfo_translate" for r in translation_rules)
                    or any(
                        r.action in {"nfo", "both"}
                        and any(h["rule"] == r.id and h["set"] == s.id for h in hits)
                        for s in sets
                        for r in s.rules
                    )
                    else "patch"
                ),
            }
        for asset in actions - {"nfo"}:
            files.update({str(p): fingerprint(p) for p in self.candidates(target, asset)})
        # Directory signatures invalidate listings only; sibling writes do not affect
        # stability or retry state.
        semantic = []
        asset_rules = {}
        for ruleset in sets:
            for rule in ruleset.rules:
                if not rule.enabled:
                    continue
                body = rule.model_dump(exclude={"id", "name", "enabled"})
                if rule.action not in {"translate", "nfo_translate"} and not any(
                    c.op.startswith("language_") for c in rule.conditions
                ):
                    body.pop("translation_policy", None)
                    body.pop("translation_fields", None)
                elif self.translation:
                    body["translation_revision"] = self.translation.revision()
                body["conditions"] = sorted(body["conditions"], key=digest)
                body["images"] = sorted(body["images"], key=digest)
                body["selected_images"] = sorted(body["selected_images"])
                semantic.append(body)
                produced = (
                    set(rule.selected_images)
                    if rule.action in {"selected_images", "both"}
                    else set()
                )
                if rule.action in {"nfo", "both", "translate", "nfo_translate"}:
                    produced.add("nfo")
                if rule.action in {"matched_images", "both"}:
                    produced.update(c.type for c in rule.images)
                if rule.action == "report":
                    produced.clear()
                for asset in produced & ({"nfo"} | set(ASSETS[target.kind])):
                    asset_body = dict(body)
                    if (
                        rule.category == "image"
                        and rule.match == "any"
                        and rule.action == "matched_images"
                    ):
                        asset_body["images"] = [
                            check for check in body["images"] if check["type"] == asset
                        ]
                    if rule.action in {"selected_images", "both"}:
                        asset_body["selected_images"] = (
                            [asset] if asset in rule.selected_images else []
                        )
                    asset_rules.setdefault(asset, []).append(asset_body)
        parent_ids = {}
        if target.kind in {"episode", "season"}:
            parent_xml, _ = self.xml(Path(target.series) / "tvshow.nfo")
            parent_ids = identities(parent_xml)
        identity = [identities(xml), parent_ids, target.kind, target.season, target.episode]
        asset_signatures = {}
        for asset in asset_rules:
            paths = [target.nfo()] if asset == "nfo" else self.candidates(target, asset)
            dependencies = {str(p): fingerprint(p) for p in paths}
            files.update(dependencies)
            # Include the condition's inputs when it triggers a different asset's update.
            for body in asset_rules.get(asset, []):
                if body["category"] == "nfo":
                    dependencies[str(target.nfo())] = fingerprint(target.nfo())
                else:
                    for check in body["images"]:
                        if check["type"] in ASSETS[target.kind]:
                            dependencies.update(
                                {
                                    str(p): fingerprint(p)
                                    for p in self.candidates(target, check["type"])
                                }
                            )
            asset_signatures[asset] = digest(
                [
                    dependencies,
                    identity,
                    sorted(
                        {digest(body): body for body in asset_rules.get(asset, [])}.values(),
                        key=digest,
                    ),
                ]
            )
        signature = digest(
            [
                files,
                identity,
                sorted({digest(body): body for body in semantic}.values(), key=digest),
            ]
        )
        stable = all(
            sig is None or time.time() - sig[0] / 1e9 >= self.config.stable_seconds
            for sig in files.values()
        )
        # Kept only for one-time matching of old state, never used for new retry decisions.
        legacy_files = dict(files)
        legacy_files[str(target.directory())] = fingerprint(target.directory())
        if target.kind == "season":
            legacy_files[target.series] = fingerprint(target.series)
        return {
            "id": target.key,
            "target": asdict(target),
            "hits": hits,
            "remaining_hits": hits,
            "translation": translation_plan,
            "translation_conflict": translation_conflict,
            "actions": sorted(actions),
            "remaining_assets": sorted(actions),
            "conflicts": conflicts,
            "stable": stable,
            "status": (
                "manual"
                if conflicts
                else (
                    "unstable"
                    if not stable
                    else "pending" if actions else "report" if hits else "complete"
                )
            ),
            "signature": signature,
            "ignore_signature": signature,
            "asset_signatures": asset_signatures,
            "legacy_signature": digest([legacy_files, [s.model_dump() for s in sets]]),
            "files": files,
            "requirements": requirements,
            "emby_mode": emby_mode,
            "results": {},
            "sync": [],
            "local": {
                "title": xml.findtext("title", "").strip() if xml is not None else "",
                "plot": xml.findtext("plot", "").strip() if xml is not None else "",
                "tagline": xml.findtext("tagline", "").strip() if xml is not None else "",
                "ids": identities(xml),
            },
        }
