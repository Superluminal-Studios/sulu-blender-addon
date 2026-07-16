"""Translate Blender's bl_ui panel code into a declarative layout document.

Blender ships its properties-editor UI as plain Python (`bl_ui/*.py`, plus
`cycles/ui.py` inside the Cycles add-on). Those files follow strong
conventions — mixin classes carrying `bl_context`/`COMPAT_ENGINES`, panel
classes with `bl_label`/`bl_parent_id`, and `draw()` bodies that alias RNA
structs (``cscene = scene.cycles``) and emit rows via ``layout.prop(...)``
behind simple ``if`` conditions.

This module abstract-interprets that code with the stdlib ``ast`` module and
emits a JSON-safe "layout document": the panel tree plus ordered items whose
visibility/enabled state is a small expression language over scene-relative
RNA paths. The web UI evaluates those expressions against the job's values
snapshot to reproduce what the user actually sees in Blender — including
which rows appear for the chosen engine/denoiser/etc.

Pure stdlib; bpy is only used by :func:`collect_layout` to locate the UI
sources of the running Blender. Everything is failure-tolerant: a panel that
cannot be translated is dropped (recorded in ``warnings``), and a total
failure returns ``None`` so submission proceeds without a layout.

Path conventions match the settings schema/values snapshot:
  * scene-relative: ``"render.fps"``, ``"cycles.samples"``
  * active-view-layer-relative: ``"@layer.use_pass_z"``

Expression language (consumed by sulu-ui ``blender-layout.ts``):
  {"op":"const","value":bool}
  {"op":"get","path":P}                      truthiness of a value
  {"op":"not"|"and"|"or","args":[...]}
  {"op":"eq"|"ne"|"lt"|"le"|"gt"|"ge","path":P,"value":json}
  {"op":"in"|"not_in","path":P,"values":[...]}
  {"op":"unknown","why":str}                 renderer treats as True
"""

from __future__ import annotations

import ast
import os
from typing import Any, Optional

_LAYOUT_VERSION = 1
_TARGET_CONTEXTS = ("render", "output", "view_layer")
_MAX_INLINE_DEPTH = 3

# Layout factory methods returning sub-layouts we keep walking into.
_CONTAINER_METHODS = {
    "column", "row", "box", "split", "grid_flow", "column_flow",
}
# Calls that emit nothing we can render; recorded as skipped nodes.
_SKIP_CALL_PREFIXES = (
    "template_", "operator", "menu", "popover", "prop_search",
    "prop_enum", "prop_with_popover", "prop_decorator", "prop_tabs_enum",
    "draw_panel_header", "label_multiline", "progress",
)


def _unknown(why: str) -> dict:
    return {"op": "unknown", "why": str(why)[:120]}


def _const(value: bool) -> dict:
    return {"op": "const", "value": bool(value)}


def _and(*exprs: Optional[dict]) -> Optional[dict]:
    parts = [e for e in exprs if e is not None]
    parts = [e for e in parts if not (e.get("op") == "const" and e.get("value"))]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return {"op": "and", "args": parts}


def _not(expr: dict) -> dict:
    if expr.get("op") == "not":
        return expr["args"][0]
    if expr.get("op") == "const":
        return _const(not expr["value"])
    if expr.get("op") == "unknown":
        return expr
    return {"op": "not", "args": [expr]}


class _Path:
    """Symbolic RNA datablock reference, e.g. '' (scene) or 'cycles'."""

    __slots__ = ("path",)

    def __init__(self, path: str):
        self.path = path

    def child(self, name: str) -> "_Path":
        return _Path(f"{self.path}.{name}" if self.path else name)


class _LayoutRef:
    """Symbolic UILayout handle; emits into a shared item list."""

    __slots__ = ("items", "visible", "enabled")

    def __init__(self, items: list, visible: Optional[dict], enabled: Optional[dict]):
        self.items = items
        self.visible = visible
        self.enabled = enabled


class _Unknown:
    __slots__ = ("why",)

    def __init__(self, why: str = ""):
        self.why = why


class _PanelInfo:
    __slots__ = (
        "name", "label", "parent", "context", "space", "engines", "order",
        "default_closed", "hide_header", "draw", "draw_header", "poll",
        "bases", "skip", "lineno", "module", "methods",
    )

    def __init__(self, name: str, module: str, lineno: int):
        self.name = name
        self.module = module
        self.lineno = lineno
        self.label: Optional[str] = None
        self.parent: Optional[str] = None
        self.context: Optional[str] = None
        self.space: Optional[str] = None
        self.engines: Optional[list] = None
        self.order: Optional[int] = None
        self.default_closed = False
        self.hide_header = False
        self.draw: Optional[ast.FunctionDef] = None
        self.draw_header: Optional[ast.FunctionDef] = None
        self.poll: Optional[ast.FunctionDef] = None
        self.bases: list[str] = []
        self.skip = False
        # every method, for inlining self.X(...) / Class.X(...) draw helpers
        self.methods: dict[str, ast.FunctionDef] = {}


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _base_names(cls: ast.ClassDef) -> list[str]:
    names = []
    for base in cls.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


class _Module:
    def __init__(self, name: str, tree: ast.Module):
        self.name = name
        self.functions: dict[str, ast.FunctionDef] = {}
        self.classes: dict[str, _PanelInfo] = {}
        # Blender registers panels from the module-level `classes = (...)`
        # tuple — that order, not class definition order, is the UI order
        self.class_order: dict[str, int] = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                self.functions[node.name] = node
            elif isinstance(node, ast.ClassDef):
                self.classes[node.name] = _parse_class(node, name)
            elif (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "classes"
                and isinstance(node.value, (ast.Tuple, ast.List))
            ):
                self.class_order = {
                    elt.id: i
                    for i, elt in enumerate(node.value.elts)
                    if isinstance(elt, ast.Name)
                }

    def ordered_class_names(self) -> list:
        names = list(self.classes.keys())
        if not self.class_order:
            return names
        fallback = len(self.class_order)
        return sorted(
            names,
            key=lambda n: self.class_order.get(n, fallback + names.index(n)),
        )


def _parse_class(cls: ast.ClassDef, module: str) -> _PanelInfo:
    info = _PanelInfo(cls.name, module, cls.lineno)
    info.bases = _base_names(cls)
    for node in cls.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            value = _literal(node.value)
            if name == "bl_label" and isinstance(value, str):
                info.label = value
            elif name == "bl_parent_id" and isinstance(value, str):
                info.parent = value
            elif name == "bl_context" and isinstance(value, str):
                info.context = value
            elif name == "bl_space_type" and isinstance(value, str):
                info.space = value
            elif name == "bl_order" and isinstance(value, int):
                info.order = value
            elif name == "bl_options" and isinstance(value, (set, frozenset, tuple, list)):
                options = set(value)
                info.default_closed = "DEFAULT_CLOSED" in options
                info.hide_header = "HIDE_HEADER" in options
            elif name == "COMPAT_ENGINES" and isinstance(value, (set, frozenset, tuple, list)):
                info.engines = sorted(str(v) for v in value)
        elif isinstance(node, ast.FunctionDef):
            info.methods[node.name] = node
            if node.name == "draw":
                info.draw = node
            elif node.name == "draw_header":
                info.draw_header = node
            elif node.name == "poll":
                info.poll = node
    return info


class _Translator:
    """Abstract interpreter for one panel's draw/draw_header/poll bodies."""

    def __init__(self, registry: "_Registry", layer_root: bool, methods: Optional[dict] = None):
        self.registry = registry
        # In view_layer-context panels, context.view_layer maps to @layer.
        self.layer_root = layer_root
        # the translated panel's own (inheritance-resolved) methods, for
        # inlining self.draw_xxx(...) helpers
        self.methods = methods or {}
        self.warnings: list[str] = []
        # Visibility of the branch currently being walked. Blender code emits
        # through container refs captured BEFORE an `if` (col = layout.column()
        # … if x: col.prop(...)), so branch visibility must be interpreter
        # state, not a property of the layout handle.
        self.visible_ctx: Optional[dict] = None
        self.inline_depth = 0

    # ---- symbolic expression evaluation -------------------------------

    def sym(self, node: ast.AST, env: dict) -> Any:
        if isinstance(node, ast.Name):
            return env.get(node.id, _Unknown(f"name:{node.id}"))
        if isinstance(node, ast.Attribute):
            base = self.sym(node.value, env)
            attr = node.attr
            if isinstance(base, _ContextRef):
                if attr == "scene":
                    return _Path("")
                if attr == "view_layer":
                    return _Path("@layer")
                if attr == "engine":
                    return _Path("render.engine")
                return _Unknown(f"context.{attr}")
            if isinstance(base, _Path):
                return base.child(attr)
            if isinstance(base, _SelfRef):
                if attr == "layout":
                    return env.get("@self_layout", _Unknown("self.layout"))
                return _Unknown(f"self.{attr}")
            return _Unknown(f"attr:{attr}")
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
            values = [self.sym(item, env) for item in node.elts]
            if all(not isinstance(v, (_Unknown, _Path, _LayoutRef)) for v in values):
                return list(values)
            return _Unknown("collection")
        if isinstance(node, ast.Call):
            return self.sym_call(node, env)
        if isinstance(node, ast.BoolOp) or isinstance(node, ast.UnaryOp) or isinstance(node, ast.Compare):
            # condition-position expressions handled by cond(); as a value → unknown
            return _Unknown("boolexpr")
        return _Unknown(type(node).__name__)

    def sym_call(self, node: ast.Call, env: dict) -> Any:
        func = node.func
        if isinstance(func, ast.Attribute):
            base = self.sym(func.value, env)
            if isinstance(base, _LayoutRef) and func.attr in _CONTAINER_METHODS:
                # containers share the parent's item list unless they carry a
                # heading (rendered as a labeled group)
                heading = None
                for kw in node.keywords:
                    if kw.arg == "heading":
                        value = _literal(kw.value)
                        if isinstance(value, str) and value:
                            heading = value
                if heading:
                    group = {"t": "group", "heading": heading, "items": []}
                    visible = _and(base.visible, self.visible_ctx)
                    if visible is not None:
                        group["visible"] = visible
                    if base.enabled:
                        group["enabled"] = base.enabled
                    base.items.append(group)
                    return _LayoutRef(group["items"], None, None)
                return _LayoutRef(base.items, base.visible, base.enabled)
        return _Unknown("call")

    # ---- condition translation ----------------------------------------

    def cond(self, node: ast.AST, env: dict, depth: int = 0) -> dict:
        if depth > 6:
            return _unknown("depth")
        if isinstance(node, ast.BoolOp):
            parts = [self.cond(v, env, depth + 1) for v in node.values]
            op = "and" if isinstance(node.op, ast.And) else "or"
            return {"op": op, "args": parts}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return _not(self.cond(node.operand, env, depth + 1))
        if isinstance(node, ast.Compare):
            return self.cond_compare(node, env)
        if isinstance(node, ast.Call):
            return self.cond_call(node, env, depth)
        if isinstance(node, ast.Constant):
            return _const(bool(node.value))
        value = self.sym(node, env)
        if isinstance(value, _Path):
            return {"op": "get", "path": value.path}
        if isinstance(value, _Unknown):
            return _unknown(value.why)
        if isinstance(value, (bool, int, float, str)):
            return _const(bool(value))
        return _unknown("value")

    def cond_compare(self, node: ast.Compare, env: dict) -> dict:
        if len(node.ops) != 1 or len(node.comparators) != 1:
            return _unknown("chained-compare")
        left = self.sym(node.left, env)
        right_node = node.comparators[0]
        op = node.ops[0]
        right = _literal(right_node)
        if right is None and not (isinstance(right_node, ast.Constant) and right_node.value is None):
            right_sym = self.sym(right_node, env)
            if isinstance(right_sym, (bool, int, float, str, list)):
                right = right_sym
            else:
                return _unknown("compare-rhs")
        if not isinstance(left, _Path):
            # allow reversed constant-vs-path comparisons
            if isinstance(left, (bool, int, float, str)):
                left_sym = self.sym(right_node, env)
                if isinstance(left_sym, _Path) and isinstance(op, (ast.Eq, ast.NotEq)):
                    kind = "eq" if isinstance(op, ast.Eq) else "ne"
                    return {"op": kind, "path": left_sym.path, "value": left}
            return _unknown("compare-lhs")
        if isinstance(op, (ast.In, ast.NotIn)):
            if isinstance(right, (set, frozenset, tuple, list)):
                kind = "in" if isinstance(op, ast.In) else "not_in"
                return {"op": kind, "path": left.path, "values": sorted(str(v) for v in right)}
            return _unknown("in-rhs")
        kind = {
            ast.Eq: "eq", ast.NotEq: "ne", ast.Lt: "lt",
            ast.LtE: "le", ast.Gt: "gt", ast.GtE: "ge",
        }.get(type(op))
        if kind is None:
            return _unknown("compare-op")
        if isinstance(right, (set, frozenset)):
            right = sorted(right)
        return {"op": kind, "path": left.path, "value": right}

    def cond_call(self, node: ast.Call, env: dict, depth: int) -> dict:
        # Pure single-return helper functions get inlined; device/preference
        # probes (and anything else) degrade to unknown → shown.
        if isinstance(node.func, ast.Name):
            fn = self.registry.functions.get(node.func.id)
            if fn is not None and depth < _MAX_INLINE_DEPTH:
                body = [s for s in fn.body if not isinstance(s, (ast.Expr,)) or not isinstance(s.value, ast.Constant)]
                if len(body) == 1 and isinstance(body[0], ast.Return) and body[0].value is not None:
                    params = [a.arg for a in fn.args.args]
                    inner_env = dict(env)
                    for param, arg in zip(params, node.args):
                        inner_env[param] = self.sym(arg, env)
                    # context param keeps flowing through helpers
                    for param in params:
                        if param == "context" and param not in [a.arg for a in fn.args.args[:len(node.args)]]:
                            inner_env.setdefault("context", env.get("context"))
                    return self.cond(body[0].value, inner_env, depth + 1)
            return _unknown(f"call:{node.func.id}")
        if isinstance(node.func, ast.Attribute):
            return _unknown(f"call:{node.func.attr}")
        return _unknown("call")

    # ---- statement walking ---------------------------------------------

    def walk(self, statements: list, env: dict, layout: _LayoutRef, depth: int = 0) -> None:
        outer_ctx = self.visible_ctx
        guard: Optional[dict] = None  # accumulated early-return inversions
        for stmt in statements:
            self.visible_ctx = _and(outer_ctx, guard)
            if isinstance(stmt, ast.Assign):
                self.stmt_assign(stmt, env, layout)
            elif isinstance(stmt, ast.AugAssign):
                continue
            elif isinstance(stmt, ast.Expr):
                self.stmt_expr(stmt, env, layout)
            elif isinstance(stmt, ast.If):
                early = self.stmt_if(stmt, env, layout, depth)
                if early is not None:
                    guard = _and(guard, early)
            elif isinstance(stmt, ast.Return):
                break
            elif isinstance(stmt, (ast.For, ast.While, ast.With, ast.Try)):
                self.emit(layout, {"t": "skipped", "kind": type(stmt).__name__.lower()})
            # imports, pass, del, etc: ignore
        self.visible_ctx = outer_ctx

    def stmt_assign(self, stmt: ast.Assign, env: dict, layout: _LayoutRef) -> None:
        value = self.sym(stmt.value, env)
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                env[target.id] = value
            elif isinstance(target, ast.Attribute):
                base = self.sym(target.value, env)
                if isinstance(base, _LayoutRef) and target.attr in ("active", "enabled"):
                    cond = self.cond(stmt.value, env)
                    base.enabled = _and(base.enabled, cond)
                elif isinstance(base, _LayoutRef) and target.attr == "active_default":
                    continue
                # use_property_split / alignment / scale_y …: ignore
            elif isinstance(target, ast.Tuple):
                for el in target.elts:
                    if isinstance(el, ast.Name):
                        env[el.id] = _Unknown("tuple-assign")

    def emit(self, layout: _LayoutRef, node: dict) -> None:
        visible = _and(layout.visible, self.visible_ctx, node.get("visible"))
        if visible is not None:
            node["visible"] = visible
        enabled = _and(layout.enabled, node.get("enabled"))
        if enabled is not None:
            node["enabled"] = enabled
        layout.items.append(node)

    def stmt_expr(self, stmt: ast.Expr, env: dict, layout: _LayoutRef) -> None:
        call = stmt.value
        if not isinstance(call, ast.Call):
            return
        func = call.func
        if isinstance(func, ast.Name):
            # module-level draw helper: inline with mapped arguments
            fn = self.registry.functions.get(func.id)
            if fn is not None:
                self.inline_draw_helper(fn, call, env, layout)
            return
        if not isinstance(func, ast.Attribute):
            return
        base = self.sym(func.value, env)
        if not isinstance(base, _LayoutRef):
            # self.draw_xxx(...) / SomeClass.draw_xxx(...) static draw helpers
            helper = None
            if isinstance(base, _SelfRef):
                helper = self.methods.get(func.attr)
            elif isinstance(func.value, ast.Name):
                owner = self.registry.classes.get(func.value.id)
                if owner is not None:
                    helper = owner.methods.get(func.attr)
            if helper is not None:
                self.inline_draw_helper(helper, call, env, layout)
            return
        method = func.attr
        if method == "prop":
            self.emit_prop(call, env, base)
        elif method == "label":
            text = self.kwarg(call, "text", 0)
            if isinstance(text, str) and text:
                self.emit(base, {"t": "label", "text": text})
        elif method.startswith("separator"):
            self.emit(base, {"t": "sep"})
        elif method in _CONTAINER_METHODS:
            # bare container call for side effects (rare)
            self.sym_call(call, env)
        elif method == "template_image_settings":
            # C-side template drawing the image format block; expand to the
            # schema's struct props so the actual output settings render
            target = self.sym(call.args[0], env) if call.args else None
            if isinstance(target, _Path):
                self.emit(base, {"t": "struct_props", "path": target.path})
            else:
                self.emit(base, {"t": "skipped", "kind": method})
        elif method.startswith(_SKIP_CALL_PREFIXES):
            self.emit(base, {"t": "skipped", "kind": method})
        # everything else (context_pointer_set, etc.): ignore

    def inline_draw_helper(self, fn: ast.FunctionDef, call: ast.Call, env: dict, layout: _LayoutRef) -> None:
        if self.inline_depth >= _MAX_INLINE_DEPTH:
            return
        params = [a.arg for a in fn.args.args]
        # bound/class methods: self/cls is not part of the call args
        if params and params[0] in ("self", "cls", "_self", "_cls"):
            inner_self = {params[0]: _SelfRef() if params[0].endswith("self") else _Unknown("cls")}
            params = params[1:]
        else:
            inner_self = {}
        inner: dict = {"context": env.get("context"), **inner_self}
        layout_param = None
        for param, arg in zip(params, call.args):
            value = self.sym(arg, env)
            inner[param] = value
            if isinstance(value, _LayoutRef) and layout_param is None:
                layout_param = param
        if layout_param is None:
            # helpers usually take (layout, context); without a layout there
            # is nothing to emit into
            return
        self.inline_depth += 1
        try:
            self.walk(fn.body, inner, inner[layout_param], depth=1)
        finally:
            self.inline_depth -= 1

    def kwarg(self, call: ast.Call, name: str, position: Optional[int] = None) -> Any:
        for kw in call.keywords:
            if kw.arg == name:
                return _literal(kw.value)
        if position is not None and len(call.args) > position:
            return _literal(call.args[position])
        return None

    def emit_prop(self, call: ast.Call, env: dict, layout: _LayoutRef) -> None:
        if len(call.args) < 2:
            return
        target = self.sym(call.args[0], env)
        prop_name = _literal(call.args[1])
        if not isinstance(target, _Path) or not isinstance(prop_name, str):
            layout.items.append({"t": "skipped", "kind": "prop"})
            return
        node: dict = {"t": "prop", "path": target.child(prop_name).path}
        text = None
        has_text = False
        for kw in call.keywords:
            if kw.arg == "text":
                has_text = True
                text = _literal(kw.value)
            elif kw.arg == "expand" and _literal(kw.value) is True:
                # Blender draws the enum as a row of buttons instead of a menu
                node["expand"] = True
        if has_text:
            node["text"] = text if isinstance(text, str) else None
        self.emit(layout, node)

    def stmt_if(
        self, stmt: ast.If, env: dict, layout: _LayoutRef, depth: int
    ) -> Optional[dict]:
        """Walk both branches with complementary visibility. Returns a guard
        to apply to the REST of the body when the branch early-returns."""
        if depth > 12:
            return None
        test = self.cond(stmt.test, env)
        body = stmt.body
        is_early_return = (
            len(body) == 1 and isinstance(body[0], ast.Return) and not stmt.orelse
        )
        if is_early_return:
            return _not(test)

        saved = self.visible_ctx
        self.visible_ctx = _and(saved, test)
        self.walk(body, dict(env), layout, depth + 1)
        if stmt.orelse:
            self.visible_ctx = _and(saved, _not(test))
            self.walk(stmt.orelse, dict(env), layout, depth + 1)
        self.visible_ctx = saved
        return None

    # ---- entry points ----------------------------------------------------

    def run_draw(self, fn: ast.FunctionDef) -> list:
        items: list = []
        root = _LayoutRef(items, None, None)
        env = {
            "self": _SelfRef(),
            "context": _ContextRef(),
            "@self_layout": root,
        }
        # bind def draw(self, context) param names
        params = [a.arg for a in fn.args.args]
        if params:
            env[params[0]] = env["self"]
        if len(params) > 1:
            env[params[1]] = env["context"]
        env["layout"] = root  # common alias even before assignment
        self.walk(fn.body, env, root)
        return items

    def run_header_toggle(self, fn: ast.FunctionDef) -> Optional[str]:
        items = self.run_draw(fn)
        for node in items:
            if node.get("t") == "prop":
                return node["path"]
        return None

    def run_poll(self, fn: ast.FunctionDef) -> Optional[dict]:
        """Translate a poll classmethod into a condition (best-effort)."""
        body = [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
            return _unknown("poll-body")
        env = {"context": _ContextRef(), "cls": _Unknown("cls")}
        params = [a.arg for a in fn.args.args]
        if params:
            env[params[0]] = _Unknown("cls")
        if len(params) > 1:
            env[params[1]] = env["context"]
        return self.cond(body[0].value, env)


class _ContextRef:
    __slots__ = ()


class _SelfRef:
    __slots__ = ()


class _Registry:
    """Cross-module function/class registry (cycles imports from bl_ui)."""

    def __init__(self, modules: list[_Module]):
        self.functions: dict[str, ast.FunctionDef] = {}
        self.classes: dict[str, _PanelInfo] = {}
        for module in modules:
            self.functions.update(module.functions)
            self.classes.update(module.classes)


def _poll_marks_dev_only(
    fn: ast.FunctionDef,
    registry: Optional["_Registry"] = None,
    depth: int = 0,
) -> bool:
    source_names = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    if source_names & {"show_developer_ui", "use_cycles_debug", "experimental"}:
        return True
    if registry is None or depth >= 3:
        return False
    # Composed polls delegate the gate: `return Mixin.poll(context) and …`
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "poll"
            and isinstance(node.func.value, ast.Name)
        ):
            base = registry.classes.get(node.func.value.id)
            if (
                base is not None
                and base.poll is not None
                and base.poll is not fn
                and _poll_marks_dev_only(base.poll, registry, depth + 1)
            ):
                return True
    return False


def _poll_is_engine_gate_only(fn: ast.FunctionDef) -> bool:
    """True for the ubiquitous `return context.engine in cls.COMPAT_ENGINES`."""
    body = [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return False
    value = body[0].value
    if isinstance(value, ast.Compare) and len(value.ops) == 1 and isinstance(value.ops[0], ast.In):
        comparator = value.comparators[0]
        if isinstance(comparator, ast.Attribute) and comparator.attr == "COMPAT_ENGINES":
            return True
    # `return context.scene` style truthiness gates
    if isinstance(value, ast.Attribute) and value.attr in ("scene", "view_layer"):
        return True
    return False


def _resolve_inheritance(info: _PanelInfo, registry: _Registry, seen: Optional[set] = None) -> None:
    seen = seen or set()
    for base_name in info.bases:
        if base_name in ("Panel", "object") or base_name in seen:
            continue
        seen.add(base_name)
        base = registry.classes.get(base_name)
        if base is None:
            if base_name in ("PresetPanel", "Menu", "UIList", "PropertyPanel"):
                info.skip = True
            continue
        _resolve_inheritance(base, registry, seen)
        if base.skip:
            info.skip = True
        if info.context is None:
            info.context = base.context
        if info.space is None:
            info.space = base.space
        if info.parent is None:
            info.parent = base.parent
        if info.engines is None:
            info.engines = base.engines
        if info.poll is None:
            info.poll = base.poll
        if info.draw is None and base.draw is not None:
            info.draw = base.draw
        for method_name, method in base.methods.items():
            info.methods.setdefault(method_name, method)


def build_layout(sources: dict[str, str]) -> Optional[dict]:
    """Translate {module_name: python_source} into a layout document.

    Module order determines panel order. Returns None when nothing could be
    translated.
    """
    modules = []
    for name, source in sources.items():
        try:
            modules.append(_Module(name, ast.parse(source)))
        except SyntaxError:
            continue
    if not modules:
        return None
    registry = _Registry(modules)

    panels = []
    warnings: list[str] = []
    for module in modules:
        for class_name in module.ordered_class_names():
            info = module.classes[class_name]
            try:
                _resolve_inheritance(info, registry)
                # mixins carry no bl_label; Menus/UILists/PresetPanels are
                # marked skip during inheritance resolution
                if "Panel" not in info.bases:
                    continue
                if info.skip or info.label is None or info.context not in _TARGET_CONTEXTS:
                    continue
                # 3D-viewport panels (e.g. Cycles' shading popovers) reuse the
                # buttons mixins but never appear in the properties editor
                if info.space is not None and info.space != "PROPERTIES":
                    continue
                if info.poll is not None and _poll_marks_dev_only(info.poll, registry):
                    continue
                translator = _Translator(
                    registry,
                    layer_root=info.context == "view_layer",
                    methods=info.methods,
                )
                items: list = []
                if info.draw is not None:
                    items = translator.run_draw(info.draw)
                header_toggle = None
                if info.draw_header is not None:
                    header_toggle = translator.run_header_toggle(info.draw_header)
                poll_expr = None
                if info.poll is not None and not _poll_is_engine_gate_only(info.poll):
                    poll_expr = translator.run_poll(info.poll)
                    if poll_expr is not None and poll_expr.get("op") == "const" and poll_expr.get("value"):
                        poll_expr = None
                panel: dict = {
                    "id": info.name,
                    "label": info.label,
                    "context": info.context,
                    "parent": info.parent,
                    "items": items,
                }
                if info.engines is not None:
                    panel["engines"] = info.engines
                if info.order is not None:
                    panel["order"] = info.order
                if info.default_closed:
                    panel["default_closed"] = True
                if info.hide_header:
                    panel["hide_header"] = True
                if header_toggle:
                    panel["header_toggle"] = header_toggle
                if poll_expr is not None:
                    panel["poll"] = poll_expr
                panels.append(panel)
            except Exception as exc:  # noqa: BLE001 — never break submission
                warnings.append(f"{info.name}: {exc}")

    if not panels:
        return None
    _apply_external_engine_adoption(panels, registry)
    doc: dict = {"layout_version": _LAYOUT_VERSION, "panels": panels}
    if warnings:
        doc["warnings"] = warnings[:20]
    return doc


def _apply_external_engine_adoption(panels: list, registry: _Registry) -> None:
    """Replicate Cycles' runtime panel adoption.

    cycles/ui.py's register() adds 'CYCLES' to every panel whose
    COMPAT_ENGINES contains 'BLENDER_RENDER' (minus an exclude list inside
    its get_panels()). Static translation can't see that mutation, so the
    same rule is applied here — otherwise the core Output/Color Management
    panels vanish for Cycles jobs.
    """
    get_panels = registry.functions.get("get_panels")
    has_cycles = any(
        info.engines and "CYCLES" in info.engines
        for info in registry.classes.values()
    )
    if get_panels is None or not has_cycles:
        return
    excludes: set[str] = set()
    for node in ast.walk(get_panels):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "exclude_panels"
        ):
            value = _literal(node.value)
            if isinstance(value, (set, frozenset, tuple, list)):
                excludes = {str(v) for v in value}
    for panel in panels:
        engines = panel.get("engines")
        if (
            engines
            and "BLENDER_RENDER" in engines
            and "CYCLES" not in engines
            and panel["id"] not in excludes
        ):
            panel["engines"] = sorted([*engines, "CYCLES"])


def collect_layout(bpy_module: Any = None) -> Optional[dict]:
    """Locate the running Blender's UI sources and translate them."""
    try:
        if bpy_module is None:
            import bpy as bpy_module  # type: ignore
        scripts_dir = bpy_module.utils.system_resource("SCRIPTS")
        bl_ui = os.path.join(scripts_dir, "startup", "bl_ui")
        ordered = [
            ("properties_render", os.path.join(bl_ui, "properties_render.py")),
            ("properties_output", os.path.join(bl_ui, "properties_output.py")),
            ("properties_view_layer", os.path.join(bl_ui, "properties_view_layer.py")),
        ]
        for addons_dir_name in ("addons_core", "addons"):
            cycles_ui = os.path.join(scripts_dir, addons_dir_name, "cycles", "ui.py")
            if os.path.isfile(cycles_ui):
                ordered.append(("cycles_ui", cycles_ui))
                break
        sources: dict[str, str] = {}
        for name, path in ordered:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    sources[name] = handle.read()
            except OSError:
                continue
        if not sources:
            return None
        return build_layout(sources)
    except Exception:  # noqa: BLE001 — submission must never depend on this
        return None
