"""静态检查策略代码里引用了但未定义的全大写常量(防 KEEPER_STAND_OFF_M 类 NameError)。

不 import 策略模块(依赖容器内 booster_agent_framework)，只静态解析 AST，
并把 src/param.py 的全局名字当作 from .param import * 的可见范围。

用法: python3 tools/check_names.py
"""
import ast
import builtins
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_param_names():
    spec = importlib.util.spec_from_file_location("_param_check", ROOT / "src/param.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {n for n in vars(mod) if not n.startswith("_")}


def module_globals(path, param_names, extra_import_names):
    tree = ast.parse(Path(path).read_text())
    names = set(dir(builtins)) | set(param_names) | set(extra_import_names)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.If):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    names.add(sub.id)
    return names


def check(path, param_names, extra_import_names):
    tree = ast.parse(Path(path).read_text())
    known = module_globals(path, param_names, extra_import_names)
    unknown = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            n = node.id
            if n not in known and n.isupper():
                unknown.setdefault(n, node.lineno)
    return unknown


def main():
    param_names = load_param_names()
    # 容器内置模块的导入名(本地没有,静态放行)
    external = {"booster_agent_framework", "AgentBase", "SoccerAgentMixin"}
    bad = False
    for path in (ROOT / "src/player.py", ROOT / "src/main.py"):
        for name, line in sorted(check(path, param_names, external).items(), key=lambda kv: kv[1]):
            print(f"{path.relative_to(ROOT)}:{line}: 未定义常量 {name}")
            bad = True
    print("CHECK_FAIL" if bad else "CHECK_OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
