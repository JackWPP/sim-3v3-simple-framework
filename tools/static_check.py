"""static_check.py —— 提交前静态门禁（两次 NameError 事故后的防线）。

背景
----
线上迭代连续踩到两类「静态可查但线上才爆」的坑：

1. v2.7 `_act_normal` presser 分支 lambda 里引用了未定义的局部变量 ``ball``
   （函数只绑定了 ``context.ball``），球一停每帧抛 ``NameError``；框架
   ``runtime._loop`` 捕获后对全员 ``p.stop()``，全队冻结。
2. v2.5 `_act_opp_kickoff` 加入门将粘滞逻辑时引用了 ``store``，但函数形参
   没有 ``store``、调用处也没传，每次对方开球 phase 每帧抛 ``NameError``。

两类问题都可由静态检查覆盖，本工具就是门禁：

- 规则①：模块级函数的调用参数个数 / 关键字与定义不匹配（多了、少了、
  未知关键字、同一参数重复传值）→ 报错。
- 规则②：函数/lambda 体内引用的「自由名」（如 ``store``/``ball``）既不是
  参数、也不是局部变量、也不在 module 全局 / star-import / builtins 里
  → 报错（运行时会 NameError）。

用法
----
    python3 tools/static_check.py                    # 默认检查 src/
    python3 tools/static_check.py --src src          # 指定策略源码目录
    python3 tools/static_check.py --src /tmp/x/src --json out.json
    python3 tools/static_check.py --git-ref 5f60659  # 检查历史 commit 的 src/（临时目录）

退出码：0 = 通过（STATIC_CHECK_OK）；1 = 有错误；2 = 参数/解析错误。
本工具只读源码，不 import 策略模块（不依赖容器内 SDK）。
"""

from __future__ import annotations

import argparse
import ast
import builtins
import json
import subprocess
import symtable
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 参与检查的策略源码（framework 是平台层，不改也不查）
DEFAULT_FILES = [
    "main.py",
    "player.py",
    "param.py",
    "utils/__init__.py",
    "utils/geom.py",
    "utils/obstacles.py",
    "utils/path_planner.py",
]

BUILTIN_NAMES = set(dir(builtins))


class FileCache:
    """按路径缓存 AST，避免重复 parse。"""

    def __init__(self) -> None:
        self._ast: dict[Path, ast.Module] = {}
        self._src: dict[Path, str] = {}

    def source(self, path: Path) -> str:
        if path not in self._src:
            self._src[path] = path.read_text(encoding="utf-8")
        return self._src[path]

    def tree(self, path: Path) -> ast.Module:
        if path not in self._ast:
            self._ast[path] = ast.parse(self.source(path), filename=str(path))
        return self._ast[path]


def _resolve_import_from(file: Path, node: ast.ImportFrom) -> Path | None:
    """把 ``from .param import *`` / ``from ..param import X`` 解析成本地 .py 路径。"""
    if node.level == 0:
        return None  # 绝对导入（外部包/标准库），不解析
    base = file.parent
    for _ in range(node.level - 1):
        base = base.parent
    parts = (node.module or "").split(".") if node.module else []
    candidate = base.joinpath(*parts).with_suffix(".py")
    if candidate.is_file():
        return candidate
    pkg = base.joinpath(*parts, "__init__.py")
    if pkg.is_file():
        return pkg
    return None


def module_level_names(file: Path, cache: FileCache, seen: set[Path] | None = None) -> set[str]:
    """模块级可见名字：symtable 根表 + 本地 star-import 的名字。"""
    seen = seen or set()
    if file in seen:
        return set()
    seen.add(file)
    src = cache.source(file)
    names: set[str] = set(symtable.symtable(src, str(file), "exec").get_identifiers())
    tree = cache.tree(file)
    for node in ast.walk(tree):
        # 只处理 module 顶层（以及 if TYPE_CHECKING: 之类的顶层块内）的 star import
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            dep = _resolve_import_from(file, node)
            if dep is not None:
                names |= module_level_names(dep, cache, seen)
    return names


def _function_params(args: ast.arguments) -> tuple[list[str], int, list[str], list[str]]:
    """返回 (位置参数名列表, 必填位置参数个数, 仅关键字参数名列表, 无默认值的仅关键字参数)。"""
    positional = [a.arg for a in list(args.posonlyargs) + list(args.args)]
    required = len(positional) - len(args.defaults)
    kwonly = [a.arg for a in args.kwonlyargs]
    kwonly_defaults = set(range(len(kwonly) - len(args.kw_defaults)))  # 粗糙但仅用于缺失提示
    kwonly_required = [
        name for i, name in enumerate(kwonly) if args.kw_defaults[i] is None
    ]
    del kwonly_defaults
    return positional, required, kwonly, kwonly_required


def collect_function_defs(
    files: list[Path], cache: FileCache, base: Path,
) -> dict[str, list[dict]]:
    """收集模块级函数定义（同名多处 → 调用检查标记 ambiguous）。"""
    defs: dict[str, list[dict]] = {}
    for file in files:
        tree = cache.tree(file)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            positional, required, kwonly, kwonly_required = _function_params(node.args)
            defs.setdefault(node.name, []).append(
                {
                    "file": str(file.relative_to(base)),
                    "line": node.lineno,
                    "positional": positional,
                    "required": required,
                    "kwonly": kwonly,
                    "kwonly_required": kwonly_required,
                    "vararg": node.args.vararg is not None,
                    "kwarg": node.args.kwarg is not None,
                }
            )
    return defs


def check_call_sites(
    files: list[Path], cache: FileCache, defs: dict[str, list[dict]], base: Path,
) -> list[str]:
    errors: list[str] = []
    unique = {name: items[0] for name, items in defs.items() if len(items) == 1}
    for file in files:
        for node in ast.walk(cache.tree(file)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            name = node.func.id
            if name not in unique:
                continue
            d = unique[name]
            if any(isinstance(a, ast.Starred) for a in node.args):
                continue  # 位置解包时无法静态校验个数
            positional = d["positional"]
            if not d["vararg"] and len(node.args) > len(positional):
                errors.append(
                    f"{file.relative_to(base)}:{node.lineno}: 调用 {name}() 传了 "
                    f"{len(node.args)} 个位置参数,但定义只接受 {len(positional)} 个"
                    f"（{d['file']}:{d['line']}）"
                )
            assigned = set(positional[: len(node.args)])
            seen_kw: set[str] = set()
            has_kwarg = any(k.arg is None for k in node.keywords)  # **kwargs
            for kw in node.keywords:
                if kw.arg is None or has_kwarg:
                    continue
                if kw.arg in seen_kw:
                    errors.append(
                        f"{file.relative_to(base)}:{node.lineno}: 调用 {name}() 关键字 "
                        f"参数 {kw.arg!r} 重复"
                    )
                seen_kw.add(kw.arg)
                if kw.arg in positional:
                    if kw.arg in assigned:
                        errors.append(
                            f"{file.relative_to(base)}:{node.lineno}: 调用 {name}() 参数 "
                            f"{kw.arg!r} 既按位置又按关键字传入（重复赋值）"
                        )
                    assigned.add(kw.arg)
                elif kw.arg not in d["kwonly"] and not d["kwarg"]:
                    errors.append(
                        f"{file.relative_to(base)}:{node.lineno}: 调用 {name}() 传了未知"
                        f"关键字参数 {kw.arg!r}（定义在 {d['file']}:{d['line']}）"
                    )
            missing = [
                p for p in positional[: d["required"]] if p not in assigned
            ]
            missing += [p for p in d["kwonly_required"] if p not in seen_kw]
            if missing and not d["vararg"]:
                errors.append(
                    f"{file.relative_to(base)}:{node.lineno}: 调用 {name}() 缺少必填参数 "
                    f"{missing}（定义在 {d['file']}:{d['line']}）"
                )
    return errors


def check_free_names(file: Path, cache: FileCache, base: Path) -> list[str]:
    """规则②：函数/lambda 体里的自由名必须在参数、局部、module 全局或 builtins 中。"""
    errors: list[str] = []
    src = cache.source(file)
    table = symtable.symtable(src, str(file), "exec")
    allowed = set(table.get_identifiers()) | BUILTIN_NAMES
    # star-import 进来的名字（例如 from .param import * 的全部常量）
    allowed |= module_level_names(file, cache)

    def walk(table, scope: str) -> None:
        for child in table.get_children():
            child_name = child.get_name()
            kind = child.get_type()  # 'function' | 'class' | 'lambda'
            if kind in ("function", "lambda"):
                func_label = "lambda" if kind == "lambda" else child_name
                for sym in child.get_symbols():
                    if (
                        sym.is_global()
                        and sym.is_referenced()
                        and sym.get_name() not in allowed
                    ):
                        errors.append(
                            f"{file.relative_to(base)}: 函数 {scope}{func_label}() 内引用了"
                            f"未定义的名字 {sym.get_name()!r}"
                            f"（既不是参数/局部变量，也不在 module 全局或 builtins 中）"
                        )
                walk(child, f"{scope}{func_label}.")
            else:
                walk(child, f"{scope}{child_name}.")

    walk(table, "")
    return errors


def run_check(src_dir: Path, cache: FileCache | None = None) -> dict:
    cache = cache or FileCache()
    files = [src_dir / rel for rel in DEFAULT_FILES if (src_dir / rel).is_file()]
    if not files:
        raise FileNotFoundError(f"{src_dir} 下找不到策略源码（main.py 等）")
    defs = collect_function_defs(files, cache, src_dir)
    call_errors = check_call_sites(files, cache, defs, src_dir)
    free_errors: list[str] = []
    for file in files:
        free_errors += check_free_names(file, cache, src_dir)
    return {
        "src": str(src_dir),
        "files": [str(f.relative_to(src_dir)) for f in files],
        "call_errors": call_errors,
        "free_name_errors": free_errors,
        "ok": not call_errors and not free_errors,
    }


def _src_from_git_ref(ref: str) -> Path:
    """把某个 commit 的 src/ 导出到临时目录，便于回归验证旧版本 bug。"""
    tmp = Path(tempfile.mkdtemp(prefix=f"static-check-{ref[:8]}-"))
    archive = subprocess.run(
        ["git", "archive", ref, "src"],
        cwd=ROOT, check=True, capture_output=True,
    )
    subprocess.run(["tar", "-x", "-C", str(tmp)], input=archive.stdout, check=True)
    return tmp / "src"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="策略源码提交前静态门禁")
    parser.add_argument("--src", default=str(ROOT / "src"), help="策略源码目录")
    parser.add_argument("--git-ref", default=None, help="检查某个 commit 的 src/（回归验证用）")
    parser.add_argument("--json", default=None, help="把结果写入 JSON 文件")
    args = parser.parse_args(argv)

    try:
        src_dir = _src_from_git_ref(args.git_ref) if args.git_ref else Path(args.src)
        result = run_check(src_dir, FileCache())
    except (FileNotFoundError, subprocess.CalledProcessError, SyntaxError) as exc:
        print(f"[static_check] 无法检查: {exc}")
        return 2

    if args.json:
        Path(args.json).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    for kind, label in (
        ("call_errors", "调用参数不匹配"),
        ("free_name_errors", "未定义自由名（运行时 NameError）"),
    ):
        for err in result[kind]:
            print(f"[FAIL] {label}: {err}")
    checked = ", ".join(result["files"])
    if result["ok"]:
        print(f"STATIC_CHECK_OK（{len(result['files'])} 个文件: {checked}）")
        return 0
    print(f"STATIC_CHECK_FAILED（{len(result['call_errors'])} 个调用错误, "
          f"{len(result['free_name_errors'])} 个未定义名）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
