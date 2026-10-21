"""
Math worker: exact computation with sympy, run as a SEPARATE process by accurate_solver.

Why separate: a hard parent timeout can kill runaway calculations, JARVIS itself never imports SymPy, and
expression parsing is isolated behind a whitelist. The model supplies expression strings, never Python code.
"""
from __future__ import annotations

import json
import re
import sys

MAX_EXPR = 400
MAX_OPS = 8


def _fail(msg: str) -> dict:
    return {"ok": False, "error": msg}


def main() -> None:
    try:
        import sympy as sp
        from sympy.parsing.sympy_parser import (
            parse_expr, standard_transformations, implicit_multiplication_application, convert_xor)
    except Exception as e:
        print(json.dumps({"results": [], "fatal": f"sympy is not installed ({e})"}))
        return

    deg = lambda x: x * sp.pi / 180
    FUNCS = {
        "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "cot": sp.cot, "sec": sp.sec, "csc": sp.csc,
        "asin": sp.asin, "acos": sp.acos, "atan": sp.atan, "atan2": sp.atan2, "arcsin": sp.asin,
        "arccos": sp.acos, "arctan": sp.atan, "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
        "asinh": sp.asinh, "acosh": sp.acosh, "atanh": sp.atanh,
        "exp": sp.exp, "log": sp.log, "ln": sp.log, "sqrt": sp.sqrt, "cbrt": sp.cbrt, "root": sp.root,
        "log10": lambda x: sp.log(x, 10), "log2": lambda x: sp.log(x, 2),
        "Abs": sp.Abs, "abs": sp.Abs, "sign": sp.sign, "floor": sp.floor, "ceiling": sp.ceiling,
        "factorial": sp.factorial, "binomial": sp.binomial, "nCr": sp.binomial,
        "nPr": lambda n, r: sp.factorial(n) / sp.factorial(n - r),
        "gcd": sp.gcd, "lcm": sp.lcm, "Min": sp.Min, "Max": sp.Max, "Mod": sp.Mod,
        "deg": deg, "Matrix": sp.Matrix, "Rational": sp.Rational, "Derivative": sp.Derivative,
        "Integral": sp.Integral,
    }
    CONSTS = {"pi": sp.pi, "E": sp.E, "I": sp.I, "oo": sp.oo, "e": sp.E}
    GREEK = {"alpha", "beta", "gamma", "theta", "phi", "omega", "mu", "sigma", "delta", "lam", "rho", "tau", "eps"}
    LOCALS = {**FUNCS, **CONSTS}
    GLOBALS = {"Integer": sp.Integer, "Float": sp.Float, "Rational": sp.Rational, "Symbol": sp.Symbol,
               "Function": sp.Function, **FUNCS, **CONSTS}
    TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)
    ALLOWED_CHARS = re.compile(r"^[A-Za-z0-9_+\-*/^().,=<>!\s|\[\]]*$")
    NUMBER = re.compile(r"\d+\.\d*|\.\d+")
    IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

    def check(text: str) -> str:
        text = str(text).strip()
        if not text: raise ValueError("empty expression")
        if len(text) > MAX_EXPR: raise ValueError("expression too long")
        if not ALLOWED_CHARS.match(text): raise ValueError("unsupported character in expression")
        if "__" in text or "." in NUMBER.sub("", text): raise ValueError("not allowed")
        for tok in IDENT.findall(text):
            if tok in LOCALS or tok in GREEK: continue
            if tok.isalpha() and len(tok) <= 3: continue
            if re.fullmatch(r"[A-Za-z]_?[0-9]", tok): continue
            raise ValueError(f"unknown name '{tok}' (write products with *)")
        return text

    def parse(text: str, extra: dict | None = None):
        t = check(text); local = dict(LOCALS)
        if extra: local.update(extra)
        return parse_expr(t, local_dict=local, global_dict=dict(GLOBALS), transformations=TRANSFORMS, evaluate=True)

    def parse_eq(text: str, extra=None):
        t = check(text)
        if "=" in t and not re.search(r"[<>!=]=|==", t) and t.count("=") == 1:
            lhs, rhs = t.split("=")
            return sp.Eq(parse(lhs, extra), parse(rhs, extra))
        return parse(t, extra)

    def var(name: str):
        name = str(name or "x").strip(); check(name)
        return sp.Symbol(name)

    def show(x) -> str:
        return str(x).replace("**", "^")

    def fmt_set(sol, v) -> str:
        name = str(v)
        if sol == sp.S.Reals: return f"{name} can be any real number"
        if sol == sp.S.EmptySet: return "no solution"
        if isinstance(sol, sp.Union): return "  or  ".join(fmt_set(a, v) for a in sol.args)
        if isinstance(sol, sp.Interval):
            lo, hi = sol.start, sol.end
            if lo == -sp.oo and hi == sp.oo: return f"{name} can be any real number"
            if lo == -sp.oo: return f"{name} {'<' if sol.right_open else '<='} {show(hi)}"
            if hi == sp.oo: return f"{name} {'>' if sol.left_open else '>='} {show(lo)}"
            return f"{show(lo)} {'<' if sol.left_open else '<='} {name} {'<' if sol.right_open else '<='} {show(hi)}"
        if isinstance(sol, sp.FiniteSet): return ", ".join(f"{name} = {show(x)}" for x in sol)
        if isinstance(sol, sp.ImageSet):
            lam = sol.lamda
            return f"{name} = {show(lam.expr).replace(str(lam.variables[0]), 'n')}  (n any integer)"
        return show(sol)

    def approx(x):
        try:
            if getattr(x, "free_symbols", None) or getattr(x, "is_Integer", False) or getattr(x, "is_Float", False):
                return None
            v = sp.N(x, 12); s = str(v)
            return None if s == show(x) else s
        except Exception: return None

    def numeric_ok(expr, tol=1e-8) -> bool:
        try: return abs(complex(sp.N(expr, 20))) < tol
        except Exception: return False

    def do_eval(o):
        r = parse(o["expr"])
        if o.get("numeric") and getattr(r, "free_symbols", None):
            raise ValueError("result still contains unknown names: " + ", ".join(sorted(map(str, r.free_symbols))))
        r = sp.simplify(r) if r.free_symbols else r
        return {"ok": True, "exact": show(r), "approx": approx(r)}

    def do_transform(o):
        e = parse(o["expr"])
        fn = {"simplify": sp.simplify, "expand": sp.expand, "factor": sp.factor}[o["op"]]
        return {"ok": True, "exact": show(fn(e))}

    def do_solve(o):
        eqs_in = o.get("eqs") or [o.get("expr")]
        eqs = [parse_eq(q) for q in eqs_in if q]
        vars_ = [var(v) for v in (o.get("vars") or [])] or sorted(
            set().union(*[getattr(q, "free_symbols", set()) for q in eqs]), key=str)
        if not vars_: raise ValueError("nothing to solve for")
        real = str(o.get("domain", "real")).lower() != "complex"
        if len(eqs) == 1 and len(vars_) == 1 and not isinstance(eqs[0], bool):
            q, v = eqs[0], vars_[0]
            try: sol = sp.solveset(q, v, domain=sp.S.Reals if real else sp.S.Complexes)
            except Exception: sol = sp.solve(q, v)
            if isinstance(sol, sp.Set) and sol.is_FiniteSet: values = list(sol)
            elif isinstance(sol, (list, tuple)): values = list(sol)
            else: return {"ok": True, "exact": fmt_set(sol, v), "approx": None, "verified": None}
            checks = []
            for val in values:
                try:
                    lhs = (q.lhs - q.rhs) if isinstance(q, sp.Eq) else q
                    checks.append(numeric_ok(lhs.subs(v, val)) if not isinstance(q, sp.core.relational.Relational)
                                  or isinstance(q, sp.Eq) else True)
                except Exception: checks.append(False)
            exact = ", ".join(f"{v} = {show(x)}" for x in values) or "no solution"
            ap = ", ".join(f"{v} ≈ {approx(x)}" for x in values if approx(x)) or None
            return {"ok": True, "exact": exact, "approx": ap, "verified": (all(checks) if values else None)}
        sol = sp.solve(eqs, vars_, dict=True)
        if not sol: return {"ok": True, "exact": "no solution", "approx": None, "verified": None}
        outs, ok_all = [], True
        for s_ in sol:
            outs.append(", ".join(f"{k} = {show(v)}" for k, v in s_.items()))
            for q in eqs:
                lhs = (q.lhs - q.rhs) if isinstance(q, sp.Eq) else q
                ok_all &= numeric_ok(lhs.subs(s_))
        return {"ok": True, "exact": " | ".join(outs), "approx": None, "verified": ok_all}

    def do_diff(o):
        r = sp.diff(parse(o["expr"]), var(o.get("var")), int(o.get("order") or 1))
        return {"ok": True, "exact": show(r), "approx": None}

    def do_integrate(o):
        e, v = parse(o["expr"]), var(o.get("var"))
        if o.get("lower") not in (None, "") and o.get("upper") not in (None, ""):
            r = sp.integrate(e, (v, parse(str(o["lower"])), parse(str(o["upper"]))))
        else: r = sp.integrate(e, v)
        return {"ok": True, "exact": show(r) + ("" if o.get("lower") not in (None, "") else " + C"), "approx": approx(r)}

    def do_limit(o):
        r = sp.limit(parse(o["expr"]), var(o.get("var")), parse(str(o.get("point", 0))), str(o.get("dir", "+-")))
        return {"ok": True, "exact": show(r), "approx": approx(r)}

    def do_series(o):
        r = sp.series(parse(o["expr"]), var(o.get("var")), parse(str(o.get("point", 0))), int(o.get("n") or 6))
        return {"ok": True, "exact": show(r.removeO()) + " + O(...)", "approx": None}

    def do_sum(o):
        r = sp.summation(parse(o["expr"]), (var(o.get("var", "k")), parse(str(o["lower"])), parse(str(o["upper"]))))
        return {"ok": True, "exact": show(r), "approx": approx(r)}

    def do_matrix(o):
        a = parse(o["a"]); kind = o["op"]
        if kind == "det": r = a.det()
        elif kind == "inverse": r = a.inv()
        elif kind == "rank": r = a.rank()
        elif kind == "transpose": r = a.T
        elif kind == "eigen": r = a.eigenvals()
        elif kind == "matmul": r = a * parse(o["b"])
        else: raise ValueError("unknown matrix operation")
        return {"ok": True, "exact": show(r), "approx": None}

    def do_stats(o):
        data = [sp.nsimplify(str(x)) for x in o["data"][:2000]]
        if not data: raise ValueError("no data")
        n = len(data); mean = sum(data) / n; var_p = sum((x - mean) ** 2 for x in data) / n
        var_s = sum((x - mean) ** 2 for x in data) / (n - 1) if n > 1 else sp.nan
        srt = sorted(data)
        med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
        out = {"count": n, "sum": sum(data), "mean": mean, "median": med, "min": srt[0], "max": srt[-1],
               "variance(population)": var_p, "stdev(population)": sp.sqrt(var_p),
               "variance(sample)": var_s, "stdev(sample)": sp.sqrt(var_s) if n > 1 else sp.nan}
        txt = "; ".join(f"{k} = {show(sp.N(v, 10)) if k != 'count' else v}" for k, v in out.items())
        return {"ok": True, "exact": txt, "approx": None}

    def do_number(o):
        kind = o["op"]; n = sp.Integer(str(o.get("n")))
        if abs(n) > 10 ** 30: raise ValueError("number too large for this operation")
        if kind == "factorint":
            r = sp.factorint(n)
            return {"ok": True, "exact": " * ".join(f"{p}^{e}" if e > 1 else str(p) for p, e in r.items()) or str(n)}
        if kind == "isprime": return {"ok": True, "exact": "prime" if sp.isprime(n) else "not prime"}
        if kind == "divisors":
            d = sp.divisors(n)
            return {"ok": True, "exact": f"{len(d)} divisors: " + ", ".join(map(str, d[:60]))}
        raise ValueError("unknown number operation")

    def do_dsolve(o):
        f = sp.Function(str(o.get("func", "f"))); x = var(o.get("var", "x"))
        eq = parse_eq(o["expr"], {str(o.get("func", "f")): f})
        r = sp.dsolve(eq, f(x))
        return {"ok": True, "exact": show(r), "approx": None}

    OPS = {
        "eval": do_eval, "simplify": do_transform, "expand": do_transform, "factor": do_transform,
        "solve": do_solve, "diff": do_diff, "integrate": do_integrate, "limit": do_limit,
        "series": do_series, "sum": do_sum, "det": do_matrix, "inverse": do_matrix, "rank": do_matrix,
        "transpose": do_matrix, "eigen": do_matrix, "matmul": do_matrix, "stats": do_stats,
        "factorint": do_number, "isprime": do_number, "divisors": do_number, "dsolve": do_dsolve,
    }
    try:
        payload = json.loads(sys.stdin.read() or "{}"); ops = payload.get("ops") or []
    except Exception as e:
        print(json.dumps({"results": [], "fatal": f"bad input: {e}"})); return
    results = []
    for o in ops[:MAX_OPS]:
        try:
            fn = OPS.get(str(o.get("op")))
            if fn is None:
                results.append(_fail(f"unknown operation '{o.get('op')}'")); continue
            r = fn(o); r["op"] = o.get("op"); results.append(r)
        except Exception as e:
            results.append({"ok": False, "op": o.get("op"), "error": f"{type(e).__name__}: {str(e)[:160]}"})
    print(json.dumps({"results": results}))


if __name__ == "__main__":
    main()
