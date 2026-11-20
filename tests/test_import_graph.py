"""Structural guards for the one-pipeline codebase.

* Every import resolves, at any depth (function-local imports included).
* The layers point one way: `medibytes` never imports `evaluation`, `tests` or `tools`.
* Only the composition root (`factory`) and the API pick concrete speech models and
  the OpenAI client; `pipeline` depends on `ports` alone.
* No trace of a removed combination (other decoders, denoisers, LLM providers, the
  mock transcript, presets) survives in the source.
"""
from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("medibytes", "evaluation", "tools")


def _modules(package: str):
    for path in sorted((ROOT / package).rglob("*.py")):
        rel = path.relative_to(ROOT).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        yield ".".join(parts), path


def _imports(path: Path, module: str):
    """(target module, imported names) for every import statement in the file."""
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, []
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            yield target, [a.name for a in node.names]


ALL = [(m, p) for pkg in PACKAGES for m, p in _modules(pkg)]


@pytest.mark.parametrize("module, path", ALL, ids=[m for m, _ in ALL])
def test_every_project_import_resolves(module, path):
    for target, names in _imports(path, module):
        if target.split(".")[0] not in PACKAGES:
            continue
        mod = importlib.import_module(target)
        for name in names:
            if name == "*":
                continue
            assert hasattr(mod, name) or importlib.util.find_spec(f"{target}.{name}"), \
                f"{module}: {target} has no {name}"


def test_the_pipeline_package_never_imports_evaluation_tests_or_tools():
    for module, path in _modules("medibytes"):
        for target, _ in _imports(path, module):
            assert target.split(".")[0] not in ("evaluation", "tests", "tools"), (module, target)


CONCRETE = ("medibytes.asr.medasr", "medibytes.asr.whisper", "medibytes.llm.openai_client",
            "medibytes.preprocessing.preprocessor")
ALLOWED = {"medibytes.factory", "medibytes.api.app", *CONCRETE}


def test_only_the_composition_root_wires_concrete_implementations():
    for module, path in _modules("medibytes"):
        if module in ALLOWED:
            continue
        for target, _ in _imports(path, module):
            assert target not in CONCRETE, f"{module} imports {target}; inject it through ports"


REMOVED = re.compile(
    r"large-v3|medasr[-_]lm|whisper_medasr|gtcrn|sherpa|deepfilter|dpdfnet|rnnoise|voicefixer"
    r"|noisereduce|speechbrain|denoise_backends|ollama|llama|llm_tidy|merge_primary"
    r"|MOCK_TEXTS|decode_presets|presets\.py|streamlit|base_pipeline|clinical_eval", re.I)


def test_no_removed_combination_survives_in_the_source():
    offenders = []
    for pkg in ("medibytes", "tools", "web/src"):
        for path in (ROOT / pkg).rglob("*"):
            if path.suffix not in (".py", ".ts", ".tsx") or "node_modules" in path.parts:
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if REMOVED.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:90]}")
    assert not offenders, "\n".join(offenders)
