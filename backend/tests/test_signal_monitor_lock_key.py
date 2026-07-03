"""Regression test for the ``lock_key`` UnboundLocalError in signal_monitor.

Bug: inside ``SignalMonitorService._check_signal_for_coin_sync`` the throttle-blocked
branches of the BUY and SELL paths referenced ``lock_key`` (``if lock_key in
self.alert_sending_locks: del ...``) BEFORE its first assignment
(``lock_key = f"{symbol}_BUY"`` / ``_SELL``). Because ``lock_key`` is assigned later
in the same function, Python treated it as a local throughout, so those earlier
references raised ``UnboundLocalError: cannot access local variable 'lock_key'`` and
aborted signal monitoring for the symbol every cycle.

Driving that ~4700-line method through real signals would need a very large amount of
mocking, so this guards the exact failure mode statically: a conservative
must-assigned dataflow analysis over the function's AST asserts that no ``Load`` of
``lock_key`` can be reached before it is definitely assigned on that path. The same
analysis flags the pre-fix code (at the four known lines) and passes on the fix.
"""
import ast
import inspect

from app.services.signal_monitor import SignalMonitorService

VAR = "lock_key"
FN = "_check_signal_for_coin_sync"


def _find_function(module_source: str, name: str):
    tree = ast.parse(module_source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def _use_before_assignment(fn_node) -> list[int]:
    """Return line numbers where VAR is loaded before it is definitely assigned."""
    problems: list[int] = []

    def loads_var(node):
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and n.id == VAR and isinstance(n.ctx, ast.Load):
                yield n

    def check_loads(node, assigned):
        if not assigned:
            for n in loads_var(node):
                problems.append(n.lineno)

    def stores_var(targets):
        for t in targets:
            for n in ast.walk(t):
                if isinstance(n, ast.Name) and n.id == VAR and isinstance(n.ctx, ast.Store):
                    return True
        return False

    def analyze(stmts, assigned):
        for s in stmts:
            if isinstance(s, ast.Assign):
                check_loads(s.value, assigned)
                if stores_var(s.targets):
                    assigned = True
            elif isinstance(s, ast.AugAssign):
                check_loads(s.value, assigned)
                check_loads(s.target, assigned)
            elif isinstance(s, ast.AnnAssign):
                if s.value is not None:
                    check_loads(s.value, assigned)
                    if isinstance(s.target, ast.Name) and s.target.id == VAR:
                        assigned = True
            elif isinstance(s, ast.If):
                check_loads(s.test, assigned)
                a_body = analyze(s.body, assigned)
                a_else = analyze(s.orelse, assigned) if s.orelse else assigned
                assigned = assigned or (a_body and a_else)
            elif isinstance(s, (ast.For, ast.AsyncFor)):
                check_loads(s.iter, assigned)
                analyze(s.body, assigned)      # body may run zero times
                analyze(s.orelse, assigned)
            elif isinstance(s, ast.While):
                check_loads(s.test, assigned)
                analyze(s.body, assigned)
                analyze(s.orelse, assigned)
            elif isinstance(s, (ast.With, ast.AsyncWith)):
                for item in s.items:
                    check_loads(item.context_expr, assigned)
                assigned = analyze(s.body, assigned)
            elif isinstance(s, ast.Try):
                analyze(s.body, assigned)      # body may raise partway through
                for h in s.handlers:
                    analyze(h.body, assigned)
                a_final = analyze(s.finalbody, assigned) if s.finalbody else assigned
                assigned = assigned or a_final
            else:
                for child in ast.iter_child_nodes(s):
                    check_loads(child, assigned)
        return assigned

    analyze(fn_node.body, False)
    return sorted(set(problems))


def test_lock_key_not_used_before_assignment():
    source = inspect.getsource(inspect.getmodule(SignalMonitorService))
    fn = _find_function(source, FN)
    offenders = _use_before_assignment(fn)
    assert offenders == [], (
        f"{VAR} is loaded before assignment in {FN}() at lines {offenders} "
        f"(UnboundLocalError regression)"
    )


def test_analysis_detects_a_known_bad_pattern():
    """Guard the guard: the analysis must flag a use-before-assignment it is meant to catch."""
    bad = (
        "def f(symbol):\n"
        "    if cond:\n"
        "        if lock_key in d:\n"
        "            del d[lock_key]\n"
        "        lock_key = f'{symbol}_BUY'\n"
    )
    fn = next(n for n in ast.walk(ast.parse(bad)) if isinstance(n, ast.FunctionDef))
    assert _use_before_assignment(fn), "analysis failed to flag a known bad pattern"
