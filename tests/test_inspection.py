import io
from pathlib import Path

import pytest
from nfocheck.config import Condition, Config, ImageCheck, Rule, RuleSet
from nfocheck.core import Inspector, Target, discover, image_candidates
from nfocheck.engine import Engine
from PIL import Image


def png(size=(100, 100)):
    stream = io.BytesIO()
    Image.new("RGB", size, "red").save(stream, format="PNG")
    return stream.getvalue()


def config(root, **kwargs):
    return Config(
        enabled=True,
        stable_seconds=0,
        interval=0,
        rule_sets=[
            RuleSet(
                id="r",
                roots=[str(root)],
                rules=[
                    Rule(id="n", conditions=[Condition(field="plot")], action="nfo"),
                    Rule(
                        id="i",
                        category="image",
                        images=[ImageCheck(type="logo")],
                        action="matched_images",
                    ),
                ],
            )
        ],
        **kwargs,
    )


class Source:
    from nfocheck.core import fallback_parse as parse

    parse = staticmethod(parse)
    calls = None

    def __init__(self):
        self.calls = []

    def candidates(self, target, assets):
        self.calls.append(assets)
        return {
            a: [
                (
                    target.nfo() if a == "nfo" else target.directory() / f"{a}.png",
                    (
                        b"<movie><title>Film</title><plot>Complete synopsis</plot></movie>"
                        if a == "nfo"
                        else png()
                    ),
                )
            ]
            for a in assets
        }


@pytest.fixture
def film(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    movie = root / "Film.mkv"
    movie.write_bytes(b"video untouched")
    return root, movie


def test_merge_and_selective_repair(film, tmp_path):
    root, movie = film
    nfo = movie.with_suffix(".nfo")
    nfo.write_text("<movie><title>Film</title><plot/></movie>")
    poster = root / "poster.png"
    poster.write_bytes(png())
    before = (poster.read_bytes(), poster.stat().st_mtime_ns, movie.read_bytes())
    cfg = config(root)
    # A second independent set must union, not replace the first set's actions.
    cfg.rule_sets.append(
        RuleSet(id="second", roots=[str(root)], rules=[cfg.rule_sets[0].rules.pop()])
    )
    engine = Engine(cfg.model_dump(), tmp_path / "data", Source())
    run = engine.execute("inspect")
    assert run["items"][0]["actions"] == ["logo", "nfo"]
    repaired = engine.execute("repair", run_id=run["id"])
    assert all(r["status"] == "repaired" for r in repaired["items"][0]["results"].values())
    assert before == (poster.read_bytes(), poster.stat().st_mtime_ns, movie.read_bytes())
    assert len(engine.store.read("backups")) == 1
    assert engine.store.read("backups")[0]["asset"] == "nfo"


def test_image_only_does_not_write_nfo(film, tmp_path):
    root, movie = film
    nfo = movie.with_suffix(".nfo")
    nfo.write_text("<movie><title>Film</title><plot>Existing</plot></movie>")
    before = nfo.read_bytes(), nfo.stat().st_mtime_ns
    engine = Engine(config(root).model_dump(), tmp_path / "data", Source())
    engine.execute("run", dry_run=False)
    assert before == (nfo.read_bytes(), nfo.stat().st_mtime_ns)
    assert engine.source.calls == [["logo"]]


def test_dry_run_and_empty_upstream(film, tmp_path):
    root, movie = film
    engine = Engine(config(root).model_dump(), tmp_path / "data", Source())
    assert engine.execute("inspect", files=[])["items"] == []
    run = engine.execute("run", dry_run=True)
    assert run["items"] and not movie.with_suffix(".nfo").exists()
    assert not engine.source.calls
    with pytest.raises(ValueError, match="试运行"):
        # refresh verifies dry-run before considering whether servers are configured.
        engine.execute("refresh", run_id=run["id"])


def test_bad_candidate_keeps_original_and_cools_down(film, tmp_path):
    root, movie = film
    movie.with_suffix(".nfo").write_text("<movie><plot/></movie>")
    source = Source()

    def bad(target, assets):
        source.calls.append(assets)
        return {a: [(target.nfo(), b"<movie><plot/></movie>")] for a in assets}

    source.candidates = bad
    cfg = config(root)
    cfg.rule_sets[0].rules = cfg.rule_sets[0].rules[:1]
    engine = Engine(cfg.model_dump(), tmp_path / "data", source)
    original = movie.with_suffix(".nfo").read_bytes()
    run = engine.execute("run", dry_run=False)
    assert run["items"][0]["results"]["nfo"]["status"] == "unimproved"
    assert movie.with_suffix(".nfo").read_bytes() == original
    again = engine.execute("run", dry_run=False)
    assert again["items"][0]["status"] == "cooldown"
    assert len(source.calls) == 1


def test_season_root_alias_and_episode_identity(tmp_path):
    show = tmp_path / "Show {tmdb-123}"
    season = show / "Season 01"
    season.mkdir(parents=True)
    episode = season / "Show S01E02.strm"
    episode.write_text("https://example.invalid/video")
    episode.with_suffix(".nfo").write_text(
        '<episodedetails><season>1</season><episode>2</episode><uniqueid type="tmdb">456</uniqueid></episodedetails>'
    )
    (show / "season01-poster.png").write_bytes(png())
    cfg = config(tmp_path)
    cfg.rule_sets[0].kinds = ["tv", "season", "episode"]
    targets, errors = discover(cfg)
    assert not errors
    assert {t.kind for t in targets} == {"tv", "season", "episode"}
    t = next(t for t in targets if t.kind == "season")
    assert image_candidates(t, "poster") == [show / "season01-poster.png"]
    t = next(t for t in targets if t.kind == "episode")
    assert not Inspector(cfg).inspect(t)["conflicts"]
    episode.with_suffix(".nfo").write_text(
        "<episodedetails><season>2</season><episode>2</episode></episodedetails>"
    )
    record = Inspector(cfg).inspect(t)
    assert record["conflicts"] and not record["actions"]


def test_dimensions_corruption_and_any_alias(film):
    root, movie = film
    cfg = config(root)
    inspector = Inspector(cfg)
    t = Target(str(movie), "movie", str(root), str(movie))
    (root / "logo.png").write_bytes(b"bad")
    check = ImageCheck(type="logo", min_width=200)
    assert inspector.image_matches(t, check)[0]
    (root / "clearlogo.png").write_bytes(png((400, 200)))
    assert not inspector.image_matches(t, check)[0]


def test_backup_restore_and_concurrent_change(film, tmp_path):
    root, movie = film
    nfo = movie.with_suffix(".nfo")
    nfo.write_text("<movie><plot/></movie>")
    engine = Engine(config(root).model_dump(), tmp_path / "data", Source())
    engine.execute("run", dry_run=False)
    backup = engine.store.read("backups")[0]
    engine.execute("restore", backup_id=backup["id"])
    assert nfo.read_text() == "<movie><plot/></movie>"
    nfo.write_text("externally edited")
    with pytest.raises(ValueError, match="又被修改"):
        engine.execute("restore", backup_id=backup["id"])


def test_rule_validation():
    with pytest.raises(ValueError):
        Condition(op="regex", value="[")
    with pytest.raises(ValueError):
        Condition(op="min_length", value="-1")
    with pytest.raises(ValueError):
        RuleSet(id="r", roots=["relative"])
