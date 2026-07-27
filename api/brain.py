import json
from pathlib import Path


class BrainUnavailable(RuntimeError):
    """The Company Brain volume is missing, unreadable, or inconsistent."""


def active_version(brain_dir: Path) -> str:
    """Return the active Brain version, read fresh so a swap needs no restart."""
    pointer = brain_dir / "active_version.json"
    try:
        version = json.loads(pointer.read_text(encoding="utf-8"))["active_version"]
    except FileNotFoundError as exc:
        raise BrainUnavailable(f"pointer file not found: {pointer}") from exc
    except (json.JSONDecodeError, KeyError) as exc:
        raise BrainUnavailable(f"pointer file malformed: {pointer}") from exc

    policy = brain_dir / "versions" / version / "screening_policy.md"
    if not policy.is_file():
        raise BrainUnavailable(f"active version {version!r} has no policy at {policy}")

    return version
