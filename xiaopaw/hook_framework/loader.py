"""HookLoader: YAML parsing + two-layer loading + strategy instantiation + deps injection."""

import importlib.util
import sys
from pathlib import Path

import yaml

from .registry import EventType, HookRegistry


class HookLoader:
    def __init__(self, registry: HookRegistry):
        self._registry = registry
        self.strategies: dict[str, object] = {}
        self._module_cache: dict[Path, object] = {}

    def load_from_directory(
        self, hooks_dir: Path, layer_name: str = "", fail_closed_names: set[str] | None = None
    ):
        yaml_path = hooks_dir / "hooks.yaml"
        if not yaml_path.exists():
            return

        try:
            with open(yaml_path) as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"[HookLoader] YAML parse error in {yaml_path}: {e}", file=sys.stderr)
            return

        if not isinstance(config, dict):
            return

        fail_closed_names = fail_closed_names or set()

        self._load_hooks_section(config, hooks_dir, layer_name, fail_closed_names)
        self._load_strategies_section(config, hooks_dir, layer_name, fail_closed_names)

    def _load_hooks_section(
        self, config: dict, hooks_dir: Path, layer_name: str, fail_closed_names: set[str]
    ):
        for event_name, handler_list in config.get("hooks", {}).items():
            event_type = EventType(event_name.lower())
            if not isinstance(handler_list, list):
                continue
            for entry in handler_list:
                handler_ref = entry if isinstance(entry, str) else entry.get("handler", "")
                if not handler_ref:
                    continue
                handler_fn = self._resolve_handler(handler_ref, hooks_dir)
                if handler_fn is None:
                    continue
                display = f"[{layer_name}] {handler_ref}" if layer_name else handler_ref
                self._registry.register(
                    event_type,
                    handler_fn,
                    name=display,
                    fail_closed=handler_ref in fail_closed_names,
                )

    def _load_strategies_section(
        self, config: dict, hooks_dir: Path, layer_name: str, fail_closed_names: set[str]
    ):
        for entry in config.get("strategies", []):
            name = entry.get("name", "")
            class_ref = entry.get("class", "")
            strategy_config = entry.get("config", {}) or {}
            hooks_map = entry.get("hooks", {}) or {}
            deps_map = entry.get("deps", {}) or {}

            cls = self._resolve_class(class_ref, hooks_dir)
            if cls is None:
                continue

            resolved_deps = {}
            for param, strategy_key in deps_map.items():
                dep = self.strategies.get(strategy_key)
                if dep is None:
                    print(
                        f"[HookLoader] WARNING: dependency '{strategy_key}' not found for {class_ref}.{param}",
                        file=sys.stderr,
                    )
                resolved_deps[param] = dep

            try:
                instance = cls(**strategy_config, **resolved_deps)
            except Exception as e:
                print(
                    f"[HookLoader] failed to instantiate {class_ref}: {e}",
                    file=sys.stderr,
                )
                continue

            self.strategies[name] = instance

            for event_name, method_name in hooks_map.items():
                event_type = EventType(event_name.lower())
                method = getattr(instance, method_name, None)
                if method is None:
                    print(
                        f"[HookLoader] method not found: {class_ref}.{method_name}",
                        file=sys.stderr,
                    )
                    continue
                display = f"[{layer_name}] {name}.{method_name}" if layer_name else f"{name}.{method_name}"
                self._registry.register(
                    event_type,
                    method,
                    name=display,
                    fail_closed=name in fail_closed_names,
                )

    def _resolve_handler(self, handler_ref: str, hooks_dir: Path):
        parts = handler_ref.rsplit(".", 1)
        if len(parts) != 2:
            print(f"[HookLoader] invalid handler ref (expected module.function): {handler_ref}", file=sys.stderr)
            return None
        module_name, func_name = parts
        module_path = (hooks_dir / f"{module_name}.py").resolve()
        if not module_path.is_relative_to(hooks_dir.resolve()):
            print(
                f"[HookLoader] path traversal blocked: {handler_ref}",
                file=sys.stderr,
            )
            return None
        if not module_path.exists():
            print(
                f"[HookLoader] module not found: {module_path}",
                file=sys.stderr,
            )
            return None
        module = self._load_module(module_name, module_path, hooks_dir)
        if module is None:
            return None
        fn = getattr(module, func_name, None)
        if fn is None:
            print(
                f"[HookLoader] function not found: {handler_ref}",
                file=sys.stderr,
            )
        return fn

    def _resolve_class(self, class_ref: str, hooks_dir: Path):
        parts = class_ref.rsplit(".", 1)
        if len(parts) != 2:
            print(f"[HookLoader] invalid class ref (expected module.Class): {class_ref}", file=sys.stderr)
            return None
        module_name, class_name = parts
        module_path = (hooks_dir / f"{module_name}.py").resolve()
        if not module_path.is_relative_to(hooks_dir.resolve()):
            print(
                f"[HookLoader] path traversal blocked: {class_ref}",
                file=sys.stderr,
            )
            return None
        if not module_path.exists():
            print(
                f"[HookLoader] module not found: {module_path}",
                file=sys.stderr,
            )
            return None
        module = self._load_module(module_name, module_path, hooks_dir)
        if module is None:
            return None
        cls = getattr(module, class_name, None)
        if cls is None:
            print(
                f"[HookLoader] class not found: {class_ref}",
                file=sys.stderr,
            )
        return cls

    def _load_module(self, module_name: str, module_path: Path, hooks_dir: Path):
        resolved = module_path.resolve()
        if resolved in self._module_cache:
            return self._module_cache[resolved]
        fq_name = f"hooks_dynamic.{id(hooks_dir)}.{module_name}"
        spec = importlib.util.spec_from_file_location(fq_name, module_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"[HookLoader] error loading {module_path}: {e}", file=sys.stderr)
            return None
        self._module_cache[resolved] = module
        return module

    def load_two_layers(self, global_dir: Path, workspace_dir: Path, fail_closed_names: set[str] | None = None):
        self.load_from_directory(global_dir, layer_name="global", fail_closed_names=fail_closed_names)
        ws_hooks = workspace_dir / "hooks"
        if ws_hooks.exists():
            self.load_from_directory(ws_hooks, layer_name="workspace", fail_closed_names=fail_closed_names)
