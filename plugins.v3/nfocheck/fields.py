"""Selectable NFO element paths; labels do not change saved XPath values.

Kodi's movie / TV show / episode tag references are the baseline. Compatibility
entries come from MoviePilot's domain/scraper.py and modules/themoviedb/scraper.py.
Kinds describe where a field is useful, not a new mandatory-field policy.
"""

ALL = ["movie", "tv", "season", "episode"]
VIDEO = ["movie", "episode"]
KODI = ["movie", "tv", "episode"]


def field(value, title, group, kinds=KODI, note=""):
    return {"value": value, "label": f"{title}({value})", "group": group,
            "kinds": list(kinds), "note": note}


NFO_FIELDS = [
    field("title", "标题", "基础信息", ALL),
    field("originaltitle", "原始标题", "基础信息", ALL, "单集在 Kodi 中继承整剧信息；MoviePilot 部分来源也会写入。"),
    field("sorttitle", "排序标题", "基础信息", ["movie", "tv"]),
    field("plot", "剧情简介", "基础信息", ALL),
    field("outline", "简短摘要", "基础信息", ALL, "Kodi 主要用于电影；MoviePilot 也会在剧、季、单集中写入。"),
    field("tagline", "宣传语", "基础信息", KODI, "剧集宣传语为 Kodi v22 新增字段。"),
    field("premiered", "首映日期", "基础信息", ALL, "单集在 Kodi 中继承整剧日期；单集自身播出日期使用 aired。"),
    field("year", "年份", "基础信息", ALL, "MoviePilot 兼容字段；Kodi v20 起使用 premiered。"),
    field("runtime", "时长（分钟）", "基础信息", KODI, "Kodi 用于电影和单集；MoviePilot 也可能写入整剧。"),
    field("mpaa", "内容分级", "基础信息", KODI, "单集在 Kodi 中继承整剧信息。"),
    field("genre", "类型", "基础信息", ALL, "可重复；单集在 Kodi 中继承整剧信息。"),
    field("country", "制作国家或地区", "基础信息", ["movie", "tv"], "Kodi 电影字段；MoviePilot 也可能写入整剧。"),
    field("studio", "制作公司", "基础信息", ALL),
    field("tag", "标签", "基础信息", ["movie", "tv"]),
    field("trailer", "预告片地址", "基础信息", ["movie", "tv"]),
    field("originallanguage", "原始语言", "基础信息", ["movie", "tv"], "Kodi v22 新增，旧刮削器可能不生成。"),
    field("uniqueid", "媒体来源 ID", "来源标识", ALL, "检查任一来源 ID；限定来源请使用下方带 type 的选项。"),
    field("uniqueid[@type='tmdb']", "TMDB 来源 ID", "来源标识", ALL),
    field("uniqueid[@type='imdb']", "IMDb 来源 ID", "来源标识", ALL),
    field("uniqueid[@type='tvdb']", "TVDB 来源 ID", "来源标识", KODI),
    field("tmdbid", "TMDB 兼容 ID", "来源标识", KODI, "MoviePilot 写入的兼容字段，与 uniqueid 分别检查。"),
    field("imdbid", "IMDb 兼容 ID", "来源标识", ["movie", "tv"], "MoviePilot 写入的兼容字段，与 uniqueid 分别检查。"),
    field("tvdbid", "TVDB 兼容 ID", "来源标识", ["movie", "tv"], "MoviePilot 写入的兼容字段，与 uniqueid 分别检查。"),
    field("actor/name", "演员姓名", "演职员", ALL),
    field("actor/role", "饰演角色", "演职员", ALL),
    field("actor/thumb", "演员头像地址", "演职员", ALL),
    field("actor/order", "演员排序", "演职员"),
    field("director", "导演", "演职员", ALL),
    field("credits", "编剧", "演职员", VIDEO),
    field("ratings/rating/value", "评分值", "评分", KODI, "多来源评分结构；MoviePilot 常用单层 rating 字段。"),
    field("ratings/rating/votes", "评分人数", "评分"),
    field("rating", "评分（兼容）", "评分", ALL, "MoviePilot 当前生成的单层评分字段。"),
    field("userrating", "个人评分", "评分"),
    field("top250", "IMDb 前 250 排名", "评分", ["movie", "tv"], "未上榜作品通常没有该字段，不建议作为通用完整性条件。"),
    field("showtitle", "剧名", "剧集与合集", ["tv", "episode"]),
    field("season", "季号或总季数", "剧集与合集", ["tv", "episode"], "单集为季号；整剧为季数，MoviePilot 可能写入 -1。season.nfo 使用 seasonnumber。"),
    field("episode", "集号或总集数", "剧集与合集", ["tv", "episode"], "单集为集号；整剧为集数，MoviePilot 可能写入 -1。"),
    field("seasonnumber", "季号", "剧集与合集", ["season"], "MoviePilot season.nfo 字段；不是 Kodi 整剧或单集的 season 字段。"),
    field("aired", "单集首播日期", "剧集与合集", ["episode"]),
    field("releasedate", "季发行日期（兼容）", "剧集与合集", ["season"], "MoviePilot 的 TMDB 季 NFO 字段。"),
    field("displayseason", "特别篇显示季号", "剧集与合集", ["episode"]),
    field("displayepisode", "特别篇显示集号", "剧集与合集", ["episode"]),
    field("episodeguide", "剧集索引", "剧集与合集", ["tv"]),
    field("status", "播出状态", "剧集与合集", ["tv"]),
    field("namedseason", "季名称", "剧集与合集", ["tv"]),
    field("seasonplot", "季简介", "剧集与合集", ["tv"], "Kodi v22 新增，位于 tvshow.nfo 中。"),
    field("set/name", "电影合集名称", "剧集与合集", ["movie"]),
    field("set/overview", "电影合集简介", "剧集与合集", ["movie"]),
    field("showlink", "关联电视剧", "剧集与合集", ["movie"]),
    field("thumb", "图片地址", "图片引用"),
    field("thumb[@aspect='poster']", "主图地址", "图片引用", ["movie", "tv"]),
    field("thumb[@aspect='clearlogo']", "徽标地址", "图片引用", ["movie", "tv"]),
    field("thumb[@aspect='banner']", "横幅地址", "图片引用", ["movie", "tv"]),
    field("thumb[@aspect='landscape']", "横版图地址", "图片引用", ["movie", "tv"]),
    field("thumb[@aspect='clearart']", "透明艺术图地址", "图片引用", ["movie", "tv"]),
    field("thumb[@aspect='discart']", "光盘图地址", "图片引用", ["movie"]),
    field("thumb[@aspect='thumb']", "单集缩略图地址", "图片引用", ["episode"]),
    field("fanart/thumb", "背景图地址", "图片引用", ["movie", "tv"]),
    field("fileinfo/streamdetails/video/codec", "视频编码", "媒体流信息", VIDEO),
    field("fileinfo/streamdetails/video/aspect", "画面比例", "媒体流信息", VIDEO),
    field("fileinfo/streamdetails/video/width", "视频宽度", "媒体流信息", VIDEO),
    field("fileinfo/streamdetails/video/height", "视频高度", "媒体流信息", VIDEO),
    field("fileinfo/streamdetails/video/durationinseconds", "视频时长（秒）", "媒体流信息", VIDEO),
    field("fileinfo/streamdetails/video/stereomode", "立体视频模式", "媒体流信息", VIDEO),
    field("fileinfo/streamdetails/video/hdrtype", "HDR 类型", "媒体流信息", VIDEO, "SDR 视频允许为空，不建议作为通用完整性条件。"),
    field("fileinfo/streamdetails/audio/codec", "音频编码", "媒体流信息", VIDEO),
    field("fileinfo/streamdetails/audio/language", "音轨语言", "媒体流信息", VIDEO),
    field("fileinfo/streamdetails/audio/channels", "音轨声道数", "媒体流信息", VIDEO),
    field("fileinfo/streamdetails/subtitle/language", "字幕语言", "媒体流信息", VIDEO),
    field("playcount", "播放次数", "播放记录"),
    field("lastplayed", "上次播放时间", "播放记录"),
    field("resume/position", "续播位置", "播放记录", VIDEO),
    field("resume/total", "续播总时长", "播放记录", VIDEO),
    field("dateadded", "入库时间", "播放记录"),
]

FIELD_LABELS = {item["value"]: item["label"] for item in NFO_FIELDS}
