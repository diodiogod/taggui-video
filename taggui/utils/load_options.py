from dataclasses import dataclass


VALID_LIMITED_SORT_BY = ("mtime", "name", "rating")
VALID_LIMITED_SORT_DIR = ("ASC", "DESC")


def normalize_limited_sort_by(value: str | None) -> str:
    text = str(value or "mtime").strip().lower()
    if text not in VALID_LIMITED_SORT_BY:
        return "mtime"
    return text


def normalize_limited_sort_dir(value: str | None, *, sort_by: str | None = None) -> str:
    text = str(value or "").strip().upper()
    if text in VALID_LIMITED_SORT_DIR:
        return text
    if normalize_limited_sort_by(sort_by) == "name":
        return "ASC"
    return "DESC"


@dataclass(frozen=True)
class LimitedLoadOptions:
    limit: int
    sort_by: str = "mtime"
    sort_dir: str = "DESC"

    def normalized(self) -> "LimitedLoadOptions | None":
        try:
            limit_value = int(self.limit)
        except Exception:
            return None
        if limit_value <= 0:
            return None
        sort_by = normalize_limited_sort_by(self.sort_by)
        sort_dir = normalize_limited_sort_dir(self.sort_dir, sort_by=sort_by)
        return LimitedLoadOptions(limit=limit_value, sort_by=sort_by, sort_dir=sort_dir)

    @property
    def db_sort_field(self) -> str:
        if self.sort_by == "name":
            return "file_name"
        if self.sort_by == "rating":
            return "rating"
        return "mtime"

    @property
    def ui_sort_label(self) -> str | None:
        if self.sort_by == "name":
            return "Name"
        if self.sort_by == "rating":
            return None
        return "Modified"

    def describe(self) -> str:
        return f"limit={self.limit}, sort_by={self.sort_by}, sort_dir={self.sort_dir}"
