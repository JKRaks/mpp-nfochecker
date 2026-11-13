"""Failures with actionable categories; diagnostic strings never contain URL secrets."""
import re
from requests.exceptions import RequestException


class CandidateRejected(ValueError):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


class SourceUnavailable(ValueError):
    pass


class FileConflict(ValueError):
    pass


class StorageError(RuntimeError):
    """Durable plugin state could not be saved; the worker must stop."""


class TaskStopped(Exception):
    pass


# Authorization contains a scheme and a credential separated by whitespace.
# Match a whole header value, including quoted JSON/Python header dictionaries.
_AUTHORIZATION = re.compile(
    r'''(?i)(["']?\bauthorization\b["']?[ \t]*[:=][ \t]*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^,;\r\n}\]"']+)'''
)
_SECRET_VALUE = re.compile(
    r'''(?i)(["']?(?:api[_-]?key|token|password)["']?\s*[=:]\s*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}\]]+)'''
)


def safe_message(error):
    text = _AUTHORIZATION.sub(r"\1[隐藏]", str(error))
    text = re.sub(r"https?://[^\s\"'<>]+", "[请求地址已隐藏]", text)
    return _SECRET_VALUE.sub(r"\1[隐藏]", text)[:1500]


def failure(error):
    if isinstance(error, CandidateRejected):
        category, status = "candidate_rejected", "unimproved"
    elif isinstance(error, SourceUnavailable):
        category, status = "source_empty", "unimproved"
    elif isinstance(error, FileConflict):
        category, status = "file_conflict", "failed"
    elif isinstance(error, (ConnectionError, TimeoutError, RequestException)):
        category, status = "network", "failed"
    elif isinstance(error, OSError):
        category, status = "io", "failed"
    else:
        category, status = "internal", "failed"
    return {"status": status, "error_code": category, "error_type": type(error).__name__,
            "message": safe_message(error), "details": getattr(error, "details", {})}
