"""A5：文件操作路径收敛（同前缀兄弟目录、绝对路径、软链接、体积上限）。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from config import config
from skills.file_ops import FileOpsSkill, PathEscapeError, is_within, resolve_inside


@pytest.fixture
def base(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def skill(base: Path) -> FileOpsSkill:
    return FileOpsSkill(base=base)


async def test_write_read_list_append(skill: FileOpsSkill, base: Path) -> None:
    w = await skill(action="write", path="notes/a.md", content="hello")
    assert w.success and (base / "notes" / "a.md").read_text(encoding="utf-8") == "hello"

    r = await skill(action="read", path="notes/a.md")
    assert r.success and r.data == "hello"

    a = await skill(action="append", path="notes/a.md", content=" world")
    assert a.success
    assert (base / "notes" / "a.md").read_text(encoding="utf-8") == "hello world"

    ls = await skill(action="list", path="notes")
    assert ls.success and "[FILE] a.md" in str(ls.data)


async def test_escape_via_parent_dir_is_blocked(skill: FileOpsSkill, tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("top-secret", encoding="utf-8")
    result = await skill(action="read", path="../secret.txt")
    assert not result.success
    assert result.metadata["error_code"] == "path_escape"


async def test_escape_via_sibling_with_same_prefix_is_blocked(base: Path, tmp_path: Path) -> None:
    """v2 的真实漏洞：``workspace2`` 与 ``workspace`` 共享字符串前缀。"""
    sibling = tmp_path / "workspace2"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("leak", encoding="utf-8")

    skill = FileOpsSkill(base=base)
    result = await skill(action="read", path="../workspace2/secret.txt")
    assert not result.success
    assert result.metadata["error_code"] == "path_escape"
    assert is_within(sibling.resolve(), base.resolve()) is False


async def test_absolute_path_is_blocked(skill: FileOpsSkill) -> None:
    outside = Path(os.environ.get("SYSTEMROOT", "C:/")) / "Windows"
    result = await skill(action="list", path=str(outside))
    assert not result.success
    assert result.metadata["error_code"] == "path_escape"


async def test_symlink_escape_is_blocked(base: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "flag.txt").write_text("outside", encoding="utf-8")
    link = base / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建软链接")

    skill = FileOpsSkill(base=base)
    result = await skill(action="read", path="link/flag.txt")
    assert not result.success
    assert result.metadata["error_code"] == "path_escape"


def test_resolve_inside_accepts_nested_relative(base: Path) -> None:
    target = resolve_inside(base, "a/b/c.txt")
    assert is_within(target, base)
    assert target.name == "c.txt"


def test_resolve_inside_rejects_empty_and_dotdot(base: Path) -> None:
    for bad in ("", "   ", "..", "../"):
        with pytest.raises(PathEscapeError):
            resolve_inside(base, bad)


async def test_large_file_is_rejected(skill: FileOpsSkill, base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "FILE_OPS_MAX_BYTES", 64)
    (base / "big.txt").write_text("x" * 200, encoding="utf-8")
    result = await skill(action="read", path="big.txt")
    assert not result.success
    assert result.metadata["error_code"] == "file_too_large"


async def test_long_file_is_truncated(skill: FileOpsSkill, base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "FILE_OPS_MAX_CHARS", 100)
    (base / "long.txt").write_text("y" * 500, encoding="utf-8")
    result = await skill(action="read", path="long.txt")
    assert result.success
    assert result.metadata["truncated"] is True
    assert "已截断" in str(result.data)


async def test_missing_file_and_directory_confusion(skill: FileOpsSkill) -> None:
    missing = await skill(action="read", path="nope.txt")
    assert missing.metadata["error_code"] == "not_found"
    await skill(action="write", path="dir/x.txt", content="1")
    as_dir = await skill(action="read", path="dir")
    assert as_dir.metadata["error_code"] == "is_directory"
