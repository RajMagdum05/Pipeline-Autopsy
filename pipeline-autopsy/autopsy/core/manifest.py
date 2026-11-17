"""Domain-neutral validation for pipeline manifests."""
import re
from collections import defaultdict, deque

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .validators import VALIDATORS

_NAME = re.compile(r"^[a-z0-9_-]+$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def _is_name(value):
    return isinstance(value, str) and _NAME.fullmatch(value) is not None


def _roles_for(stage, roles):
    if stage.get("scope") != "item":
        return [None]
    selected = stage.get("item_roles")
    if isinstance(selected, list) and selected:
        return [role for role in selected if isinstance(role, str)]
    return roles or ["*"]


def _stage_nodes(stage, roles):
    return [(stage.get("name"), role) for role in _roles_for(stage, roles)]


def _find_cycle(stages, stage_by_name, producers, roles):
    nodes = []
    for stage in stages:
        if isinstance(stage, dict) and isinstance(stage.get("name"), str):
            nodes.extend(_stage_nodes(stage, roles))
    adjacency = {node: set() for node in nodes}

    def connect(source, target):
        if source in adjacency and target in adjacency and source != target:
            adjacency[source].add(target)

    for consumer in stages:
        if not isinstance(consumer, dict) or not isinstance(consumer.get("name"), str):
            continue
        for kind in consumer.get("consumes", []):
            for producer, _ in producers.get(kind, []):
                if producer is consumer or producer.get("name") == consumer.get("name"):
                    continue
                for source in _stage_nodes(producer, roles):
                    for target in _stage_nodes(consumer, roles):
                        if source[1] is None or target[1] is None or source[1] == target[1]:
                            connect(source, target)
        for req in consumer.get("requires", []):
            if not isinstance(req, dict):
                continue
            required = stage_by_name.get(req.get("stage"))
            if not required:
                continue
            gate_role = req.get("item_role")
            for source in _stage_nodes(required, roles):
                if source[1] != gate_role:
                    continue
                for target in _stage_nodes(consumer, roles):
                    # An item must not wait on the gate produced by itself.
                    if target[1] != gate_role:
                        connect(source, target)

    indegree = {node: 0 for node in nodes}
    for targets in adjacency.values():
        for target in targets:
            indegree[target] += 1
    ready = deque(node for node, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        node = ready.popleft()
        visited += 1
        for target in adjacency[node]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    return visited != len(nodes)


def validate_manifest(manifest, pack_validators=()):
    """Return every detectable manifest problem; return an empty list when valid.

    ``pack_validators`` is the registry supplied by the pack loader. The core does
    not load domain packs or access the filesystem itself.
    """
    if not isinstance(manifest, dict):
        return ["manifest must be an object"]
    problems = []
    for key in ("manifest", "pipeline", "version", "stages"):
        if key not in manifest:
            problems.append(f"missing required key: {key}")
    if manifest.get("manifest") != "pipeline-manifest/1":
        problems.append("manifest must be 'pipeline-manifest/1'")
    if not _is_name(manifest.get("pipeline")):
        problems.append("pipeline must match [a-z0-9_-]+")
    if not isinstance(manifest.get("version"), str) or not _SEMVER.fullmatch(manifest["version"]):
        problems.append("version must be a semantic version")

    stages = manifest.get("stages")
    if not isinstance(stages, list) or not stages:
        problems.append("stages must be a non-empty list")
        stages = []
    external = manifest.get("external_inputs", [])
    if not isinstance(external, list) or any(not _is_name(kind) for kind in external):
        problems.append("external_inputs must be a list of kind names")
        external = []
    external_set = set(external)

    items = manifest.get("items", {})
    roles = items.get("roles", []) if isinstance(items, dict) else []
    if not isinstance(items, dict) or not isinstance(roles, list) or any(not isinstance(role, str) for role in roles):
        problems.append("items.roles must be a list of strings")
        roles = []

    evidence = manifest.get("evidence")
    allowed = []
    if evidence is not None:
        if not isinstance(evidence, dict):
            problems.append("evidence must be an object")
        else:
            if evidence.get("level") not in ("E0", "E1", "E2"):
                problems.append("evidence.level must be E0, E1, or E2")
            allowed = evidence.get("kinds_allowed", [])
            if not isinstance(allowed, list) or any(not _is_name(kind) for kind in allowed):
                problems.append("evidence.kinds_allowed must be a list of kind names")
            retention = evidence.get("retention_days")
            if not isinstance(retention, int) or isinstance(retention, bool) or retention < 1:
                problems.append("evidence.retention_days must be a positive integer")
    else:
        allowed = []

    if "pack" in manifest and not _is_name(manifest.get("pack")):
        problems.append("pack must match [a-z0-9_-]+")

    stage_by_name = {}
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            problems.append(f"stages[{index}] must be an object")
            continue
        name = stage.get("name")
        if not _is_name(name):
            problems.append(f"stages[{index}].name must match [a-z0-9_-]+")
        elif name in stage_by_name:
            problems.append(f"duplicate stage name: {name}")
        else:
            stage_by_name[name] = stage
        if stage.get("scope") not in ("item", "run"):
            problems.append(f"stages[{index}].scope must be item or run")
        for field in ("consumes", "produces"):
            values = stage.get(field)
            if not isinstance(values, list) or any(not _is_name(kind) for kind in values):
                problems.append(f"stages[{index}].{field} must be a list of kind names")
        if "item_roles" in stage and (not isinstance(stage["item_roles"], list)
                                      or any(not isinstance(role, str) for role in stage["item_roles"])):
            problems.append(f"stages[{index}].item_roles must be a list of strings")
        if "requires" in stage and not isinstance(stage["requires"], list):
            problems.append(f"stages[{index}].requires must be a list")

    producers = defaultdict(list)
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict) or not isinstance(stage.get("produces"), list):
            continue
        for kind in stage["produces"]:
            if not isinstance(kind, str):
                continue
            if any(owner.get("name") != stage.get("name") for owner, _ in producers[kind]):
                problems.append(f"kind {kind!r} is produced by more than one stage")
            producers[kind].append((stage, index))

    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        consumes = stage.get("consumes", [])
        if not isinstance(consumes, list):
            consumes = []
        for kind in consumes:
            if not isinstance(kind, str) or kind in external_set:
                continue
            owners = producers.get(kind, [])
            if not any(owner_index < index for _, owner_index in owners):
                problems.append(f"stages[{index}] consumes {kind!r} before it is produced or without external input")

        requires = stage.get("requires", [])
        if not isinstance(requires, list):
            continue
        for req_index, req in enumerate(requires):
            if not isinstance(req, dict):
                problems.append(f"stages[{index}].requires[{req_index}] must be an object")
                continue
            target = stage_by_name.get(req.get("stage"))
            if target is None:
                problems.append(f"stages[{index}].requires[{req_index}] references an unknown stage")
            elif target.get("scope") != "item":
                problems.append(f"stages[{index}].requires[{req_index}].stage must have scope item")
            if req.get("item_role") not in roles:
                problems.append(f"stages[{index}].requires[{req_index}].item_role must be listed in items.roles")

    artifacts = manifest.get("artifacts", {})
    if not isinstance(artifacts, dict):
        problems.append("artifacts must be an object")
        artifacts = {}
    try:
        pack_names = set(pack_validators) if manifest.get("pack") else set()
    except TypeError:
        pack_names = set()
        problems.append("pack_validators must be an iterable of validator names")
    known_validators = set(VALIDATORS) | pack_names
    for kind, spec in artifacts.items():
        if not _is_name(kind):
            problems.append(f"artifact kind {kind!r} must match [a-z0-9_-]+")
        if not isinstance(spec, dict):
            problems.append(f"artifacts.{kind} must be an object")
            continue
        if "schema" in spec:
            try:
                Draft202012Validator.check_schema(spec["schema"])
            except SchemaError as exc:
                problems.append(f"artifacts.{kind}.schema is invalid: {exc.message}")
        consistency = spec.get("consistency", [])
        if not isinstance(consistency, list):
            problems.append(f"artifacts.{kind}.consistency must be a list")
            continue
        for rule_index, rule in enumerate(consistency):
            if not isinstance(rule, dict):
                problems.append(f"artifacts.{kind}.consistency[{rule_index}] must be an object")
                continue
            validator = rule.get("validator")
            if not isinstance(validator, str) or validator not in known_validators:
                problems.append(f"validator {validator!r} is not registered in core or the declared pack")

    if isinstance(allowed, list):
        all_kinds = set(external_set) | set(producers)
        for kind in allowed:
            if isinstance(kind, str) and kind not in all_kinds:
                problems.append(f"evidence kind {kind!r} is neither produced nor external")

    if stages and not any("scope must be" in problem for problem in problems):
        if _find_cycle(stages, stage_by_name, producers, roles):
            problems.append("data and control dependencies contain a cycle")

    return list(dict.fromkeys(problems))
