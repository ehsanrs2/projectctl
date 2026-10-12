from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath

from projectctl.application.tasks import capture_task_snapshot
from projectctl.core.digest import digest
from projectctl.core.errors import ConfigurationError
from projectctl.core.paths import resolve_inside_repo
from projectctl.core.time import utc_now
from projectctl.git import current_branch, resolve_commit
from projectctl.execution_scope.catalog import resolve_execution_scope_catalog
from projectctl.project.loader import load_project_config
from projectctl.scheduler.digests import semantic_task_digest
from projectctl.schemas.context_discovery import (
    ContextDiscoveryEvidence,
    ContextDiscoveryReport,
    ContextPathCandidate,
    ContextScopeSuggestion,
    ScopeCoverage,
)
from projectctl.schemas.execution_input import ExecutionPathScope


_SOURCE_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
    ".kt", ".kts", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php",
    ".swift", ".scala", ".lua", ".zig", ".ex", ".exs", ".m", ".mm", ".vue",
    ".svelte", ".sql",
}
_DOC_EXTENSIONS = {".md", ".mdx", ".rst", ".txt", ".yaml", ".yml", ".toml"}
_MAX_SOURCE_BYTES = 512_000
_MAX_REFERENCE_BYTES = 256_000
_MAX_CANDIDATES = 48
_MAX_INPUT_SUGGESTIONS = 24
_ACTION_WORDS = {
    "add", "change", "create", "delete", "edit", "fix", "implement", "modify",
    "move", "refactor", "remove", "rename", "replace", "update", "write",
}
_STOPWORDS = {
    "about", "after", "again", "against", "also", "and", "are", "because",
    "before", "between", "build", "code", "context", "could", "from", "have",
    "into", "more", "project", "should", "task", "than", "that", "the", "their",
    "then", "this", "through", "using", "with", "without",
}
_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.@+-]+)+\.[A-Za-z0-9]+)"
)
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".projectctl-context-", suffix=".json", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass


def _git(root: Path, *args: str, text: bool = True, check: bool = True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=text,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr
        stdout = result.stdout
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        raise ConfigurationError(
            (stderr or stdout or f"git {' '.join(args)} failed").strip()
        )
    return result


def _tracked_files(root: Path, commit: str) -> list[str]:
    result = _git(
        root,
        "ls-tree",
        "-r",
        "--full-tree",
        "--name-only",
        commit,
    )
    return sorted(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
        and not line.startswith(".projectctl/")
        and not line.startswith(".git/")
    )


def _git_bytes(root: Path, commit: str, path: str, *, max_bytes: int) -> bytes | None:
    size = _git(root, "cat-file", "-s", f"{commit}:{path}", check=False)
    if size.returncode != 0:
        return None
    try:
        if int(size.stdout.strip()) > max_bytes:
            return None
    except ValueError:
        return None
    result = _git(root, "show", f"{commit}:{path}", text=False, check=False)
    if result.returncode != 0:
        return None
    return result.stdout


def _git_text(root: Path, commit: str, path: str, *, max_bytes: int) -> str | None:
    data = _git_bytes(root, commit, path, max_bytes=max_bytes)
    if data is None:
        return None
    return data.decode("utf-8", errors="replace")


def _split_identifier(value: str) -> list[str]:
    pieces = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value).replace("_", " ")
    return [item.casefold() for item in _WORD_RE.findall(pieces)]


def _terms(text: str) -> set[str]:
    result: set[str] = set()
    for raw in _WORD_RE.findall(text):
        for item in _split_identifier(raw):
            if len(item) >= 3 and item not in _STOPWORDS:
                result.add(item)
    return result


def _normalize_repo_path(root: Path, raw: str) -> str | None:
    raw = raw.replace("\\", "/").strip()
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(root).as_posix()
        except Exception:
            return None
    try:
        safe = resolve_inside_repo(root, raw, must_exist=False)
        return safe.relative_to(root).as_posix()
    except Exception:
        return None


def _reference_paths(task) -> list[str]:
    return sorted(
        {
            *task.references.specs,
            *task.references.plans,
            *task.references.decisions,
            *task.references.research,
        }
    )


def _module_aliases(path: str) -> set[str]:
    pure = PurePosixPath(path)
    if pure.suffix not in {".py", ".pyi"}:
        return set()
    parts = list(pure.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if not parts:
        return set()
    aliases = {".".join(parts)}
    if parts[0] in {"src", "lib"} and len(parts) > 1:
        aliases.add(".".join(parts[1:]))
    return aliases


def _resolve_import(
    module: str,
    *,
    current_module: str,
    level: int,
    module_to_path: dict[str, str],
) -> str | None:
    name = module
    if level:
        package = current_module.split(".")
        if package:
            package = package[:-1]
        climb = max(level - 1, 0)
        if climb:
            package = package[:-climb] if climb <= len(package) else []
        name = ".".join([*package, module] if module else package)
    while name:
        if name in module_to_path:
            return module_to_path[name]
        name = name.rsplit(".", 1)[0] if "." in name else ""
    return None


def _python_index(
    root: Path,
    commit: str,
    files: list[str],
) -> tuple[
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
    int,
]:
    python_files = [
        path for path in files if PurePosixPath(path).suffix in {".py", ".pyi"}
    ]
    module_to_path: dict[str, str] = {}
    path_modules: dict[str, set[str]] = {}
    for path in python_files:
        aliases = _module_aliases(path)
        path_modules[path] = aliases
        for module in sorted(aliases, key=len):
            module_to_path.setdefault(module, path)

    symbols: dict[str, set[str]] = defaultdict(set)
    imports: dict[str, set[str]] = defaultdict(set)
    imported_by: dict[str, set[str]] = defaultdict(set)
    indexed = 0

    for path in python_files:
        text = _git_text(root, commit, path, max_bytes=_MAX_SOURCE_BYTES)
        if text is None:
            continue
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError:
            continue
        indexed += 1
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols[node.name].add(path)

        aliases = path_modules.get(path) or {""}
        current_module = sorted(aliases, key=len)[0]
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = _resolve_import(
                        alias.name,
                        current_module=current_module,
                        level=0,
                        module_to_path=module_to_path,
                    )
                    if target:
                        targets.append(target)
            elif isinstance(node, ast.ImportFrom):
                target = _resolve_import(
                    node.module or "",
                    current_module=current_module,
                    level=node.level,
                    module_to_path=module_to_path,
                )
                if target:
                    targets.append(target)
                else:
                    for alias in node.names:
                        joined = ".".join(
                            item for item in [node.module or "", alias.name] if item
                        )
                        target = _resolve_import(
                            joined,
                            current_module=current_module,
                            level=node.level,
                            module_to_path=module_to_path,
                        )
                        if target:
                            targets.append(target)
            for target in targets:
                if target == path:
                    continue
                imports[path].add(target)
                imported_by[target].add(path)
    return symbols, imports, imported_by, indexed


def _graphify_data(root: Path, enabled: bool):
    if not enabled:
        return None, None, []
    path = root / "graphify-out" / "graph.json"
    if not path.exists():
        return None, None, [
            "features.graphify is enabled but graphify-out/graph.json is missing; "
            "builtin discovery continued without Graphify evidence."
        ]
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return None, None, [f"Graphify graph could not be read: {exc}"]
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        return None, None, ["Graphify graph.json has no valid node-link nodes list."]
    edges = data.get("links", data.get("edges", []))
    if not isinstance(edges, list):
        return None, None, ["Graphify graph.json has no valid links/edges list."]
    return data, "sha256:" + hashlib.sha256(raw).hexdigest(), []


def discover_context(
    project_root: Path,
    task_id: str,
    *,
    integration_target_ref: str | None = None,
    now: datetime | None = None,
    persist: bool = True,
) -> ContextDiscoveryReport:
    root = project_root.resolve()
    now = now or utc_now()
    if now.tzinfo is None:
        raise ValueError("Context discovery time must be timezone-aware.")

    config = load_project_config(root)
    target_ref = integration_target_ref or current_branch(root)
    base_commit = resolve_commit(root, target_ref)
    snapshot = capture_task_snapshot(
        root,
        state="all",
        read_cache_max_age_seconds=0,
    )
    task = next((item for item in snapshot.tasks if item.id == task_id), None)
    if task is None:
        raise ConfigurationError(f"Unknown task for context discovery: {task_id!r}.")

    files = _tracked_files(root, base_commit)
    tracked = set(files)
    source_files = {
        path for path in files if PurePosixPath(path).suffix.casefold() in _SOURCE_EXTENSIONS
    }
    symbols, imports, imported_by, indexed_python = _python_index(
        root, base_commit, files
    )

    evidence: list[ContextDiscoveryEvidence] = []
    candidates: dict[str, dict] = {}
    primary_paths: set[str] = set()

    def add_evidence(
        *,
        provider: str,
        kind: str,
        strength: str,
        detail: str,
        source_path: str | None = None,
        relation: str | None = None,
        confidence_score: float | None = None,
        source_location: str | None = None,
    ) -> str:
        evidence_id = f"e-{len(evidence) + 1:04d}"
        evidence.append(
            ContextDiscoveryEvidence(
                evidence_id=evidence_id,
                provider=provider,
                kind=kind,
                strength=strength,
                source_path=source_path,
                source_location=source_location,
                relation=relation,
                detail=detail,
                confidence_score=confidence_score,
            )
        )
        return evidence_id

    def add_candidate(
        path: str,
        *,
        score: int,
        roles: set[str],
        evidence_id: str,
        reason: str,
        primary: bool = False,
    ) -> None:
        if path not in tracked:
            return
        item = candidates.setdefault(
            path,
            {
                "score": 0,
                "roles": set(),
                "evidence_ids": [],
                "reasons": [],
            },
        )
        item["score"] += score
        item["roles"].update(roles)
        if evidence_id not in item["evidence_ids"]:
            item["evidence_ids"].append(evidence_id)
        if reason not in item["reasons"]:
            item["reasons"].append(reason)
        if primary:
            primary_paths.add(path)

    reference_texts: list[tuple[str, str]] = []
    for path in _reference_paths(task):
        if path not in tracked:
            continue
        suffix = PurePosixPath(path).suffix.casefold()
        if suffix in _DOC_EXTENSIONS:
            text = _git_text(root, base_commit, path, max_bytes=_MAX_REFERENCE_BYTES)
            if text is not None:
                reference_texts.append((path, text))
        ev = add_evidence(
            provider="builtin",
            kind="task_reference",
            strength="explicit",
            source_path=path,
            detail=f"Task authority explicitly references {path}.",
        )
        add_candidate(
            path,
            score=100,
            roles={"reference"},
            evidence_id=ev,
            reason="explicit task reference",
        )

    title_text = task.title
    combined_text = "\n".join([title_text, *task.tags, *[text for _, text in reference_texts]])
    query_terms = _terms(combined_text)
    semantic_terms = query_terms - _ACTION_WORDS
    title_terms = _terms(title_text) - _ACTION_WORDS

    mention_sources = [("task title", title_text, None)]
    mention_sources.extend(
        (f"task reference {path}", text, path) for path, text in reference_texts
    )
    for source_label, text, source_path in mention_sources:
        for raw_path in sorted(set(_PATH_RE.findall(text))):
            path = _normalize_repo_path(root, raw_path)
            if path is None or path not in tracked:
                continue
            roles = {"input"} if path in source_files else {"reference"}
            line_action = False
            for line in text.splitlines():
                if raw_path in line and _ACTION_WORDS.intersection(_terms(line)):
                    line_action = True
                    break
            if path in source_files and line_action:
                roles.add("write_candidate")
            ev = add_evidence(
                provider="builtin",
                kind="path_mention",
                strength="explicit",
                source_path=source_path,
                detail=f"{source_label} explicitly mentions tracked path {path}.",
            )
            add_candidate(
                path,
                score=120 if line_action else 105,
                roles=roles,
                evidence_id=ev,
                reason=f"explicit path mention in {source_label}",
                primary=path in source_files,
            )

    normalized_title_words = {word.casefold() for word in _WORD_RE.findall(title_text)}
    for symbol, paths in sorted(symbols.items()):
        symbol_terms = set(_split_identifier(symbol))
        if not symbol_terms or symbol_terms <= _ACTION_WORDS:
            continue
        exact_symbol = (
            symbol.casefold() in normalized_title_words
            and symbol.casefold() not in _ACTION_WORDS
        )
        term_match = symbol_terms <= semantic_terms
        if not exact_symbol and not term_match:
            continue
        for path in sorted(paths):
            in_title = exact_symbol or symbol_terms <= title_terms
            ev = add_evidence(
                provider="builtin",
                kind="python_symbol",
                strength="structural",
                source_path=path,
                detail=f"Python AST defines symbol {symbol!r} mentioned by task context.",
            )
            roles = {"input"}
            if in_title:
                roles.add("write_candidate")
            add_candidate(
                path,
                score=100 if in_title else 80,
                roles=roles,
                evidence_id=ev,
                reason=f"Python symbol match: {symbol}",
                primary=True,
            )

    for path in sorted(source_files):
        stem_terms = set(_split_identifier(PurePosixPath(path).stem))
        overlap_terms = stem_terms - _ACTION_WORDS
        if not overlap_terms or not (overlap_terms & semantic_terms):
            continue
        overlap = sorted(overlap_terms & semantic_terms)
        ev = add_evidence(
            provider="builtin",
            kind="filename_token",
            strength="structural",
            source_path=path,
            detail=f"Filename tokens overlap task context: {', '.join(overlap)}.",
        )
        add_candidate(
            path,
            score=45 + min(20, 5 * len(overlap)),
            roles={"input"},
            evidence_id=ev,
            reason="filename token match",
        )

    for path in sorted(primary_paths):
        for related, relation in [
            *((target, "imports") for target in sorted(imports.get(path, set()))),
            *((source, "imported_by") for source in sorted(imported_by.get(path, set()))),
        ]:
            ev = add_evidence(
                provider="builtin",
                kind="python_import",
                strength="structural",
                source_path=path,
                relation=relation,
                detail=f"{path} {relation} {related} according to Python AST.",
            )
            add_candidate(
                related,
                score=45,
                roles={"input"},
                evidence_id=ev,
                reason=f"one-hop Python {relation} relation",
            )

        pure = PurePosixPath(path)
        stem = pure.stem
        companion_names = {
            f"test_{stem}.py",
            f"{stem}_test.py",
            f"test_{stem}.ts",
            f"{stem}.test.ts",
            f"{stem}.spec.ts",
            f"{stem}.test.tsx",
            f"{stem}.spec.tsx",
            f"{stem}.test.js",
            f"{stem}.spec.js",
        }
        for candidate_path in sorted(source_files):
            if PurePosixPath(candidate_path).name not in companion_names:
                continue
            ev = add_evidence(
                provider="builtin",
                kind="test_companion",
                strength="structural",
                source_path=path,
                relation="tested_by",
                detail=f"{candidate_path} is a conventional test companion for {path}.",
            )
            add_candidate(
                candidate_path,
                score=85,
                roles={"input", "write_candidate", "test"},
                evidence_id=ev,
                reason="conventional test companion",
            )

    graph, graph_digest, graph_warnings = _graphify_data(
        root, bool(config.features.graphify)
    )
    warnings = list(graph_warnings)
    if graph is not None:
        nodes = {
            str(node.get("id")): node
            for node in graph.get("nodes", [])
            if isinstance(node, dict) and node.get("id") is not None
        }
        graph_edges = graph.get("links", graph.get("edges", []))
        seed_ids: set[str] = set()
        for node_id, node in nodes.items():
            raw_path = str(node.get("source_file") or "")
            path = _normalize_repo_path(root, raw_path) if raw_path else None
            label_terms = _terms(str(node.get("label") or ""))
            if (
                path in primary_paths
                or (
                    label_terms
                    and not label_terms <= _ACTION_WORDS
                    and label_terms <= semantic_terms
                )
            ):
                seed_ids.add(node_id)
                if path in tracked and path in source_files:
                    ev = add_evidence(
                        provider="graphify",
                        kind="graphify_node",
                        strength="structural",
                        source_path=path,
                        detail=(
                            "Graphify node matches a builtin seed or task-context label: "
                            f"{node.get('label') or node_id}."
                        ),
                    )
                    add_candidate(
                        path,
                        score=55,
                        roles={"input"},
                        evidence_id=ev,
                        reason="Graphify seed node",
                    )

        for edge in graph_edges:
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            if source not in seed_ids and target not in seed_ids:
                continue
            neighbor_id = target if source in seed_ids else source
            node = nodes.get(neighbor_id)
            if node is None:
                continue
            raw_path = str(node.get("source_file") or "")
            path = _normalize_repo_path(root, raw_path) if raw_path else None
            if path is None or path not in tracked or path not in source_files:
                continue
            confidence = str(edge.get("confidence") or "AMBIGUOUS").upper()
            if confidence == "EXTRACTED":
                strength = "structural"
                score = 45
            elif confidence == "INFERRED":
                strength = "inferred"
                score = 20
            else:
                strength = "ambiguous"
                score = 5
            raw_score = edge.get("confidence_score")
            confidence_score = (
                float(raw_score)
                if isinstance(raw_score, (int, float)) and 0 <= float(raw_score) <= 1
                else None
            )
            relation = str(edge.get("relation") or "related")
            ev = add_evidence(
                provider="graphify",
                kind="graphify_edge",
                strength=strength,
                source_path=path,
                relation=relation,
                confidence_score=confidence_score,
                detail=(
                    f"Graphify {confidence} edge {source} -[{relation}]-> {target} "
                    f"connects task-context seed to {path}."
                ),
            )
            add_candidate(
                path,
                score=score,
                roles={"input"},
                evidence_id=ev,
                reason=f"Graphify {confidence.lower()} {relation} relation",
            )
        warnings.append(
            "Graphify evidence is derived and graph.json is not treated as base-commit "
            "authority; its digest/provenance are recorded for review only."
        )

    role_order = {"write_candidate": 0, "input": 1, "test": 2, "reference": 3}
    rendered_candidates = [
        ContextPathCandidate(
            path=path,
            roles=sorted(item["roles"], key=lambda value: role_order[value]),
            score=item["score"],
            evidence_ids=item["evidence_ids"],
            reasons=item["reasons"],
        )
        for path, item in candidates.items()
    ]
    rendered_candidates.sort(key=lambda item: (-item.score, item.path))
    rendered_candidates = rendered_candidates[:_MAX_CANDIDATES]

    report = ContextDiscoveryReport(
        discovery_id=f"context-discovery-{uuid.uuid4().hex}",
        generated_at=now,
        project_id=config.project.id,
        task_id=task.id,
        integration_target_ref=target_ref,
        base_commit=base_commit,
        task_digest=semantic_task_digest(task),
        repository_file_count=len(files),
        indexed_python_files=indexed_python,
        graphify_enabled=bool(config.features.graphify),
        graphify_digest=graph_digest,
        candidates=rendered_candidates,
        evidence=evidence,
        warnings=warnings,
    )
    if persist:
        _atomic_json(
            root
            / ".projectctl"
            / "context"
            / "discovery"
            / task.id
            / f"{report.discovery_id}.json",
            report,
        )
    return report


def _scope_covers(path: str, scopes) -> bool:
    pure = PurePosixPath(path)
    for scope in scopes:
        if scope.kind == "exact" and scope.path == path:
            return True
        if scope.kind == "tree":
            base = PurePosixPath(scope.path)
            try:
                pure.relative_to(base)
                return True
            except ValueError:
                pass
    return False


def suggest_scope(
    project_root: Path,
    task_id: str,
    *,
    report: ContextDiscoveryReport | None = None,
    integration_target_ref: str | None = None,
    now: datetime | None = None,
    persist: bool = True,
) -> ContextScopeSuggestion:
    root = project_root.resolve()
    now = now or utc_now()
    report = report or discover_context(
        root,
        task_id,
        integration_target_ref=integration_target_ref,
        now=now,
        persist=persist,
    )

    input_paths = [
        item.path
        for item in report.candidates
        if (
            ("input" in item.roles or "test" in item.roles)
            and item.score >= 40
            and PurePosixPath(item.path).suffix.casefold() in _SOURCE_EXTENSIONS
        )
    ][:_MAX_INPUT_SUGGESTIONS]
    write_paths = [
        item.path
        for item in report.candidates
        if "write_candidate" in item.roles
        and item.score >= 80
        and PurePosixPath(item.path).suffix.casefold() in _SOURCE_EXTENSIONS
    ]

    inputs = [ExecutionPathScope(path=path, kind="exact") for path in sorted(set(input_paths))]
    writes = [ExecutionPathScope(path=path, kind="exact") for path in sorted(set(write_paths))]

    authority = resolve_execution_scope_catalog(root)
    declared = (
        authority.catalog.tasks.get(task_id)
        if authority.catalog is not None else None
    )

    coverage = ScopeCoverage()
    declared_digest = None
    if declared is not None:
        declared_digest = digest(declared)
        coverage = ScopeCoverage(
            suggested_inputs_not_declared=[
                item.path for item in inputs if not _scope_covers(item.path, declared.inputs)
            ],
            suggested_writes_not_declared=[
                item.path for item in writes if not _scope_covers(item.path, declared.writes)
            ],
            declared_inputs_not_suggested=[
                item.path
                for item in declared.inputs
                if not any(_scope_covers(candidate.path, [item]) for candidate in inputs)
            ],
            declared_writes_not_suggested=[
                item.path
                for item in declared.writes
                if not any(_scope_covers(candidate.path, [item]) for candidate in writes)
            ],
        )

    warnings = list(report.warnings)
    if not writes:
        warnings.append(
            "No write path met the conservative write-candidate threshold; "
            "write scope must be authored manually."
        )
    warnings.append(
        "This scope suggestion is derived evidence only. ProjectCTL will not write "
        "projectctl.scope.yaml or expand execution authority from this artifact."
    )

    suggestion = ContextScopeSuggestion(
        suggestion_id=f"context-scope-{uuid.uuid4().hex}",
        generated_at=now,
        project_id=report.project_id,
        task_id=report.task_id,
        base_commit=report.base_commit,
        discovery_digest=digest(report),
        input_scopes=inputs,
        write_scopes=writes,
        declared_scope_present=declared is not None,
        declared_scope_digest=declared_digest,
        coverage=coverage,
        warnings=warnings,
    )
    if persist:
        _atomic_json(
            root
            / ".projectctl"
            / "context"
            / "suggestions"
            / task_id
            / f"{suggestion.suggestion_id}.json",
            suggestion,
        )
    return suggestion
