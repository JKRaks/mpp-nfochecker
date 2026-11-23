"""The only MoviePilot scraping compatibility boundary; never changes host policy."""
from copy import copy
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from requests.exceptions import RequestException
from .core import ALIASES, ROOT_TAGS, image_candidates, identities, parse_nfo, fingerprint
from .errors import SourceUnavailable, TaskStopped


def _nfo_tmdb_id(xml):
    from .manual import tmdb_ids
    primary, compatible = tmdb_ids(xml)
    return primary or compatible


def _series_tmdb_id(target):
    if not target.series:
        raise SourceUnavailable("缺少所属剧目录，无法按季集查询 TMDB")
    series = Path(target.series)
    ids = set(re.findall(r"\{tmdb[-=]([1-9][0-9]*)\}", series.name, re.I))
    try:
        xml = parse_nfo((series / "tvshow.nfo").read_bytes())
    except (FileNotFoundError, ValueError, ET.ParseError):
        xml = None
    if xml is not None and xml.tag == "tvshow":
        series_id = _nfo_tmdb_id(xml)
        if series_id:
            ids.add(series_id)
    if len(ids) > 1:
        raise SourceUnavailable("所属剧的目录标记与 tvshow.nfo 中的 TMDB ID 存在冲突")
    if not ids:
        raise SourceUnavailable("请先在所属剧的 tvshow.nfo 或剧目录名中提供剧的 TMDB ID")
    return ids.pop()


class MoviePilotSource:
    def __init__(self):
        from app.chain.media import MediaChain
        from app.chain.scraping import ScrapingChain
        self.media = MediaChain()
        self.scraper = ScrapingChain()
        self.begin_run()

    def begin_run(self):
        self._contexts = {}
        self._images_ready = set()

    @staticmethod
    def parse(path):
        from app.sdk.media import MetaInfoPath
        meta = MetaInfoPath(path)
        return meta.begin_season, meta.begin_episode

    def resolve(self, target, images=False):
        cache_key = (target.key, target.season, target.episode,
                     tuple(fingerprint(Path(target.series) / "tvshow.nfo") or []) if target.series else ())
        if cache_key in self._contexts:
            meta, info = self._contexts[cache_key]
            if images and cache_key not in self._images_ready:
                self.media.obtain_images(info)
                self._images_ready.add(cache_key)
            return meta, info
        from app.sdk.media import MetaInfoPath, normalize_media_source
        from app.schemas.types import MediaType
        meta = MetaInfoPath(Path(target.media if target.kind in {"episode", "season"} else target.path))
        meta.type = MediaType.MOVIE if target.kind == "movie" else MediaType.TV
        # IDs in episode/season NFOs can be episode/season IDs. Use the parent series identity.
        identity_path = Path(target.series) / "tvshow.nfo" if target.kind in {"season", "episode"} else target.nfo()
        ids = {}
        if identity_path.is_file():
            try:
                ids = identities(parse_nfo(identity_path.read_bytes()))
            except (ValueError, ET.ParseError):
                pass  # Invalid NFO is a supported repair case; recognize using the path.
        info = None
        for name in ["tmdb", "douban", "bangumi", "imdb", "tvdb"]:
            if name not in ids:
                continue
            source = normalize_media_source(name)
            if source:
                info = self.media.recognize_media(meta=meta, media_source=source, media_id=ids[name])
                break
        if info is None:
            path = target.series if target.kind in {"season", "episode"} else target.path
            context = self.media.recognize_by_path(str(path))
            info = context.media_info if context else None
        if info is None:
            raise SourceUnavailable("官方识别未找到媒体身份")
        if target.kind in {"season", "episode"}:
            from app.sdk.media import resolve_media_identity
            source, media_id = resolve_media_identity(media=info)
            info = self.media.recognize_media(meta=meta, media_source=source, media_id=media_id,
                                             episode_group=getattr(info, "episode_group", None))
            if info is None:
                raise SourceUnavailable("官方识别未找到季集信息")
        if images:
            self.media.obtain_images(info)
            self._images_ready.add(cache_key)
        self._contexts[cache_key] = (meta, info)
        return meta, info

    def candidates(self, target, assets):
        """Compatibility helper. Workers consume iter_candidates lazily."""
        import threading
        result = {}
        for asset in assets:
            result[asset] = []
            for candidate in self.iter_candidates(target, asset, threading.Event()):
                if isinstance(candidate, Exception):
                    raise candidate
                result[asset].append(candidate)
        return result

    def iter_tmdb_nfo(self, target, tmdb_id: str, stop):
        """Look up an explicitly selected identity without using the current run's recognition."""
        from app.sdk.media import MetaInfoPath, normalize_media_source, resolve_media_identity
        from app.schemas.types import MediaType

        if stop.is_set():
            raise TaskStopped()
        if not re.fullmatch(r"[1-9][0-9]*", tmdb_id) or target.kind not in ROOT_TAGS:
            raise ValueError("请为当前媒体填写有效的 TMDB ID")
        nested = target.kind in {"season", "episode"}
        numbers = {}
        if nested:
            numbers = {"seasonnumber": target.season} if target.kind == "season" else {
                "season": target.season, "episode": target.episode}
            if None in numbers.values():
                raise SourceUnavailable("无法确定当前条目的季集编号")
        lookup_id = _series_tmdb_id(target) if nested else tmdb_id
        source = normalize_media_source("tmdb")
        if not source:
            raise SourceUnavailable("MoviePilot 无法识别 TMDB 来源")
        media_type = MediaType.MOVIE if target.kind == "movie" else MediaType.TV
        info = self.media.recognize_media(mtype=media_type, media_source=source, media_id=lookup_id, cache=False)
        if not info or info.type != media_type:
            raise SourceUnavailable("TMDB 没有返回该类型的媒体")
        actual_source, actual_id = resolve_media_identity(media=info)
        if actual_source != source or str(actual_id) != lookup_id:
            raise SourceUnavailable("MoviePilot 返回的媒体来源或 ID 与本次查询不一致")
        if stop.is_set():
            raise TaskStopped()
        meta = MetaInfoPath(Path(target.media if nested else target.path))
        meta.type = media_type
        info = copy(info)
        info.scrape_source = source
        content = self.scraper.metadata_nfo(meta=meta, mediainfo=info, season=target.season, episode=target.episode)
        if stop.is_set():
            raise TaskStopped()
        if not content:
            raise SourceUnavailable("TMDB 没有提供该条目的 NFO")
        data = content.encode("utf-8")
        try:
            xml = parse_nfo(data)
        except (ValueError, ET.ParseError) as exc:
            raise SourceUnavailable("TMDB 返回的 NFO 无法读取") from exc
        if xml.tag != ROOT_TAGS[target.kind]:
            raise SourceUnavailable("返回的 NFO 媒体层级不符")
        if any((xml.findtext(tag) or "").strip() != str(number) for tag, number in numbers.items()):
            raise SourceUnavailable("返回的 NFO 季集编号与当前条目不符")
        candidate_id = _nfo_tmdb_id(xml)
        if target.kind == "season" and not candidate_id:
            # MoviePilot writes seasonnumber but omits the season's own ID from a TMDB season NFO.
            if getattr(info, "episode_group", None):
                raise SourceUnavailable("分集组的季编号经过重排，缺少可以核对的 TMDB 季 ID")
            tmdb_info = getattr(info, "tmdb_info", None) or {}
            seasons = tmdb_info.get("seasons") or []
            season_ids = [str(row.get("id")) for row in seasons
                          if isinstance(row, dict) and row.get("season_number") == target.season]
            if season_ids != [tmdb_id]:
                raise SourceUnavailable("TMDB 返回的当前季详情与填写的季 ID 不符，或缺少季 ID")
            node = next((el for el in xml.findall("uniqueid")
                         if (el.get("type") or "").strip().lower() == "tmdb"), None)
            if node is None:
                node = ET.SubElement(xml, "uniqueid", {"type": "tmdb"})
            node.text = tmdb_id
            data = ET.tostring(xml, encoding="utf-8", xml_declaration=True)
        elif candidate_id != tmdb_id:
            raise SourceUnavailable("返回的 NFO 未包含当前媒体层级的指定 TMDB ID")
        yield target.nfo(), data

    def iter_candidates(self, target, asset, stop):
        from app.sdk.network import RequestUtils
        from app.sdk.config import settings
        if stop.is_set():
            raise TaskStopped()
        meta, info = self.resolve(target, asset != "nfo")
        if stop.is_set():
            raise TaskStopped()
        kwargs = {"season": target.season, "episode": target.episode}
        if asset == "nfo":
            content = self.scraper.metadata_nfo(meta=meta, mediainfo=info, **kwargs)
            if content:
                yield target.nfo(), content.encode("utf-8")
            return
        images = self.scraper.metadata_img(mediainfo=info, **kwargs) or {}
        for name, url in images.items():
            if stop.is_set():
                raise TaskStopped()
            stem = Path(name).stem.lower()
            if target.kind == "season":
                stem = __import__("re").sub(r"^season(?:\d+|-specials)-", "", stem)
            accepted = ALIASES[asset] + (["episode-thumb"] if target.kind == "episode" else [])
            if stem not in accepted:
                continue
            if target.kind == "season" and name.lower().startswith("season"):
                from app.schemas.types import ScrapingTarget
                if not self.scraper._matches_image_season(name, ScrapingTarget.SEASON, target.season):
                    continue
            try:
                response = RequestUtils(proxies=settings.PROXY, timeout=30).get_res(url=str(url))
                if response is None:
                    raise ConnectionError("图片来源请求失败")
                try:
                    if response.status_code != 200:
                        raise ConnectionError(f"图片来源 HTTP {response.status_code}")
                    content = response.content
                finally:
                    response.close()
                if stop.is_set():
                    raise TaskStopped()
                yield self.destination(target, asset, name), content
            except RequestException as exc:
                yield ConnectionError("图片来源请求失败：" + type(exc).__name__)
            except (ConnectionError, OSError, ValueError) as exc:
                # One failed source does not hide later aliases/candidates.
                yield exc

    def destination(self, target, asset, hint):
        existing = image_candidates(target, asset)
        if existing:
            return existing[0]
        from app.schemas.file import FileItem
        from app.schemas.types import ScrapingTarget, ScrapingMetadata
        item = FileItem(storage="local", type="dir" if target.kind in {"tv", "season"} else "file",
                        path=target.path, name=Path(target.path).name, basename=Path(target.path).stem)
        parent = FileItem(storage="local", type="dir", path=str(target.directory()), name=target.directory().name)
        _, path = self.scraper._get_target_fileitem_and_path(
            current_fileitem=item, item_type=ScrapingTarget[target.kind.upper()],
            metadata_type=ScrapingMetadata[asset.upper()], filename_hint=hint, parent_fileitem=parent)
        if not path:
            raise ValueError("官方命名接口未提供目标路径")
        return Path(path)
