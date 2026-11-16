"""A6：代码执行子进程隔离、AST 拦截、超时 kill、stdout 不污染宿主。"""

from __future__ import annotations

import sys

import pytest

from config import config
from skills.code_executor import CodeExecutorSkill, UnsafeCodeError, guard_code


@pytest.fixture
def skill() -> CodeExecutorSkill:
    return CodeExecutorSkill()


async def test_prints_are_captured(skill: CodeExecutorSkill) -> None:
    result = await skill(code="print('hello sandbox')")
    assert result.success
    assert "hello sandbox" in str(result.data)
    assert result.metadata["returncode"] == 0


async def test_math_allowed(skill: CodeExecutorSkill) -> None:
    code = "import math\nprint(round(math.sqrt(2), 4))"
    result = await skill(code=code)
    assert result.success and "1.4142" in str(result.data)


async def test_syntax_error_is_friendly(skill: CodeExecutorSkill) -> None:
    result = await skill(code="def f(:\n    pass")
    assert not result.success
    assert result.metadata["error_code"] == "syntax_error"


async def test_dangerous_import_is_blocked(skill: CodeExecutorSkill) -> None:
    result = await skill(code="import os\nprint(os.listdir('.'))")
    assert not result.success
    assert result.metadata["error_code"] == "unsafe_code"


async def test_dynamic_import_and_builtins_are_blocked(skill: CodeExecutorSkill) -> None:
    assert (await skill(code="__import__('os').system('dir')")).metadata["error_code"] == "unsafe_code"
    assert (await skill(code="eval('1+1')")).metadata["error_code"] == "unsafe_code"
    assert (await skill(code="open('x.txt','w').write('x')")).metadata["error_code"] == "unsafe_code"


async def test_dunder_escape_is_blocked() -> None:
    with pytest.raises(UnsafeCodeError):
        guard_code("print(().__class__.__bases__)")
    with pytest.raises(UnsafeCodeError):
        guard_code("print(getattr((), '__class__'))")


async def test_runtime_error_reports_exit_code(skill: CodeExecutorSkill) -> None:
    result = await skill(code="raise ValueError('boom')")
    assert not result.success
    assert result.metadata["returncode"] != 0
    assert "ValueError" in str(result.error)


async def test_timeout_kills_child(skill: CodeExecutorSkill, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "CODE_EXEC_TIMEOUT", 0.8)
    result = await skill(code="while True:\n    pass")
    assert not result.success
    assert result.metadata["error_code"] == "timeout"
    assert result.metadata["duration_ms"] < 5000


async def test_host_stdout_is_not_swapped(skill: CodeExecutorSkill) -> None:
    before = sys.stdout
    await skill(code="print('x')")
    assert sys.stdout is before


async def test_disabled_flag(monkeypatch: pytest.MonkeyPatch, skill: CodeExecutorSkill) -> None:
    monkeypatch.setattr(config, "ENABLE_CODE_EXEC", False)
    result = await skill(code="print(1)")
    assert not result.success
    assert result.metadata["error_code"] == "disabled"


async def test_empty_code(skill: CodeExecutorSkill) -> None:
    result = await skill(code="   ")
    assert result.metadata["error_code"] == "empty_code"
