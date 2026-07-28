"""Loading, validating and activating a Company Brain version, where a version is a directory hashed as one unit."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from agent.constants import (
    APPLICANT_BOOL_FACTS,
    APPLICANT_FACTS,
    HIT_FACTS,
    OPERATORS,
    POINTER_FILE,
    POLICY_FILE,
    PROMPT_ROLES,
    REQUIRED_PROMPT_ROLES,
    RULES_FILE,
)
from agent.schemas import Brain, BrainSettings, Pointer, Rule


class BrainUnavailable(RuntimeError):
    """The Company Brain volume is missing, unreadable, or inconsistent."""


class BrainInvalid(BrainUnavailable):
    """A version exists but does not describe an executable policy."""

    def __init__(self, version: str, errors: list[str]) -> None:
        self.version = version
        self.errors = errors
        super().__init__(f"Brain version {version!r} is invalid: " + "; ".join(errors))


class BrainReadOnly(BrainUnavailable):
    """The volume cannot be written, so no swap can be recorded."""


_CACHE: dict[str, Brain] = {}


def read_pointer(brain_dir: Path) -> Pointer:
    """Read the active-version pointer fresh, so a swap needs no restart."""
    path = brain_dir / POINTER_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BrainUnavailable(f"pointer file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BrainUnavailable(f"pointer file malformed: {path}") from exc

    try:
        return Pointer.model_validate(raw)
    except ValidationError as exc:
        raise BrainUnavailable(f"pointer file malformed: {path}: {_compact(exc)}") from exc


def load_brain(brain_dir: Path) -> Brain:
    """The policy in force right now."""
    return load_version(brain_dir, read_pointer(brain_dir).active_version)


def active_version(brain_dir: Path) -> str:
    """The active version, confirmed loadable rather than merely named."""
    return load_brain(brain_dir).version


def load_version(brain_dir: Path, version: str) -> Brain:
    """Load and validate one version, raising rather than falling back to another."""
    directory = brain_dir / "versions" / version
    try:
        policy_bytes = (directory / POLICY_FILE).read_bytes()
        rules_bytes = (directory / RULES_FILE).read_bytes()
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise BrainUnavailable(f"version {version!r} is incomplete: {exc}") from exc

    # Prompt paths live in the table, so it is parsed before the hash can be taken.
    document = _document(version, rules_bytes)
    prompt_bytes = _read_prompts(version, directory, document)

    brain_hash = _digest(policy_bytes, rules_bytes, prompt_bytes)
    cached = _CACHE.get(brain_hash)
    if cached is not None:
        return cached

    brain = _parse(version, document, policy_bytes, prompt_bytes, brain_hash)
    _CACHE[brain_hash] = brain
    return brain


def _document(version: str, rules_bytes: bytes) -> dict[str, Any]:
    """The rule table as a mapping, or a load failure."""
    try:
        document = yaml.safe_load(rules_bytes.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise BrainInvalid(version, [f"{RULES_FILE} is not valid YAML: {exc}"]) from exc
    if not isinstance(document, dict):
        raise BrainInvalid(version, [f"{RULES_FILE} must be a mapping"])
    return document


def _read_prompts(version: str, directory: Path, document: dict[str, Any]) -> dict[str, bytes]:
    """Resolve the declared role → path mapping into bytes, or fail the load."""
    declared = document.get("prompts")
    if not isinstance(declared, dict):
        raise BrainInvalid(version, [f"{RULES_FILE}: `prompts` must map each role to a path"])

    root = directory.resolve()
    errors: list[str] = []
    prompts: dict[str, bytes] = {}

    for role, relative in sorted(declared.items()):
        label = f"prompts[{role}]"
        if role not in PROMPT_ROLES:
            errors.append(f"prompts: unknown role {role!r}")
            continue
        if not isinstance(relative, str) or not relative.strip():
            errors.append(f"{label}: path must be a non-empty string")
            continue

        path = (directory / relative).resolve()
        if Path(relative).is_absolute() or not path.is_relative_to(root):
            errors.append(f"{label}: path {relative!r} escapes the version directory")
            continue

        try:
            content = path.read_bytes()
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            errors.append(f"{label}: file not found: {relative}")
            continue
        except OSError as exc:
            errors.append(f"{label}: cannot read {relative}: {exc}")
            continue

        if not content.strip():
            errors.append(f"{label}: {relative} is empty")
            continue

        prompts[role] = content

    for role in sorted(REQUIRED_PROMPT_ROLES - set(prompts)):
        if not any(error.startswith(f"prompts[{role}]") for error in errors):
            errors.append(f"prompts: required role {role!r} is missing")

    if errors:
        raise BrainInvalid(version, errors)
    return prompts


def _digest(policy_bytes: bytes, rules_bytes: bytes, prompts: dict[str, bytes]) -> str:
    """Hash a version as one unit: prose, table and every prompt, roles in sorted order."""
    digest = hashlib.sha256()
    digest.update(policy_bytes)
    digest.update(b"\0")
    digest.update(rules_bytes)
    for role in sorted(prompts):
        digest.update(b"\0")
        digest.update(role.encode("utf-8"))
        digest.update(b"\0")
        digest.update(prompts[role])
    return "sha256:" + digest.hexdigest()


def _parse(
    version: str,
    document: dict[str, Any],
    policy_bytes: bytes,
    prompt_bytes: dict[str, bytes],
    brain_hash: str,
) -> Brain:
    """Turn a version directory into an executable Brain."""
    try:
        settings = BrainSettings.model_validate(document.get("settings") or {})
    except ValidationError as exc:
        raise BrainInvalid(version, [f"settings: {_compact(exc)}"]) from exc

    try:
        rules = [Rule.model_validate(entry) for entry in document.get("rules") or []]
    except ValidationError as exc:
        raise BrainInvalid(version, [f"rules: {_compact(exc)}"]) from exc

    errors: list[str] = []

    declared = document.get("policy_version")
    if declared != version:
        errors.append(f"policy_version {declared!r} does not match directory {version!r}")

    for required in settings.required_documents:
        if required.satisfied_by not in APPLICANT_BOOL_FACTS:
            errors.append(
                f"required_documents[{required.id}]: {required.satisfied_by!r} is not a declared boolean fact"
            )

    prompts: dict[str, str] = {}
    for role, content in prompt_bytes.items():
        try:
            prompts[role] = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"prompts[{role}]: not valid UTF-8: {exc}")

    errors.extend(_validate_rules(rules))
    if errors:
        raise BrainInvalid(version, errors)

    return Brain(
        version=version,
        settings=settings,
        rules=rules,
        policy_text=policy_bytes.decode("utf-8"),
        prompts=prompts,
        brain_hash=brain_hash,
    )


def _validate_rules(rules: list[Rule]) -> list[str]:
    """Every way a rule table can fail to be executable, collected rather than short-circuited."""
    if not rules:
        return ["the rule table is empty"]

    errors: list[str] = []
    seen: set[int] = set()
    defaults: list[int] = []

    for rule in rules:
        label = f"rule {rule.id}"
        if rule.id in seen:
            errors.append(f"{label}: duplicate id")
        seen.add(rule.id)

        if not 0.0 <= rule.confidence <= 1.0:
            errors.append(f"{label}: confidence {rule.confidence} outside [0, 1]")
        if not rule.cite.strip():
            errors.append(f"{label}: cite is empty")

        vocabulary = APPLICANT_FACTS | HIT_FACTS if rule.scope == "each_hit" else APPLICANT_FACTS
        for name, condition in rule.when.items():
            if name not in vocabulary:
                errors.append(f"{label}: condition on undeclared fact {name!r}")
            errors.extend(f"{label}: {problem}" for problem in _validate_condition(name, condition))
        for name in rule.evidence:
            if name not in vocabulary:
                errors.append(f"{label}: evidence names undeclared fact {name!r}")

        if not rule.when:
            defaults.append(rule.id)
            if rule.decision != "CLEAR":
                errors.append(f"{label}: the default rule must decide CLEAR, not {rule.decision}")

    if len(defaults) != 1:
        errors.append(f"expected exactly one default rule (empty `when`), found {len(defaults)}")

    return errors


def _validate_condition(name: str, condition: Any) -> list[str]:
    """Check one condition; a bare scalar is an equality test and is always well-formed."""
    if not isinstance(condition, dict):
        return []
    if len(condition) != 1:
        return [f"condition on {name!r} must hold exactly one operator, got {sorted(condition)}"]

    ((operator, operand),) = condition.items()
    if operator not in OPERATORS:
        return [f"condition on {name!r} uses unknown operator {operator!r}"]
    if operator == "in" and not isinstance(operand, list):
        return [f"condition on {name!r}: 'in' expects a list"]
    if operator in ("gte", "lte") and not isinstance(operand, (int, float)):
        return [f"condition on {name!r}: {operator!r} expects a number"]
    return []


def _compact(exc: ValidationError) -> str:
    """Flatten a pydantic error into one line fit for an API response."""
    return "; ".join(".".join(str(part) for part in err["loc"]) + f": {err['msg']}" for err in exc.errors())


def list_versions(brain_dir: Path) -> list[dict[str, Any]]:
    """Every version on the volume, each with whether it would load."""
    root = brain_dir / "versions"
    if not root.is_dir():
        raise BrainUnavailable(f"versions directory not found: {root}")

    versions: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), key=lambda entry: entry.name):
        if not path.is_dir():
            continue
        try:
            brain = load_version(brain_dir, path.name)
        except BrainInvalid as exc:
            versions.append({"version": path.name, "valid": False, "errors": exc.errors})
        except BrainUnavailable as exc:
            versions.append({"version": path.name, "valid": False, "errors": [str(exc)]})
        else:
            versions.append(
                {
                    "version": path.name,
                    "valid": True,
                    "rules": len(brain.rules),
                    "prompts": sorted(brain.prompts),
                    "brain_hash": brain.brain_hash,
                }
            )
    return versions


def activate(brain_dir: Path, version: str) -> tuple[str | None, Brain]:
    """Point the Brain at another version, validating the target before the pointer moves."""
    brain = load_version(brain_dir, version)

    try:
        previous = read_pointer(brain_dir).active_version
    except BrainUnavailable:
        previous = None

    payload = json.dumps({"active_version": version, "previous_version": previous}, indent=2) + "\n"

    pointer = brain_dir / POINTER_FILE
    temporary = pointer.with_name(POINTER_FILE + ".tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, pointer)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise BrainReadOnly(f"cannot record the swap in {pointer}: {exc}") from exc

    return previous, brain
