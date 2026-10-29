"""AST-based code security policy (deny-list).

Skills are LLM-generated, so an allow-list of "safe" modules is a losing game:
every new stdlib module is a fresh escape route. Instead we deny the modules
and OS entry points that reach the network, spawn processes, or deserialize
attacker-controlled data, and let everything else through — including `open`,
which skills need for file I/O.
"""
import ast
import fnmatch

# Modules that can reach the network, spawn processes, or deserialize
# arbitrary objects. Checked against the first-level import root.
BANNED_IMPORTS = {
    # network
    "socket", "ssl", "urllib", "http", "requests", "aiohttp",
    "ftplib", "smtplib", "telnetlib", "poplib", "imaplib", "xmlrpc",
    # process / native code
    "subprocess", "multiprocessing", "ctypes", "pty", "webbrowser",
    # deserialization / dynamic execution
    "pickle", "marshal", "shelve", "importlib", "runpy", "dill",
}

# Direct references to dangerous builtins (calls or bare names).
BANNED_BUILTINS = {"exec", "eval", "compile", "__import__"}

# `os` attributes that execute programs or delete paths. `exec*`/`spawn*`
# are matched as patterns so every alias (execv, execve, execvpe, spawnlp...)
# is covered.
BANNED_OS_ATTRS = {"system", "popen", "remove", "unlink", "rmdir", "kill"}
BANNED_OS_ATTR_PATTERNS = ("exec*", "spawn*")

# Reference only — the modules historically treated as safe. Enforcement is
# the deny-list above (BANNED_IMPORTS); this set is kept for documentation
# and back-compat with callers that import it.
ALLOWED_IMPORTS = {
    "os", "sys", "json", "pathlib", "shutil",
    "datetime", "re", "math", "random", "collections",
    "typing", "itertools", "functools", "hashlib", "zipfile",
    "glob", "fnmatch", "string", "time",
}


def _is_banned_os_attr(name: str) -> bool:
    if name in BANNED_OS_ATTRS:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in BANNED_OS_ATTR_PATTERNS)


def _os_aliases(tree: ast.AST) -> set[str]:
    """Local names bound to the `os` module (covers `import os as o`).

    Only module imports bind an alias: names imported *from* os (e.g.
    `from os import path`) are checked directly at the import site, so a local
    variable that later reuses such a name is not treated as `os`.
    """
    aliases = {"os"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "os":
                    aliases.add(alias.asname or "os")
    return aliases


def validate_code(source: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return False, f"Syntax error: {e}"

    os_names = _os_aliases(tree)

    for node in ast.walk(tree):
        # Imports: reject banned modules (and banned names pulled from os).
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in BANNED_IMPORTS:
                    return False, f"Disallowed import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            root = mod.split(".")[0]
            if root in BANNED_IMPORTS:
                return False, f"Disallowed import: {mod}"
            if root == "os":
                for alias in node.names:
                    if _is_banned_os_attr(alias.name) or alias.name in BANNED_BUILTINS:
                        return False, f"Disallowed import: from os import {alias.name}"
        # Banned builtins (exec/eval/compile/__import__).
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BANNED_BUILTINS:
                return False, f"Disallowed builtin call: {node.func.id}"
        elif isinstance(node, ast.Name) and node.id in BANNED_BUILTINS:
            return False, f"Disallowed builtin reference: {node.id}"
        # os attribute access: os.system(...), os.remove(...), o.spawnv(...).
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in os_names:
                if _is_banned_os_attr(node.attr):
                    return False, f"Disallowed os attribute access: {node.attr}"

    return True, "Validation passed"
