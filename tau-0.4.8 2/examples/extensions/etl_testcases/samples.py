"""Read the historical ETL test-case samples shipped with the demo."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tau_agent.types import JSONValue

_FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_SAMPLES_DIR = Path(__file__).resolve().parent / "samples"


@dataclass(frozen=True, slots=True)
class Sample:
    sample_id: str
    title: str
    tags: tuple[str, ...]
    summary: str
    body: str

    def matches(self, keyword: str) -> bool:
        haystack = " ".join((self.sample_id, self.title, self.summary, *self.tags, self.body))
        return keyword.casefold() in haystack.casefold()

    def summary_line(self) -> str:
        tags = ", ".join(self.tags) if self.tags else "无"
        return f"- {self.sample_id} | {self.title} | 标签: {tags} | {self.summary}"


def read_samples(sample_id: str | None, keyword: str | None) -> tuple[str, dict[str, JSONValue]]:
    """List sample summaries, or return one full historical sample."""
    samples = _load_samples()
    if not samples:
        message = f"没有找到历史样例。期望目录：{_SAMPLES_DIR}。"
        return message, {"demo": True, "error": message}

    if sample_id is not None and sample_id.strip():
        return _read_one(samples, sample_id.strip())

    selected = samples
    needle = keyword.strip() if isinstance(keyword, str) else ""
    if needle:
        selected = tuple(sample for sample in samples if sample.matches(needle))
    return _list_samples(selected, needle, len(samples))


def _read_one(samples: tuple[Sample, ...], sample_id: str) -> tuple[str, dict[str, JSONValue]]:
    for sample in samples:
        if sample.sample_id == sample_id:
            text = (
                f"历史样例 `{sample.sample_id}`，只示范用例写法，"
                f"不覆盖用户本次描述的 ETL 规则。\n\n{sample.body}"
            )
            return text, {"demo": True, "sample": _sample_details(sample, include_body=True)}
    known = ", ".join(sample.sample_id for sample in samples)
    message = f"没有历史样例 `{sample_id}`。可用编号：{known}。"
    return message, {"demo": True, "error": message}


def _list_samples(
    samples: tuple[Sample, ...], keyword: str, total: int
) -> tuple[str, dict[str, JSONValue]]:
    if keyword and not samples:
        message = f"没有匹配 `{keyword}` 的历史样例。可以不带 keyword 查看全部 {total} 份。"
        return message, {"demo": True, "error": message, "samples": []}
    heading = (
        f"匹配 `{keyword}` 的历史样例 {len(samples)} 份："
        if keyword
        else f"历史测试样例 {len(samples)} 份。读取全文时传入 sample_id："
    )
    lines = [heading, *(sample.summary_line() for sample in samples)]
    details: dict[str, JSONValue] = {
        "demo": True,
        "samples": [_sample_details(sample, include_body=False) for sample in samples],
    }
    return "\n".join(lines), details


def _sample_details(sample: Sample, *, include_body: bool) -> dict[str, JSONValue]:
    details: dict[str, JSONValue] = {
        "sample_id": sample.sample_id,
        "title": sample.title,
        "tags": list(sample.tags),
        "summary": sample.summary,
    }
    if include_body:
        details["body"] = sample.body
    return details


def _load_samples() -> tuple[Sample, ...]:
    if not _SAMPLES_DIR.is_dir():
        return ()
    loaded: list[Sample] = []
    for path in sorted(_SAMPLES_DIR.glob("*.md")):
        loaded.append(_parse_sample(path.read_text(encoding="utf-8"), path.stem))
    return tuple(sorted(loaded, key=lambda sample: sample.sample_id))


def _parse_sample(text: str, fallback_id: str) -> Sample:
    match = _FRONT_MATTER.match(text)
    meta: dict[str, str] = {}
    body = text.strip()
    if match is not None:
        body = text[match.end() :].strip()
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    tags = tuple(part.strip() for part in meta.get("tags", "").split(",") if part.strip())
    return Sample(
        sample_id=meta.get("id") or fallback_id,
        title=meta.get("title") or fallback_id,
        tags=tags,
        summary=meta.get("summary", ""),
        body=body + "\n",
    )
