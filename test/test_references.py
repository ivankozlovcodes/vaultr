"""Static reference resolution across kit/ and mods/: relative imports/re-exports, kit icon names, and mod commands.

Every check inspects static syntax (imports, string literals, and template prefixes) and cannot see names built at run
time, such as dynamic import(), variables or constants passed to icon(), or commands assembled by helpers/interpolation."""
import home_guard  # noqa: F401  (first: every test on a throwaway home)
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(home_guard.ROOT)
KIT_DIR = ROOT / "kit"
MODS_DIR = ROOT / "mods"
NODE = shutil.which("node")

KIT_JS = {p.name for p in KIT_DIR.glob("*.js")}
ALL_MODS = sorted(d.name for d in MODS_DIR.iterdir() if d.is_dir())

REGEX_PREV_WORDS = {
    "return", "throw", "case", "default", "delete", "void", "typeof", "in",
    "instanceof", "new", "else", "do", "yield", "await", "export", "of",
}
REGEX_PREV_PUNCT = set("(=,:;![?&|+-*%^~<>/{") | {
    "===", "!==", "==", "!=", "<=", ">=", "=>", "&&", "||", "??", "**", "...",
    "+=", "-=", "*=", "/=", "%=", "&&=", "||=", "??=",
}


def mod_own_files(mod_dir):
    is_ob = mod_dir.name.startswith("ob-")
    out = []
    for p in sorted(mod_dir.rglob("*")):
        if not p.is_file() or p.suffix not in (".js", ".mjs"):
            continue
        rel_mod = p.relative_to(mod_dir).as_posix()
        if "vendor" in rel_mod.split("/"):
            continue
        if is_ob and "/" not in rel_mod and p.name in KIT_JS:
            continue
        out.append(p)
    return out


def own_js_files(mods_dir=MODS_DIR, kit_dir=KIT_DIR, ob_only=False):
    files = sorted(kit_dir.glob("*.js")) if kit_dir.is_dir() else []
    if mods_dir.is_dir():
        for m in sorted(mods_dir.iterdir()):
            if not m.is_dir():
                continue
            if ob_only and not m.name.startswith("ob-"):
                continue
            files.extend(mod_own_files(m))
    return files


def lex_js(src):
    """Tokenize ES module JS source while skipping comments and balancing template interpolations."""
    tokens = []
    i = 0
    n = len(src)
    line = 1
    brace_depth = 0
    tpl_depths = []

    def prev_allows_regex():
        if not tokens:
            return True
        k, v, _ = tokens[-1]
        if k == "IDENT":
            return v in REGEX_PREV_WORDS
        if k == "PUNCT":
            return v in REGEX_PREV_PUNCT
        return k in ("TPL_HEAD", "TPL_MID")

    def read_tpl_chunk(start_idx, is_head):
        nonlocal line
        j = start_idx
        buf = []
        chunk_line = line
        while j < n:
            ch = src[j]
            if ch == "\\":
                if j + 1 < n:
                    esc = src[j + 1]
                    if esc == "\n":
                        line += 1
                    elif esc == "n":
                        buf.append("\n")
                    elif esc == "t":
                        buf.append("\t")
                    elif esc == "r":
                        buf.append("\r")
                    else:
                        buf.append(esc)
                    j += 2
                    continue
            if ch == "`":
                tokens.append(("TPL_STATIC" if is_head else "TPL_TAIL", "".join(buf), chunk_line))
                return j + 1
            if ch == "$" and j + 1 < n and src[j + 1] == "{":
                tokens.append(("TPL_HEAD" if is_head else "TPL_MID", "".join(buf), chunk_line))
                tpl_depths.append(brace_depth)
                return j + 2
            if ch == "\n":
                line += 1
            buf.append(ch)
            j += 1
        tokens.append(("TPL_TAIL", "".join(buf), chunk_line))
        return j

    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r\f\v":
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            nl = src.find("\n", i + 2)
            i = n if nl < 0 else nl
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            end = src.find("*/", i + 2)
            if end < 0:
                line += src[i:].count("\n")
                break
            line += src[i:end + 2].count("\n")
            i = end + 2
            continue
        if c == "/" and prev_allows_regex():
            j = i + 1
            in_cls = False
            while j < n:
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "[":
                    in_cls = True
                elif ch == "]" and in_cls:
                    in_cls = False
                elif ch == "/" and not in_cls:
                    j += 1
                    while j < n and src[j].isalpha():
                        j += 1
                    break
                elif ch == "\n":
                    break
                j += 1
            tokens.append(("REGEX", src[i:j], line))
            i = j
            continue
        if c in ('"', "'"):
            q = c
            j = i + 1
            chars = []
            str_line = line
            while j < n:
                ch = src[j]
                if ch == "\\":
                    if j + 1 < n:
                        esc = src[j + 1]
                        if esc == "n":
                            chars.append("\n")
                        elif esc == "t":
                            chars.append("\t")
                        elif esc == "r":
                            chars.append("\r")
                        elif esc == "\n":
                            line += 1
                        else:
                            chars.append(esc)
                        j += 2
                        continue
                if ch == q:
                    j += 1
                    break
                if ch == "\n":
                    line += 1
                chars.append(ch)
                j += 1
            tokens.append(("STRING", "".join(chars), str_line))
            i = j
            continue
        if c == "`":
            i = read_tpl_chunk(i + 1, is_head=True)
            continue
        if c == "{":
            brace_depth += 1
            tokens.append(("PUNCT", "{", line))
            i += 1
            continue
        if c == "}":
            if tpl_depths and tpl_depths[-1] == brace_depth:
                tpl_depths.pop()
                i = read_tpl_chunk(i + 1, is_head=False)
                continue
            brace_depth = max(0, brace_depth - 1)
            tokens.append(("PUNCT", "}", line))
            i += 1
            continue
        if c.isalpha() or c in "_$":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            tokens.append(("IDENT", src[i:j], line))
            i = j
            continue
        if c.isdigit():
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in "._"):
                j += 1
            tokens.append(("NUMBER", src[i:j], line))
            i = j
            continue
        for op in ("===", "!==", "==", "!=", "<=", ">=", "=>", "&&", "||", "??", "?.", "++", "--", "**", "..."):
            if src.startswith(op, i):
                tokens.append(("PUNCT", op, line))
                i += len(op)
                break
        else:
            tokens.append(("PUNCT", c, line))
            i += 1
    return tokens


def _extract_binding_names(toks, start, close_ch):
    """Parse `{ a, b: c = 1 }` or `[a, b]` destructuring bindings starting inside the opener."""
    names = set()
    j = start
    n = len(toks)
    depth = 1
    expect_key = close_ch == "}"
    while j < n and depth > 0:
        tk, tv, _ = toks[j]
        if tk == "PUNCT" and tv in ("{", "[", "("):
            if tv in ("{", "[") and not expect_key:
                sub, j = _extract_binding_names(toks, j + 1, "}" if tv == "{" else "]")
                names |= sub
                continue
            depth += 1
        elif tk == "PUNCT" and tv in ("}", "]", ")"):
            depth -= 1
            if depth == 0:
                return names, j + 1
        elif depth == 1 and tk == "PUNCT" and tv == ",":
            expect_key = close_ch == "}"
        elif depth == 1 and tk == "PUNCT" and tv == ":":
            expect_key = False
        elif depth == 1 and tk == "PUNCT" and tv == "=":
            j += 1
            ed = 0
            while j < n:
                ek, ev, _ = toks[j]
                if ek == "PUNCT" and ev in ("(", "[", "{"):
                    ed += 1
                elif ek == "PUNCT" and ev in (")", "]", "}"):
                    if ed == 0:
                        break
                    ed -= 1
                elif ed == 0 and ek == "PUNCT" and ev == ",":
                    break
                j += 1
            continue
        elif depth == 1 and tk == "IDENT":
            if close_ch == "}" and expect_key:
                if j + 1 < n and toks[j + 1][0] == "PUNCT" and toks[j + 1][1] == ":":
                    j += 1
                    continue
                names.add(tv)
                expect_key = False
            elif not expect_key:
                names.add(tv)
        j += 1
    return names, j


def parse_module_io(path):
    """Return (imports, exports, star_exports, reexport_checks) for an ES module file."""
    toks = lex_js(Path(path).read_text(encoding="utf-8"))
    imports = []
    exports = set()
    star_exports = []
    reexport_checks = []
    n = len(toks)
    depth = 0
    i = 0

    while i < n:
        k, v, ln = toks[i]
        if k == "PUNCT" and v in ("(", "[", "{"):
            depth += 1
            i += 1
            continue
        if k == "PUNCT" and v in (")", "]", "}"):
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and k == "IDENT" and v in ("import", "export"):
            if v == "import":
                if i + 1 < n and toks[i + 1][0] == "PUNCT" and toks[i + 1][1] in ("(", "."):
                    i += 1
                    continue
                j = i + 1
                if j < n and toks[j][0] == "STRING":
                    imports.append((toks[j][1], [], ln))
                    i = j + 1
                    continue
                names = []
                while j < n and not (toks[j][0] == "IDENT" and toks[j][1] == "from"):
                    if toks[j][0] == "PUNCT" and toks[j][1] == "{":
                        j += 1
                        while j < n and not (toks[j][0] == "PUNCT" and toks[j][1] == "}"):
                            if toks[j][0] in ("IDENT", "STRING"):
                                orig = toks[j][1]
                                if j + 2 < n and toks[j + 1][0] == "IDENT" and toks[j + 1][1] == "as":
                                    j += 3
                                else:
                                    j += 1
                                names.append((orig, ln))
                            else:
                                j += 1
                        j += 1
                    elif toks[j][0] == "PUNCT" and toks[j][1] == "*":
                        j += 1
                        if j + 1 < n and toks[j][0] == "IDENT" and toks[j][1] == "as":
                            j += 2
                    elif toks[j][0] == "IDENT":
                        names.append(("default", ln))
                        j += 1
                    else:
                        j += 1
                if j + 1 < n and toks[j][0] == "IDENT" and toks[j][1] == "from" and toks[j + 1][0] == "STRING":
                    imports.append((toks[j + 1][1], names, ln))
                    i = j + 2
                    continue
            else:
                j = i + 1
                if j >= n:
                    break
                if toks[j][0] == "IDENT" and toks[j][1] == "default":
                    exports.add("default")
                    i = j + 1
                    continue
                if toks[j][0] == "PUNCT" and toks[j][1] == "*":
                    j += 1
                    if j + 1 < n and toks[j][0] == "IDENT" and toks[j][1] == "as":
                        exports.add(toks[j + 1][1])
                        j += 2
                        if j + 1 < n and toks[j][0] == "IDENT" and toks[j][1] == "from" and toks[j + 1][0] == "STRING":
                            reexport_checks.append((toks[j + 1][1], [], ln))
                            i = j + 2
                            continue
                    elif j + 1 < n and toks[j][0] == "IDENT" and toks[j][1] == "from" and toks[j + 1][0] == "STRING":
                        star_exports.append((toks[j + 1][1], ln))
                        i = j + 2
                        continue
                if toks[j][0] == "PUNCT" and toks[j][1] == "{":
                    j += 1
                    pairs = []
                    while j < n and not (toks[j][0] == "PUNCT" and toks[j][1] == "}"):
                        if toks[j][0] in ("IDENT", "STRING"):
                            orig = toks[j][1]
                            alias = orig
                            if j + 2 < n and toks[j + 1][0] == "IDENT" and toks[j + 1][1] == "as":
                                alias = toks[j + 2][1]
                                j += 3
                            else:
                                j += 1
                            pairs.append((orig, alias))
                        else:
                            j += 1
                    j += 1
                    for _, alias in pairs:
                        exports.add(alias)
                    if j + 1 < n and toks[j][0] == "IDENT" and toks[j][1] == "from" and toks[j + 1][0] == "STRING":
                        reexport_checks.append((toks[j + 1][1], [(orig, ln) for orig, _ in pairs], ln))
                        i = j + 2
                        continue
                    i = j
                    continue
                if toks[j][0] == "IDENT" and toks[j][1] == "async":
                    j += 1
                if j < n and toks[j][0] == "IDENT" and toks[j][1] in ("function", "class"):
                    j += 1
                    if j < n and toks[j][0] == "PUNCT" and toks[j][1] == "*":
                        j += 1
                    if j < n and toks[j][0] == "IDENT":
                        exports.add(toks[j][1])
                        i = j + 1
                        continue
                if j < n and toks[j][0] == "IDENT" and toks[j][1] in ("const", "let", "var"):
                    j += 1
                    d = 0
                    expect_name = True
                    while j < n:
                        tk, tv, _ = toks[j]
                        if d == 0 and tk == "PUNCT" and tv == ";":
                            break
                        if d == 0 and expect_name and tk == "PUNCT" and tv in ("{", "["):
                            bound, j = _extract_binding_names(toks, j + 1, "}" if tv == "{" else "]")
                            exports |= bound
                            expect_name = False
                            continue
                        if tk == "PUNCT" and tv in ("(", "[", "{"):
                            d += 1
                            j += 1
                            continue
                        if tk == "PUNCT" and tv in (")", "]", "}"):
                            d = max(0, d - 1)
                            j += 1
                            continue
                        if d == 0 and tk == "PUNCT" and tv == ",":
                            expect_name = True
                            j += 1
                            continue
                        if d == 0 and tk == "PUNCT" and tv == "=":
                            expect_name = False
                            j += 1
                            continue
                        if d == 0 and expect_name and tk == "IDENT":
                            exports.add(tv)
                            expect_name = False
                            j += 1
                            continue
                        if d == 0 and not expect_name and tk == "IDENT" and tv in ("export", "import", "function", "class", "const", "let", "var"):
                            break
                        j += 1
                    i = j
                    continue
        i += 1
    return imports, exports, star_exports, reexport_checks


def resolve_exports(path, cache, visiting=None):
    rp = Path(path).resolve()
    if rp in cache:
        return cache[rp]
    if visiting is None:
        visiting = set()
    if rp in visiting:
        return set()
    visiting.add(rp)
    _, exps, stars, _ = parse_module_io(rp)
    all_exps = set(exps)
    for spec, _ in stars:
        if spec.startswith("."):
            target = (rp.parent / spec).resolve()
            if target.is_file():
                all_exps |= (resolve_exports(target, cache, visiting) - {"default"})
    cache[rp] = all_exps
    return all_exps


def check_imports(files, root=ROOT):
    cache = {}
    errors = []
    for f in files:
        rel = Path(f).relative_to(root).as_posix()
        imps, _, stars, reexps = parse_module_io(f)
        for spec, names, ln in imps + reexps:
            if not spec.startswith("."):
                continue
            target = (Path(f).parent / spec).resolve()
            if not target.is_file():
                errors.append(f"{rel}:{ln}: missing module {spec}")
                continue
            exported = resolve_exports(target, cache)
            for name, _ in names:
                if name not in exported:
                    errors.append(f"{rel}:{ln}: {spec} does not export {name!r}")
        for spec, ln in stars:
            if not spec.startswith("."):
                continue
            target = (Path(f).parent / spec).resolve()
            if not target.is_file():
                errors.append(f"{rel}:{ln}: missing module {spec}")
    return errors


def value_strings(toks, include_tpl_head=False):
    """Extract string literals (and optional template prefixes) in value-producing positions of an expression."""
    if not toks:
        return []
    while len(toks) >= 2 and toks[0][0] == "PUNCT" and toks[0][1] == "(" and toks[-1][0] == "PUNCT" and toks[-1][1] == ")":
        d = 0
        matched = True
        for idx, (k, v, _) in enumerate(toks):
            if k == "PUNCT" and v in ("(", "[", "{"):
                d += 1
            elif k == "PUNCT" and v in (")", "]", "}"):
                d -= 1
                if d == 0 and idx < len(toks) - 1:
                    matched = False
                    break
        if matched:
            toks = toks[1:-1]
        else:
            break
    if not toks:
        return []
    if len(toks) == 1 and toks[0][0] in ("STRING", "TPL_STATIC"):
        return [toks[0][1]]
    if include_tpl_head and toks[0][0] == "TPL_HEAD":
        return [toks[0][1]]
    d = 0
    q_idx = None
    t_depth = 0
    for idx, (k, v, _) in enumerate(toks):
        if k == "PUNCT" and v in ("(", "[", "{"):
            d += 1
        elif k == "PUNCT" and v in (")", "]", "}"):
            d -= 1
        elif d == 0 and k == "PUNCT":
            if v == "?":
                if q_idx is None:
                    q_idx = idx
                t_depth += 1
            elif v == ":" and q_idx is not None:
                t_depth -= 1
                if t_depth == 0:
                    return (value_strings(toks[q_idx + 1:idx], include_tpl_head)
                            + value_strings(toks[idx + 1:], include_tpl_head))
    for op in ("??", "||"):
        d = 0
        parts = []
        last = 0
        for idx, (k, v, _) in enumerate(toks):
            if k == "PUNCT" and v in ("(", "[", "{"):
                d += 1
            elif k == "PUNCT" and v in (")", "]", "}"):
                d -= 1
            elif d == 0 and k == "PUNCT" and v == op:
                parts.append(toks[last:idx])
                last = idx + 1
        if parts:
            parts.append(toks[last:])
            out = []
            for part in parts:
                out.extend(value_strings(part, include_tpl_head))
            return out
    d = 0
    last_and = None
    for idx, (k, v, _) in enumerate(toks):
        if k == "PUNCT" and v in ("(", "[", "{"):
            d += 1
        elif k == "PUNCT" and v in (")", "]", "}"):
            d -= 1
        elif d == 0 and k == "PUNCT" and v == "&&":
            last_and = idx
    if last_and is not None:
        return value_strings(toks[last_and + 1:], include_tpl_head)
    return []


def collect_first_arg(toks, open_paren_idx):
    d = 0
    j = open_paren_idx + 1
    out = []
    while j < len(toks):
        tk, tv, _ = toks[j]
        if tk == "PUNCT" and tv in ("(", "[", "{"):
            d += 1
        elif tk == "PUNCT" and tv in (")", "]", "}"):
            if d == 0:
                break
            d -= 1
        elif d == 0 and tk == "PUNCT" and tv == ",":
            break
        out.append(toks[j])
        j += 1
    return out


def collect_prop_value(toks, colon_idx):
    d = 0
    j = colon_idx + 1
    out = []
    while j < len(toks):
        tk, tv, _ = toks[j]
        if tk == "PUNCT" and tv in ("(", "[", "{"):
            d += 1
        elif tk == "PUNCT" and tv in (")", "]", "}"):
            if d == 0:
                break
            d -= 1
        elif d == 0 and tk == "PUNCT" and tv in (",", ";"):
            break
        out.append(toks[j])
        j += 1
    return out


def check_icons(files, icons_dir=KIT_DIR / "icons", root=ROOT):
    avail = {p.stem for p in icons_dir.glob("*.svg")}
    errors = []
    for f in files:
        rel = Path(f).relative_to(root).as_posix()
        toks = lex_js(Path(f).read_text(encoding="utf-8"))
        n = len(toks)
        for i, (k, v, ln) in enumerate(toks):
            if k == "IDENT" and v in ("icon", "iconPath") and i + 1 < n and toks[i + 1][0] == "PUNCT" and toks[i + 1][1] == "(":
                if i > 0 and toks[i - 1][1] in (".", "function"):
                    continue
                arg = collect_first_arg(toks, i + 1)
                for name in value_strings(arg):
                    if name not in avail:
                        errors.append(f"{rel}:{ln}: {v}({name!r}) has no kit/icons/{name}.svg")
            elif k == "IDENT" and v == "icon" and i + 1 < n and toks[i + 1][0] == "PUNCT" and toks[i + 1][1] == ":":
                if i > 0 and toks[i - 1][0] == "PUNCT" and toks[i - 1][1] in ("{", ","):
                    val = collect_prop_value(toks, i + 1)
                    for name in value_strings(val):
                        if name not in avail:
                            errors.append(f"{rel}:{ln}: icon: {name!r} has no kit/icons/{name}.svg")
    return errors


def load_table_commands():
    if not NODE:
        raise unittest.SkipTest("node is not installed")
    with tempfile.TemporaryDirectory(prefix="ref-cmds-") as folder:
        src_dir = MODS_DIR / "ob-settings"
        for p in src_dir.glob("*.js"):
            txt = p.read_text(encoding="utf-8").replace('from "herdr"', 'from "./herdr.js"')
            Path(folder, p.name).write_text(txt, encoding="utf-8")
        Path(folder, "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
        Path(folder, "herdr.js").write_text(
            'export const keys = () => [];\nexport const commands = () => [];\n'
            'export const window = () => ({ platform: "linux" });\n',
            encoding="utf-8",
        )
        code = (
            f'import {{ registry }} from "{Path(folder, "registry.js").as_uri()}";\n'
            f'import {{ VAULTR_COMMANDS }} from "{(MODS_DIR / "ob-switcher" / "commands.js").as_uri()}";\n'
            'const ob = registry().filter((r) => r.group === "Vaultr layout" || r.group === "Sessions panel").map((r) => r.action);\n'
            'const pal = VAULTR_COMMANDS.map((c) => c.route);\n'
            'process.stdout.write(JSON.stringify({ ob, pal }));\n'
        )
        out = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise AssertionError(out.stderr)
        data = json.loads(out.stdout)
    return data["ob"] + data["pal"]


def mod_command_index(mods_dir=MODS_DIR):
    info = {}
    if not mods_dir.is_dir():
        return info
    for m in sorted(mods_dir.iterdir()):
        if not m.is_dir():
            continue
        has_nc = False
        lits = set()
        for f in mod_own_files(m):
            toks = lex_js(f.read_text(encoding="utf-8"))
            for idx, (tk, tv, _) in enumerate(toks):
                if tk == "IDENT" and tv == "nextCommand" and idx + 1 < len(toks) and toks[idx + 1][1] == "(":
                    has_nc = True
                if tk in ("STRING", "TPL_STATIC"):
                    lits.add(tv)
        info[m.name] = (has_nc, lits)
    return info


def extract_code_commands(files, root=ROOT):
    out = []
    for f in files:
        rel = Path(f).relative_to(root).as_posix()
        toks = lex_js(Path(f).read_text(encoding="utf-8"))
        n = len(toks)
        for i, (k, v, ln) in enumerate(toks):
            if k == "IDENT" and v == "run" and i + 1 < n and toks[i + 1][0] == "PUNCT" and toks[i + 1][1] == "(":
                if i > 0 and toks[i - 1][1] in (".", "function"):
                    continue
                arg = collect_first_arg(toks, i + 1)
                for s in value_strings(arg, include_tpl_head=True):
                    out.append((f"{rel}:{ln}", "run()", s))
            elif k == "IDENT" and v == "command" and i + 1 < n and toks[i + 1][0] == "PUNCT" and toks[i + 1][1] == ":":
                if i > 0 and toks[i - 1][0] == "PUNCT" and toks[i - 1][1] in ("{", ","):
                    val = collect_prop_value(toks, i + 1)
                    for s in value_strings(val, include_tpl_head=True):
                        out.append((f"{rel}:{ln}", "command:", s))
    return out


def check_commands(sources, mods_info):
    errors = []
    known = set(mods_info)
    for loc, kind, cmd in sources:
        if not isinstance(cmd, str) or cmd.startswith("{"):
            continue
        head = cmd.split(":", 1)[0]
        if "." not in head:
            continue
        mod, verb = head.split(".", 1)
        if mod not in known and not mod.startswith("ob-"):
            continue
        if mod not in mods_info:
            errors.append(f"{loc} ({kind}): {cmd!r} targets missing mod {mod!r}")
            continue
        has_nc, lits = mods_info[mod]
        if not has_nc:
            errors.append(f"{loc} ({kind}): {cmd!r} targets {mod}, which has no nextCommand( loop")
        if verb and verb not in lits:
            errors.append(f"{loc} ({kind}): {cmd!r} -> {mod} has no string literal {verb!r}")
    return errors


class RepoReferences(unittest.TestCase):
    def test_relative_imports_and_reexports_resolve(self):
        """Every relative `import` and `export ... from` across kit/*.js and mods' own files names an existing file and
        exported bindings. Cannot see dynamic import() calls or paths built at run time."""
        self.assertEqual(check_imports(own_js_files()), [])

    def test_icon_literals_exist_in_kit_icons(self):
        """Every string literal reaching icon(), iconPath(), or an icon: property in kit/ and mods/ob-* own files has a
        matching SVG in kit/icons/. Cannot see icon names passed in variables, constants, or built at run time."""
        self.assertEqual(check_icons(own_js_files(ob_only=True)), [])

    def test_mod_commands_resolve_to_handler_and_verb(self):
        """Every Vaultr mod command in keys/vaultr-keys.json, OB/SESSIONS, VAULTR_COMMANDS, run(), and menu command:
        literals names a mod folder whose own files hold nextCommand( and the verb literal. Cannot see commands built
        at run time by helper wrappers or interpolated verb templates."""
        with open(ROOT / "keys" / "vaultr-keys.json", encoding="utf-8") as f:
            keys_data = json.load(f)
        sources = [
            (f"keys/vaultr-keys.json:{sec}", "keys", act)
            for sec, binds in keys_data.items()
            for act in binds.values()
        ]
        for act in load_table_commands():
            sources.append(("OB/SESSIONS/VAULTR_COMMANDS", "table", act))
        sources.extend(extract_code_commands(own_js_files()))
        self.assertEqual(check_commands(sources, mod_command_index()), [])


class ReferenceCheckerUnits(unittest.TestCase):
    def test_imports_check_catches_missing_file_and_missing_export(self):
        with tempfile.TemporaryDirectory(dir=home_guard.TMP) as tmp:
            root = Path(tmp)
            (root / "dep.js").write_text("export const a = 1; export default function d() {}\n", encoding="utf-8")
            (root / "re.js").write_text('export { a as b } from "./dep.js";\nexport * from "./dep.js";\n', encoding="utf-8")
            (root / "good.js").write_text(
                'import def, { a, b } from "./re.js";\nimport d from "./dep.js";\n',
                encoding="utf-8",
            )
            # good.js imports default from re.js (export * omits default), so that must fail; direct default passes.
            errs = check_imports([root / "good.js", root / "re.js"], root=root)
            self.assertEqual(len(errs), 1)
            self.assertIn("default", errs[0])

            (root / "bad.js").write_text('import { nope } from "./dep.js";\nimport "./missing.js";\n', encoding="utf-8")
            errs = check_imports([root / "bad.js"], root=root)
            self.assertEqual(len(errs), 2)

            (root / "destr.js").write_text("export const { x, y: z = 2 } = obj;\n", encoding="utf-8")
            (root / "use_destr.js").write_text('import { x, z } from "./destr.js";\n', encoding="utf-8")
            self.assertEqual(check_imports([root / "use_destr.js"], root=root), [])

    def test_icons_check_reads_value_branches_and_ignores_conditions(self):
        with tempfile.TemporaryDirectory(dir=home_guard.TMP) as tmp:
            root = Path(tmp)
            icons = root / "icons"
            icons.mkdir()
            (icons / "search.svg").write_text("<svg/>\n", encoding="utf-8")
            (icons / "info.svg").write_text("<svg/>\n", encoding="utf-8")
            (root / "ok.js").write_text(
                'const a = icon(mode === "not-an-icon" ? "search" : "info");\n'
                'const b = { icon: cond ? "search" : "info" };\n'
                'const c = iconPath("search");\n'
                'const d = icon(x ?? "info");\n'
                'const e = icon(flag && "search");\n'
                'const f = icon(`info`);\n',
                encoding="utf-8",
            )
            self.assertEqual(check_icons([root / "ok.js"], icons_dir=icons, root=root), [])

            (root / "bad.js").write_text(
                'icon("missing-a");\niconPath("missing-b");\nconst x = { icon: ok ? "search" : "missing-c" };\n',
                encoding="utf-8",
            )
            errs = check_icons([root / "bad.js"], icons_dir=icons, root=root)
            self.assertEqual(len(errs), 3)

    def test_commands_check_catches_missing_mod_loop_and_verb(self):
        with tempfile.TemporaryDirectory(dir=home_guard.TMP) as tmp:
            root = Path(tmp)
            mods = root / "mods"
            (mods / "ob-ok").mkdir(parents=True)
            (mods / "ob-ok" / "main.js").write_text('const c = await nextCommand(); if (c === "go") {}\n', encoding="utf-8")
            (mods / "ob-noloop").mkdir(parents=True)
            (mods / "ob-noloop" / "main.js").write_text('const v = "go";\n', encoding="utf-8")
            (mods / "caller").mkdir(parents=True)
            (mods / "caller" / "main.js").write_text(
                'run("ob-ok.go");\n'
                'run(`ob-ok.go:${x}`);\n'
                'run(`ob-ok.${x}`);\n'
                'run("ob-ghost.go");\n'
                'run(`ob-ghost.${x}`);\n'
                'run("ob-noloop.go");\n'
                'const m = { command: "ob-ok.missing" };\n'
                'run("pane.split", { direction: "right" });\n',
                encoding="utf-8",
            )
            info = mod_command_index(mods_dir=mods)
            cmds = extract_code_commands([mods / "caller" / "main.js"], root=root)
            errs = check_commands(cmds, info)
            self.assertEqual(len(errs), 4)
            self.assertEqual(sum("ob-ghost" in e for e in errs), 2)
            self.assertTrue(any("ob-noloop" in e for e in errs))
            self.assertTrue(any("missing" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
