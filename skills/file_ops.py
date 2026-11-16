"""文件读写技能：所有操作被限制在 ``WORKSPACE_DIR`` 之内。

v2 的安全判定是 ``str(target).startswith(str(BASE))``，有两个真实漏洞：
1. **同前缀兄弟目录逃逸**：``BASE = /srv/workspace``，传入 ``../workspace2/secret.txt``
   解析出的绝对路径以 ``/srv/workspace`` 开头，判定通过 → 越界读取。
2. **软链接逃逸**：``resolve()`` 之后仍只比对字符串前缀，若目标目录是软链接，
   指到工作目录外的真实文件时无法识别（这里 ``resolve()`` 会跟随链接，
   再配合 ``commonpath`` 比较，才真正收敛到 base 内）。

现在用 ``os.path.commonpath`` 做"目录级"包含判断，并对软链接、绝对路径、
``..``、超长文件统一拦截，同时限制单次读写体积，避免把上下文撑爆。
"""

from __future__ import annotations

import os
from pathlib import Path

from config import config
from skills import BaseSkill, SkillParam, SkillResult, registry


class PathEscapeError(ValueError):
    """目标路径越出工作目录。"""


def is_within(target: Path, base: Path) -> bool:
    """目录级包含判断（不是字符串前缀判断）。

    ``commonpath`` 返回两者最深的公共父目录：只有当它恰好等于 ``base`` 才算在内部。
    Windows 需要 ``normcase`` 处理大小写与分隔符差异。
    """
    try:
        common = os.path.commonpath([os.path.normcase(str(target)), os.path.normcase(str(base))])
    except ValueError:  # 不同盘符等
        return False
    return common == os.path.normcase(str(base))


def resolve_inside(base: Path, raw_path: str) -> Path:
    """把相对路径解析成 base 内的绝对路径，越界则抛 ``PathEscapeError``。"""
    if raw_path is None:
        raise PathEscapeError("path 不能为空")
    candidate = str(raw_path).strip()
    if not candidate:
        raise PathEscapeError("path 不能为空")
    # resolve() 会跟随软链接并把 . / .. 归一化
    target = (base / candidate).resolve()
    if not is_within(target, base):
        raise PathEscapeError(f"路径越界：{raw_path}")
    return target


@registry.register
class FileOpsSkill(BaseSkill):
    name = "file_ops"
    description = "在受控工作目录内读取、写入、追加文件，或列出目录内容。"
    dangerous = True
    parameters = [
        SkillParam(
            name="action",
            type="string",
            description="操作类型",
            required=True,
            enum=["read", "write", "append", "list"],
        ),
        SkillParam(name="path", type="string", description="相对工作目录的文件路径", required=True),
        SkillParam(name="content", type="string", description="写入/追加的内容", required=False),
    ]

    def __init__(self, base: Path | None = None) -> None:
        self._base = Path(base) if base else None

    @property
    def base(self) -> Path:
        base = self._base or Path(config.WORKSPACE_DIR)
        base.mkdir(parents=True, exist_ok=True)
        return base.resolve()

    async def execute(self, action: str, path: str, content: str = "", **kw) -> SkillResult:  # type: ignore[override]
        try:
            target = resolve_inside(self.base, path)
        except PathEscapeError as exc:
            return SkillResult(success=False, error=str(exc), metadata={"error_code": "path_escape"})

        base = self.base
        relative = target.relative_to(base).as_posix() or "."

        try:
            if action == "read":
                return self._read(target, relative)
            if action == "write":
                return self._write(target, relative, content, append=False)
            if action == "append":
                return self._write(target, relative, content, append=True)
            if action == "list":
                return self._list(target, relative)
            return SkillResult(success=False, error=f"未知操作：{action}", metadata={"error_code": "bad_action"})
        except OSError as exc:
            return SkillResult(success=False, error=f"{type(exc).__name__}: {exc}", metadata={"error_code": "io_error"})

    # ---------------- 具体操作 ----------------
    def _read(self, target: Path, relative: str) -> SkillResult:
        if not target.exists():
            return SkillResult(success=False, error=f"文件不存在：{relative}", metadata={"error_code": "not_found"})
        if target.is_dir():
            return SkillResult(
                success=False,
                error=f"{relative} 是目录，读取请用 list",
                metadata={"error_code": "is_directory"},
            )
        size = target.stat().st_size
        if size > config.FILE_OPS_MAX_BYTES:
            return SkillResult(
                success=False,
                error=f"文件过大（{size} bytes > {config.FILE_OPS_MAX_BYTES}），请改用更小的文件",
                metadata={"error_code": "file_too_large"},
            )
        text = target.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > config.FILE_OPS_MAX_CHARS
        if truncated:
            text = text[: config.FILE_OPS_MAX_CHARS] + "\n...[已截断]"
        return SkillResult(
            success=True,
            data=text,
            metadata={"path": relative, "chars": len(text), "truncated": truncated, "bytes": size},
        )

    def _write(self, target: Path, relative: str, content: str, *, append: bool) -> SkillResult:
        if len(content.encode("utf-8")) > config.FILE_OPS_MAX_BYTES:
            return SkillResult(
                success=False,
                error=f"写入内容过大（上限 {config.FILE_OPS_MAX_BYTES} bytes）",
                metadata={"error_code": "content_too_large"},
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with target.open(mode, encoding="utf-8") as fp:
            fp.write(content or "")
        return SkillResult(
            success=True,
            data=f"{'已追加' if append else '已写入'} {relative}（{len(content or '')} 字符）",
            metadata={"path": relative, "chars": len(content or ""), "append": append},
        )

    def _list(self, target: Path, relative: str) -> SkillResult:
        if not target.exists():
            return SkillResult(success=False, error=f"目录不存在：{relative}", metadata={"error_code": "not_found"})
        if target.is_file():
            return SkillResult(
                success=True,
                data=f"[FILE] {target.name}（{target.stat().st_size} bytes）",
                metadata={"path": relative, "count": 1},
            )
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        limit = 200
        lines = [f"{'[DIR] ' if e.is_dir() else '[FILE]'} {e.name}" for e in entries[:limit]]
        if len(entries) > limit:
            lines.append(f"...共 {len(entries)} 项，仅显示前 {limit} 项")
        return SkillResult(
            success=True,
            data="\n".join(lines) or "(空目录)",
            metadata={"path": relative, "count": len(entries)},
        )


__all__ = ["FileOpsSkill", "resolve_inside", "is_within", "PathEscapeError"]
