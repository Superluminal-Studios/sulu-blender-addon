import ast
import types
from pathlib import Path


ADDON_INIT = Path(__file__).resolve().parents[1] / "__init__.py"


def _load_purge_function(fake_modules, fake_atexit, cached_globals=None):
    tree = ast.parse(ADDON_INIT.read_text(encoding="utf-8"))
    function_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_purge_cached_submodules"
    )
    namespace = {
        "__name__": "SuperluminalRender",
        "atexit": fake_atexit,
        "sys": types.SimpleNamespace(modules=fake_modules),
    }
    namespace.update(cached_globals or {})
    exec(compile(ast.Module([function_node], []), str(ADDON_INIT), "exec"), namespace)
    return namespace["_purge_cached_submodules"], namespace


def test_purge_cached_submodules_replaces_stale_addon_children():
    class CachedStorage:
        enable_job_thread = True

        @classmethod
        def save(cls):
            pass

    cached_storage_module = types.SimpleNamespace(Storage=CachedStorage)
    root_module = object()
    unrelated_module = object()
    fake_modules = {
        "SuperluminalRender": root_module,
        "SuperluminalRender.storage": cached_storage_module,
        "SuperluminalRender.utils": object(),
        "SuperluminalRender.utils.request_utils": object(),
        "unrelated": unrelated_module,
    }
    unregistered_callbacks = []
    fake_atexit = types.SimpleNamespace(
        unregister=unregistered_callbacks.append,
    )

    stale_utils_attribute = object()
    purge, namespace = _load_purge_function(
        fake_modules,
        fake_atexit,
        cached_globals={"utils": stale_utils_attribute},
    )

    assert purge() is True
    assert CachedStorage.enable_job_thread is False
    assert unregistered_callbacks == [CachedStorage.save]
    assert "utils" not in namespace
    assert fake_modules == {
        "SuperluminalRender": root_module,
        "unrelated": unrelated_module,
    }


def test_purge_cached_submodules_is_a_noop_on_first_import():
    root_module = object()
    fake_modules = {"SuperluminalRender": root_module}
    fake_atexit = types.SimpleNamespace(
        unregister=lambda _callback: (_ for _ in ()).throw(
            AssertionError("no exit callback should be unregistered")
        )
    )

    purge, _namespace = _load_purge_function(fake_modules, fake_atexit)

    assert purge() is False
    assert fake_modules == {"SuperluminalRender": root_module}
