import copy
from urllib.parse import parse_qs, urlsplit

from nfocheck.config import EmbyServer
from nfocheck.core import Inspector, Target
from nfocheck.emby import EmbyGateway, map_path
from nfocheck.engine import Engine
from test_inspection import Source, config, png


class Response:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data

    def close(self):
        pass


class Service:
    def __init__(self, before, after=None):
        self.before = before
        self.after = after or before
        self.calls = []
        self.offline = False

    def get_data(self, url):
        if self.offline:
            return None
        self.calls.append(("GET", url))
        return Response(
            {"Items": [copy.deepcopy(self.before)], "TotalRecordCount": 1}
            if "StartIndex=" in url
            else copy.deepcopy(self.after)
        )

    def post_data(self, url, **kwargs):
        self.calls.append(("POST", url))
        return Response({})


class Stop:
    def is_set(self):
        return False

    def wait(self, seconds):
        return False


def setup(tmp_path, mode="compare"):
    root = tmp_path / "media"
    root.mkdir()
    movie = root / "Film.mkv"
    movie.write_bytes(b"video")
    movie.with_suffix(".nfo").write_text("<movie><title>Film</title><plot>Complete</plot></movie>")
    (root / "logo.png").write_bytes(png())
    cfg = config(root)
    cfg.emby_servers = [
        EmbyServer(name="server", mappings=[{"local": str(root), "remote": "/movies"}])
    ]
    cfg.emby_timeout = 0.05
    cfg.rule_sets[0].emby = mode
    inspector = Inspector(cfg)
    record = inspector.inspect(Target(str(movie), "movie", str(root), str(movie)))
    item = {
        "Id": "1",
        "Path": "/movies/Film.mkv",
        "Type": "Movie",
        "Name": "Film",
        "Overview": "",
        "ImageTags": {},
    }
    return cfg, inspector, record, item


def test_refresh_missing_fields_and_images(tmp_path):
    cfg, inspector, record, before = setup(tmp_path)
    service = Service(before, {**before, "Overview": "Complete", "ImageTags": {"Logo": "new"}})
    gateway = EmbyGateway(cfg, {"server": service})
    comparison = gateway.compare(record, inspector)
    assert comparison[0]["fields"] == ["Overview"]
    assert comparison[0]["assets"] == ["logo"]
    result = gateway.refresh(record, inspector, Stop())
    assert result[0]["status"] == "verified"
    post = [url for method, url in service.calls if method == "POST"]
    assert len(post) == 1 and "/Refresh?" in post[0]
    params = parse_qs(urlsplit(post[0].replace("[HOST]", "http://local/")).query)
    assert params["ReplaceAllImages"] == ["false"]
    assert params["Recursive"] == ["false"]
    assert params["MetadataRefreshMode"] == ["FullRefresh"]
    record["sync"] = result
    gateway.refresh(record, inspector, Stop())
    assert len([c for c in service.calls if c[0] == "POST"]) == 1


def test_image_only_never_replaces_metadata_or_uploads(tmp_path):
    cfg, inspector, record, before = setup(tmp_path, "changed")
    record["results"] = {"logo": {"status": "repaired"}}
    before["ImageTags"] = {"Logo": "old", "Primary": "curated"}
    service = Service(before, {**before, "ImageTags": {"Logo": "new", "Primary": "curated"}})
    result = EmbyGateway(cfg, {"server": service}).refresh(record, inspector, Stop())
    assert result[0]["status"] == "unconfirmed"
    post = next(url for method, url in service.calls if method == "POST")
    assert "MetadataRefreshMode=ValidationOnly" in post
    assert "ReplaceAllMetadata=false" in post and "ReplaceAllImages=false" in post
    assert "/Refresh?" in post


def test_locked_and_unmatched_do_not_expand_scope(tmp_path):
    cfg, inspector, record, before = setup(tmp_path)
    before["LockedFields"] = ["Overview"]
    before["ImageTags"] = {"Logo": "existing"}
    service = Service(before)
    gateway = EmbyGateway(cfg, {"server": service})
    assert gateway.refresh(record, inspector, Stop())[0]["status"] == "locked"
    assert not any(method == "POST" for method, _ in service.calls)
    before["Path"] = "/other/Film.mkv"
    gateway = EmbyGateway(cfg, {"server": service})
    assert gateway.refresh(record, inspector, Stop())[0]["status"] == "failed"
    assert not any(method == "POST" for method, _ in service.calls)


def test_path_mapping_boundary():
    assert (
        map_path("/media/115/F.mkv", [{"local": "/media/11", "remote": "/wrong"}])
        == "/media/115/F.mkv"
    )
    assert (
        map_path(
            "/media/115/F.mkv",
            [{"local": "/media", "remote": "/all"}, {"local": "/media/115", "remote": "/right"}],
        )
        == "/right/F.mkv"
    )


def test_offline_sync_retries_without_scraping_again(tmp_path):
    cfg, inspector, record, before = setup(tmp_path, "changed")
    root = tmp_path / "media"
    (root / "Film.nfo").write_text("<movie><title>Film</title><plot/></movie>")
    service = Service(
        before, {**before, "Overview": "Complete synopsis", "ImageTags": {"Logo": "ok"}}
    )
    service.offline = True
    source = Source()
    engine = Engine(
        cfg.model_dump(), tmp_path / "data", source, lambda c: EmbyGateway(c, {"server": service})
    )
    first = engine.execute("run", dry_run=False)
    assert first["items"][0]["sync"][0]["status"] == "failed"
    assert len(source.calls) == 1
    service.offline = False
    second = engine.execute("run", dry_run=False)
    assert second["items"][0]["sync"][0]["status"] == "verified"
    assert len(source.calls) == 1


def test_own_write_can_refresh_during_stability_window(tmp_path):
    import os
    import time

    cfg, inspector, record, before = setup(tmp_path, "changed")
    root = tmp_path / "media"
    (root / "Film.nfo").write_text("<movie><title>Film</title><plot/></movie>")
    old = time.time() - 1000
    for path in [*root.iterdir(), root]:
        os.utime(path, (old, old))
    cfg.stable_seconds = 300
    service = Service(
        before, {**before, "Overview": "Complete synopsis", "ImageTags": {"Logo": "ok"}}
    )
    engine = Engine(
        cfg.model_dump(), tmp_path / "data", Source(), lambda c: EmbyGateway(c, {"server": service})
    )
    run = engine.execute("run", dry_run=False)
    assert run["items"][0]["results"]["nfo"]["status"] == "repaired"
    assert run["items"][0]["sync"][0]["status"] == "verified"
