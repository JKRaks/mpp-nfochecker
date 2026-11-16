"""插件 API 的响应模型。

模型只声明前端依赖的顶层字段，并允许额外字段，避免 FastAPI 响应过滤丢弃数据。
接口仍直接返回业务对象，不使用宿主 schemas.Response 外层包装。
"""
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class _Payload(BaseModel):
    """允许额外字段的基类，保持与既有 JSON 结构兼容。"""

    model_config = ConfigDict(extra="allow")


class SettingsData(_Payload):
    """设置页数据：配置、资产枚举、NFO 字段、翻译说明、Emby 服务与通知渠道。"""

    config: Optional[dict[str, Any]] = None
    assets: Optional[dict[str, Any]] = None
    nfo_fields: Optional[list[Any]] = None
    translation: Optional[dict[str, Any]] = None
    servers: Optional[list[str]] = None
    channels: Optional[list[dict[str, Any]]] = None


class OkData(_Payload):
    """仅表示操作是否完成的结果。"""

    ok: bool = True


class StopData(_Payload):
    """停止请求的结果。"""

    ok: bool = True
    message: str = ""


class StatusData(_Payload):
    """运行状态、运行记录摘要和待同步数量。"""

    live: Optional[dict[str, Any]] = None
    runs: Optional[list[Any]] = None
    pending_count: int = 0
    backups: Optional[list[Any]] = None


class ReportData(_Payload):
    """运行记录分页结果；ids_only 时只返回 ids。"""

    ids: Optional[list[str]] = None
    items: Optional[list[Any]] = None
    total: Optional[int] = None
    page: Optional[int] = None
    page_size: Optional[int] = None


class DeleteRunsData(_Payload):
    """已删除的运行编号。"""

    deleted: list[str] = []


class LiveData(_Payload):
    """启动任务后返回的实时状态快照。"""

    busy: Optional[bool] = None
    run_id: Optional[str] = None
    error: Optional[str] = None


class PendingData(_Payload):
    """待同步队列分页。"""

    items: list[dict[str, Any]] = []
    total: int = 0
    page: int = 1
    page_size: int = 100


class BackupDetailData(_Payload):
    """NFO 备份只读预览。"""

    backup: dict[str, Any]
    nfo: str
