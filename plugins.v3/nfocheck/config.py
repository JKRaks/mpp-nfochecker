"""Validated user configuration, shared by UI, workflow and worker."""

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ASSETS = {
    "movie": ["poster", "backdrop", "logo", "banner", "landscape", "thumb", "clearart", "disc"],
    "tv": ["poster", "backdrop", "logo", "banner", "landscape", "thumb", "clearart"],
    "season": ["poster", "backdrop", "banner", "landscape", "thumb"],
    "episode": ["thumb"],
}
Kind = Literal["movie", "tv", "season", "episode"]
ImageType = Literal[
    "poster", "backdrop", "logo", "banner", "landscape", "thumb", "clearart", "disc"
]


class Condition(BaseModel):
    op: Literal[
        "missing",
        "invalid",
        "empty",
        "min_length",
        "regex",
        "identity_missing",
        "conflict",
        "language_missing",
        "language_mismatch",
        "language_unknown",
    ] = "empty"
    field: str = "plot"
    value: str = ""

    @model_validator(mode="after")
    def validate_condition(self):
        if self.op in {"empty", "min_length", "regex"} and not self.field.strip():
            raise ValueError("请选择 NFO 字段或填写自定义字段路径")
        if self.op == "regex":
            try:
                re.compile(self.value)
            except re.error as exc:
                raise ValueError("正则表达式无效：" + str(exc)) from exc
        if self.op == "min_length" and (not self.value.isdigit() or int(self.value) < 1):
            raise ValueError("最小长度必须为正整数")
        if self.op.startswith("language_") and self.field not in {
            "title",
            "plot",
            "outline",
            "tagline",
        }:
            raise ValueError("语言条件仅支持标题、简介、摘要和宣传语")
        if self.field.startswith("/") or ".." in self.field:
            raise ValueError("字段路径必须相对于 NFO 根元素")
        # Validate ElementTree's supported XPath subset before running a scan.
        import xml.etree.ElementTree as ET

        try:
            ET.fromstring("<root/>").findall(self.field or "plot")
        except (SyntaxError, KeyError, TypeError) as exc:
            raise ValueError("不支持的 XML 字段路径") from exc
        return self


class ImageCheck(BaseModel):
    type: ImageType = "poster"
    missing: bool = True
    damaged: bool = True
    min_width: int = Field(default=0, ge=0)
    min_height: int = Field(default=0, ge=0)


class Rule(BaseModel):
    id: str
    name: str = "规则"
    enabled: bool = True
    category: Literal["nfo", "image"] = "nfo"
    match: Literal["any", "all"] = "any"
    conditions: list[Condition] = Field(default_factory=list)
    images: list[ImageCheck] = Field(default_factory=list)
    action: Literal[
        "report", "nfo", "matched_images", "selected_images", "both", "translate", "nfo_translate"
    ] = "report"
    selected_images: list[ImageType] = Field(default_factory=list)
    translation_policy: str = "default"
    translation_fields: list[str] = Field(default_factory=lambda: ["plot", "outline"])

    @model_validator(mode="after")
    def validate_rule(self):
        if not self.translation_fields or set(self.translation_fields) - {
            "title",
            "plot",
            "outline",
            "tagline",
        }:
            raise ValueError("请选择有效翻译字段")
        self.translation_fields = list(dict.fromkeys(self.translation_fields))
        if self.action in {"translate", "nfo_translate"} and self.category != "nfo":
            raise ValueError("翻译动作仅用于 NFO 规则")
        if any(
            c.op.startswith("language_") and c.field not in self.translation_fields
            for c in self.conditions
        ):
            raise ValueError("语言条件字段需要包含在所选翻译字段中")
        if self.category == "nfo" and not self.conditions:
            raise ValueError("NFO 规则至少需要一个条件")
        if self.category == "image" and not self.images:
            raise ValueError("图片规则至少需要一种图片")
        if self.category == "nfo" and self.action == "matched_images":
            raise ValueError("NFO 条件不能选择更新命中图片")
        if self.action == "selected_images" and not self.selected_images:
            raise ValueError("请选择要更新的图片类型")
        if self.action == "both" and self.category == "nfo" and not self.selected_images:
            raise ValueError("同时更新时请选择图片类型")
        return self


class RuleSet(BaseModel):
    id: str
    name: str = "规则集"
    enabled: bool = True
    roots: list[str] = Field(default_factory=list)
    kinds: list[Kind] = Field(default_factory=lambda: ["movie", "tv", "episode"])
    excludes: list[str] = Field(default_factory=list)
    exclude_regex: str = ""
    exclude_season_zero: bool = False
    emby: Literal["off", "changed", "compare"] = "off"
    rules: list[Rule] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_set(self):
        if self.exclude_regex:
            try:
                re.compile(self.exclude_regex)
            except re.error as exc:
                raise ValueError("排除正则无效：" + str(exc)) from exc
        if any(not Path(p).is_absolute() for p in self.roots + self.excludes):
            raise ValueError("检查目录及排除路径必须是绝对路径")
        if len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError("规则 ID 重复")
        return self


class BackupConfig(BaseModel):
    nfo: bool = True
    images: bool = False
    directory: str = ""
    cleanup: bool = True
    days: int = Field(default=30, ge=0)
    versions: int = Field(default=3, ge=0)


class EmbyServer(BaseModel):
    name: str
    libraries: list[str] = Field(default_factory=list)
    mappings: list[dict[str, str]] = Field(default_factory=list)


class Config(BaseModel):
    version: int = 3
    enabled: bool = False
    rule_sets: list[RuleSet] = Field(default_factory=list)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    batch_limit: int = Field(default=100, ge=1, le=10000)
    auto_continue: bool = False
    max_batches_per_run: int = Field(default=3, ge=1, le=100)
    interval: float = Field(default=2, ge=0)
    stable_seconds: int = Field(default=300, ge=0)
    cooldown_days: float = Field(default=7, ge=0)
    max_no_improvement: int = Field(default=3, ge=1)
    history_days: int = Field(default=30, ge=1)
    emby_servers: list[EmbyServer] = Field(default_factory=list)
    emby_poll: float = Field(default=10, ge=1)
    emby_timeout: float = Field(default=120, ge=0, le=3600)
    notify: Literal["off", "always", "issues"] = "issues"
    notify_channels: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_config(self):
        if len({s.id for s in self.rule_sets}) != len(self.rule_sets):
            raise ValueError("规则集 ID 重复")
        if self.backup.directory and not Path(self.backup.directory).is_absolute():
            raise ValueError("备份目录必须是绝对路径")
        for server in self.emby_servers:
            for mapping in server.mappings:
                if not mapping.get("local", "").startswith("/") or not mapping.get("remote"):
                    raise ValueError("路径映射需要本地绝对路径及 Emby 路径")
        return self


def defaults():
    rules = [
        Rule(
            id="nfo",
            name="NFO 基础完整性",
            conditions=[
                Condition(op="missing"),
                Condition(op="invalid"),
                Condition(field="title"),
                Condition(field="plot"),
            ],
        )
    ]
    rules.extend(
        Rule(id=asset, name=name, category="image", images=[ImageCheck(type=asset)])
        for asset, name in [
            ("poster", "主图完整性"),
            ("logo", "徽标补全"),
            ("backdrop", "背景图补全"),
            ("thumb", "单集主图"),
        ]
    )
    return Config(rule_sets=[RuleSet(id="default", name="基础完整性", rules=rules)]).model_dump()
