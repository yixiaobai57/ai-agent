"""代码执行技能：把模型生成的 Python 代码放到**独立子进程**里跑。

v2 的三处硬伤：
1. 黑名单是字符串匹配（``'os.system' in code``），``__import__('os').system(...)``
   或 ``getattr(os, 'sys'+'tem')`` 立刻绕过。
2. 用 ``exec`` 在**宿主进程内**执行，且把全局 ``sys.stdout`` 换成 ``StringIO``——
   两个并发会话会互相串输出，还会污染服务端日志。
3. ``asyncio.wait_for`` 超时只是取消了 future，线程里的死循环仍在跑，越积越多。

现在：
- 代码写进临时目录，用 ``python -I``（隔离模式）作为子进程执行，会话之间零共享；
- 超时直接 kill 子进程，不会留下僵尸计算；
- 执行前做 AST 检查：拦掉危险 import、``eval``/``exec``/``open`` 等调用；
- stdout / stderr 分流，stderr 只在返回码非 0 时算失败（warning 不再被误判成错误）。

诚实边界：AST + 子进程隔离是**降低风险**，不是安全沙箱。要跑不可信代码，
请把 ``ENABLE_CODE_EXEC`` 关掉，或用容器/nsjail 之类的外部隔离。
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from config import config
from skills import BaseSkill, SkillParam, SkillResult, registry

# 允许 import 的标准库白名单：够做算法题/数据处理，但拿不到进程与文件能力
ALLOWED_MODULES: set[str] = {
    "math",
    "statistics",
    "random",
    "decimal",
    "fractions",
    "json",
    "re",
    "string",
    "textwrap",
    "datetime",
    "time",
    "collections",
    "itertools",
    "functools",
    "heapq",
    "bisect",
    "typing",
    "dataclasses",
    "enum",
    "hashlib",
    "base64",
    "uuid",
    "copy",
}

BANNED_CALLS: set[str] = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",
    "input",
    "breakpoint",
    "globals",
    "locals",
    "vars",
    "setattr",
    "delattr",
}

MAX_OUTPUT_CHARS = 8000


class UnsafeCodeError(ValueError):
    """代码未通过静态安全检查。"""


def guard_code(code: str) -> None:
    """静态检查：语法错误抛 SyntaxError，危险用法抛 UnsafeCodeError。"""
    tree = ast.parse(code)

    for node in ast.walk(tree):
        # import 白名单
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_MODULES:
                    raise UnsafeCodeError(f"禁止 import 模块：{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root not in ALLOWED_MODULES:
                raise UnsafeCodeError(f"禁止 from ... import：{node.module}")
        # 危险内建调用
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in BANNED_CALLS:
                raise UnsafeCodeError(f"禁止调用：{fn.id}()")
            if isinstance(fn, ast.Name) and fn.id == "getattr" and node.args:
                first_const = node.args[1] if len(node.args) > 1 else None
                if isinstance(first_const, ast.Constant) and str(first_const.value).startswith("__"):
                    raise UnsafeCodeError(f"禁止通过 getattr 访问下划线属性：{first_const.value}")
        # 双下划线属性（``().__class__.__bases__`` 这类逃逸套路）
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise UnsafeCodeError(f"禁止访问下划线属性：{node.attr}")


def _child_env() -> dict[str, str]:
    """给子进程一个干净环境：不继承 API Key 等敏感变量。"""
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "LANG", "LC_ALL")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


@registry.register
class CodeExecutorSkill(BaseSkill):
    name = "execute_code"
    description = "在隔离子进程中执行 Python 代码并返回 stdout（仅限标准库算法/数据处理）。"
    dangerous = True
    parameters = [
        SkillParam(name="code", type="string", description="要执行的 Python 源码", required=True),
    ]

    async def execute(self, code: str, **kw: Any) -> SkillResult:  # type: ignore[override]
        if not config.ENABLE_CODE_EXEC:
            return SkillResult(
                success=False,
                error="代码执行已被禁用（ENABLE_CODE_EXEC=false）",
                metadata={"error_code": "disabled"},
            )
        if not code.strip():
            return SkillResult(success=False, error="code 为空", metadata={"error_code": "empty_code"})

        try:
            guard_code(code)
        except SyntaxError as exc:
            return SkillResult(
                success=False,
                error=f"语法错误：第 {exc.lineno} 行 {exc.msg}",
                metadata={"error_code": "syntax_error"},
            )
        except UnsafeCodeError as exc:
            return SkillResult(success=False, error=str(exc), metadata={"error_code": "unsafe_code"})

        started = time.perf_counter()
        timeout = float(config.CODE_EXEC_TIMEOUT)

        with tempfile.TemporaryDirectory(prefix="agent_exec_") as tmp:
            script = Path(tmp) / "snippet.py"
            script.write_text(code, encoding="utf-8")
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                str(script),
                cwd=tmp,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_child_env(),
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                _kill(proc)
                await proc.wait()
                return SkillResult(
                    success=False,
                    error=f"执行超时（>{timeout:g}s），子进程已终止",
                    metadata={"error_code": "timeout", "duration_ms": int((time.perf_counter() - started) * 1000)},
                )

        duration_ms = int((time.perf_counter() - started) * 1000)
        stdout = _clip(stdout_b.decode("utf-8", "replace"))
        stderr = _clip(stderr_b.decode("utf-8", "replace"))
        rc = proc.returncode or 0

        if rc != 0:
            detail = stderr or stdout or "(无输出)"
            return SkillResult(
                success=False,
                data=stdout or None,
                error=f"进程退出码 {rc}：{detail}",
                metadata={"error_code": "runtime_error", "returncode": rc, "duration_ms": duration_ms},
            )
        data = stdout if stdout else "(无输出)"
        if stderr:
            data += f"\n[stderr]\n{stderr}"
        return SkillResult(
            success=True,
            data=data,
            metadata={"returncode": rc, "duration_ms": duration_ms, "chars": len(stdout)},
        )


def _clip(text: str) -> str:
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + "\n...[输出已截断]"
    return text


def _kill(proc: asyncio.subprocess.Process) -> None:
    with contextlib.suppress(ProcessLookupError):
        proc.kill()


__all__ = ["CodeExecutorSkill", "guard_code", "UnsafeCodeError", "ALLOWED_MODULES"]
