"""AST-gated sandbox for user-supplied backtest strategies.

User strategy code runs as ``generate(data, params) -> positions`` where
``positions`` is a Series/list of ints in {0, 1} aligned to the data rows.
Execution happens in a subprocess (hard timeout, no way to touch the host
process), and every node of the code is validated against an allowlist before
it runs — imports, lambdas, exceptions, dunder/private attribute access and all
dangerous builtins are rejected up front. Built-in strategies never pass
through here (see ``strategies.py``).
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

_BACKEND_ROOT = str(Path(__file__).resolve().parents[3])

MAX_CODE_CHARS = 40_000
MAX_AST_DEPTH = 30

_SAFE_BUILTINS: dict = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "len": len, "range": range, "enumerate": enumerate, "zip": zip,
    "sorted": sorted, "reversed": reversed, "any": any, "all": all,
    "list": list, "tuple": tuple, "dict": dict, "set": set,
    "bool": bool, "int": int, "float": float, "str": str, "pow": pow,
    "isinstance": isinstance, "filter": filter, "map": map,
    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "RuntimeError": RuntimeError, "ZeroDivisionError": ZeroDivisionError,
    "IndexError": IndexError, "ArithmeticError": ArithmeticError,
}

_ALLOWED_ATTRS: frozenset[str] = frozenset({
    # pandas frame/series access + vectorized ops (df, pd, np share this list;
    # attributes a given object does not have simply raise AttributeError)
    "open", "high", "low", "close", "volume", "timestamp", "date",
    "index", "columns", "values", "shape", "ndim", "size", "dtype", "name", "T",
    "iloc", "loc", "iat", "at", "dt",
    "rolling", "ewm", "diff", "clip", "fillna", "dropna", "astype", "shift",
    "pct_change", "cumsum", "cumprod", "mean", "std", "var", "min", "max",
    "sum", "median", "quantile", "abs", "round", "head", "tail", "reset_index",
    "drop", "isna", "notna", "isnull", "notnull", "corr", "cov", "rank",
    "prod", "count", "idxmax", "idxmin", "apply", "map", "groupby",
    "sort_index", "sort_values", "resample", "copy", "unique", "nunique",
    "describe", "first_valid_index", "last_valid_index", "to_numpy",
    "between", "clip_lower", "clip_upper", "crossing", "ge", "le", "gt", "lt",
    "get", "keys", "items", "values",
    # numpy constants
    "pi", "e", "inf", "nan", "newaxis",
})

_ALLOWED_NP_FUNCS: frozenset[str] = frozenset({
    "abs", "sqrt", "log", "log10", "log1p", "exp", "sign", "clip", "maximum",
    "minimum", "mean", "std", "var", "sum", "cumsum", "cumprod", "diff", "roll",
    "nanmean", "nanstd", "nanmax", "nanmin", "nanpercentile", "percentile",
    "where", "select", "linspace", "arange", "zeros", "ones", "full",
    "full_like", "reshape", "argmax", "argmin", "floor", "ceil", "trunc",
    "sin", "cos", "tan", "arctan", "arctan2", "power", "square", "absolute",
    "corrcoef", "cov", "unique", "flip", "concatenate", "stack", "repeat",
})

_ALLOWED_NODES: tuple = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.FunctionDef,
    ast.arguments, ast.arg, ast.Return, ast.If, ast.IfExp, ast.Compare,
    ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Call, ast.Attribute, ast.Subscript,
    ast.Slice, ast.Name, ast.Load, ast.Store, ast.Constant, ast.Tuple,
    ast.List, ast.Dict, ast.Set, ast.keyword, ast.For, ast.While, ast.Break,
    ast.Continue, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
    ast.comprehension, ast.operator, ast.unaryop, ast.cmpop,
)

_FORBIDDEN_NODES = (
    ast.Import, ast.ImportFrom, ast.Lambda, ast.ClassDef, ast.Global,
    ast.Nonlocal, ast.Try, ast.TryStar, ast.Raise, ast.Assert, ast.With,
    ast.NamedExpr, ast.Starred, ast.Yield, ast.YieldFrom, ast.Await,
    ast.AsyncFunctionDef, ast.Del, ast.Delete, ast.AnnAssign, ast.Match,
)


class StrategySandboxError(Exception):
    pass


def _collect_target_names(node: ast.AST, defined: set[str]) -> None:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            defined.add(child.id)


def _defined_names(tree: ast.AST) -> set[str]:
    """Names that may legally be referenced: function params, loop targets,
    comprehension iterators and assignment targets."""
    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            defined.add(node.name)
            for a in node.args.args:
                defined.add(a.arg)
            for extra in (node.args.posonlyargs, node.args.kwonlyargs):
                for a in extra:
                    defined.add(a.arg)
            if node.args.vararg:
                defined.add(node.args.vararg.arg)
            if node.args.kwarg:
                defined.add(node.args.kwarg.arg)
        elif isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                _collect_target_names(t, defined)
        elif isinstance(node, ast.For):
            _collect_target_names(node.target, defined)
        elif isinstance(node, ast.comprehension):
            _collect_target_names(node.target, defined)
    return defined


def _depth(node: ast.AST) -> int:
    d = 0
    for child in ast.iter_child_nodes(node):
        d = max(d, 1 + _depth(child))
    return d


def validate_ast(code: str) -> list[str]:
    """Return a list of human-readable violations (empty == allowed)."""
    violations: list[str] = []
    if not code.strip():
        return ["strategy code is empty"]
    if len(code) > MAX_CODE_CHARS:
        violations.append(f"strategy code too large ({len(code)} > {MAX_CODE_CHARS} chars)")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:  # pragma: no cover - exercised via string
        return [f"syntax error: {exc}"]
    if _depth(tree) > MAX_AST_DEPTH:
        violations.append(f"expression nesting exceeds {MAX_AST_DEPTH}")
    defined = _defined_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_NODES):
            violations.append(f"forbidden construct: {type(node).__name__} at line {getattr(node, 'lineno', '?')}")
            continue
        if not isinstance(node, _ALLOWED_NODES):
            violations.append(f"unsupported node: {type(node).__name__} at line {getattr(node, 'lineno', '?')}")
            continue
        if isinstance(node, ast.Attribute):
            if not node.attr.isidentifier() or node.attr.startswith("_") or node.attr not in _ALLOWED_ATTRS:
                violations.append(f"forbidden attribute access: .{node.attr} at line {node.lineno}")
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute):
                if fn.attr not in _ALLOWED_ATTRS and fn.attr not in _ALLOWED_NP_FUNCS:
                    violations.append(f"forbidden method call: .{fn.attr}() at line {fn.lineno}")
            elif isinstance(fn, ast.Name):
                if fn.id not in _SAFE_BUILTINS and fn.id not in ("df", "np", "pd", "params", "generate"):
                    violations.append(f"forbidden call: {fn.id}() at line {fn.lineno}")
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            allowed_names = set(_SAFE_BUILTINS) | {"df", "np", "pd", "params", "generate"}
            if node.id not in allowed_names and node.id not in defined:
                violations.append(f"unknown identifier: {node.id} at line {node.lineno}")
    return violations


def _positions_from_result(result, n_rows: int) -> list[int]:
    if isinstance(result, pd.Series):
        result = result.tolist()
    elif isinstance(result, np.ndarray):
        result = result.tolist()
    if not isinstance(result, list):
        raise StrategySandboxError("generate() must return a list / Series / ndarray of 0/1")
    if len(result) != n_rows:
        raise StrategySandboxError(f"generate() returned {len(result)} positions for {n_rows} rows")
    out = []
    for i, v in enumerate(result):
        try:
            v = int(v)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise StrategySandboxError(f"position {i} is not an integer: {v!r}") from exc
        if v not in (0, 1):
            raise StrategySandboxError(f"position {i} is {v}, expected 0 or 1")
        out.append(v)
    return out


def _child_main(code_path: str, df_path: str, params_json: str) -> int:
    """Runs inside the sandbox subprocess; prints JSON to stdout."""
    result: dict = {}
    try:
        code = Path(code_path).read_text(encoding="utf-8")
        violations = validate_ast(code)
        if violations:
            result = {"ok": False, "error": "; ".join(violations[:10])}
            print(json.dumps(result))
            return 0
        df = pd.read_csv(df_path, index_col=0)
        params = json.loads(params_json or "{}")
        if not isinstance(params, dict):
            params = {}
        globs = {
            "__builtins__": _SAFE_BUILTINS,
            "df": df,
            "np": np,
            "pd": pd,
            "params": params,
        }
        compiled = compile(code, "<user_strategy>", "exec")
        exec(compiled, globs)
        generate = globs.get("generate")
        if not callable(generate):
            result = {"ok": False, "error": "your code must define a generate(data, params) function"}
            print(json.dumps(result))
            return 0
        try:
            positions = generate(df, params)
        except TypeError:
            try:
                positions = generate(df)
            except TypeError:
                result = {"ok": False, "error": "generate() must accept (data) or (data, params)"}
                print(json.dumps(result))
                return 0
        result = {"ok": True, "positions": _positions_from_result(positions, len(df))}
    except Exception as exc:  # noqa: BLE001 - report back to the parent
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(limit=5)}
    print(json.dumps(result))
    return 0


def _child_script() -> str:
    return (
        "import json, sys; sys.path.insert(0, %r);\n"
        "from app.services.backtesting.sandbox import _child_main;\n"
        "rc = _child_main(sys.argv[1], sys.argv[2], sys.argv[3]);\n"
        "sys.exit(rc)"
    ) % _BACKEND_ROOT


def run_user_strategy(
    code: str,
    df: pd.DataFrame,
    params: dict | None = None,
    *,
    timeout: float = 20.0,
    use_subprocess: bool = True,
) -> pd.Series:
    """Validate and execute user strategy code; returns a 0/1 position Series."""
    violations = validate_ast(code)
    if violations:
        raise StrategySandboxError("; ".join(violations[:10]))

    def _inline() -> pd.Series:
        globs = {
            "__builtins__": _SAFE_BUILTINS,
            "df": df,
            "np": np,
            "pd": pd,
            "params": dict(params or {}),
        }
        exec(compile(code, "<user_strategy>", "exec"), globs)  # noqa: S102 - validated above
        generate = globs.get("generate")
        if not callable(generate):
            raise StrategySandboxError("your code must define a generate(data, params) function")
        try:
            positions = generate(df, dict(params or {}))
        except TypeError:
            positions = generate(df)
        return pd.Series(_positions_from_result(positions, len(df)), index=df.index)

    if not use_subprocess:
        return _inline()

    df_path = ""
    code_path = ""
    try:
        tmpdir = tempfile.mkdtemp(prefix="stockos_strategy_")
        df_path = os.path.join(tmpdir, "data.csv")
        code_path = os.path.join(tmpdir, "code.py")
        df.to_csv(df_path)
        Path(code_path).write_text(code, encoding="utf-8")
        script = _child_script()
        proc = subprocess.run(
            [sys.executable, "-c", script, code_path, df_path, json.dumps(params or {})],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_BACKEND_ROOT,
            check=False,
        )
        try:
            payload = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise StrategySandboxError(
                f"sandbox returned invalid output: {proc.stdout[:200]!r} / {proc.stderr[:200]!r}"
            ) from exc
        if not payload.get("ok"):
            raise StrategySandboxError(str(payload.get("error", "unknown sandbox error")))
        return pd.Series(payload["positions"], index=df.index, dtype=int)
    except subprocess.TimeoutExpired as exc:
        raise StrategySandboxError(f"strategy execution timed out after {timeout}s") from exc
    finally:
        for p in (df_path, code_path):
            try:
                if p:
                    os.remove(p)
            except OSError:
                pass
        if "tmpdir" in locals():
            try:
                os.rmdir(tmpdir)
            except OSError:
                pass
