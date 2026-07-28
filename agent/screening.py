"""The watchlist sweep: the delivered tool, called once per name variant, unioned by subject and entry. (D-009)"""

import hashlib
import importlib.util
from collections.abc import Callable, Iterable
from functools import lru_cache
from itertools import permutations
from pathlib import Path

from agent.constants import MAX_PERMUTED_TOKENS, WATCHLIST_TOOL
from agent.corroborate import corroborate
from agent.schemas import Hit, ScreeningResult, ScreeningTarget

Search = Callable[..., list[dict]]


class WatchlistUnavailable(RuntimeError):
    """The delivered tool is not importable, or its data is not beside it."""


@lru_cache(maxsize=None)
def load_tool(path: str = WATCHLIST_TOOL) -> Search:
    """Import assets/tools/watchlist_search.py in place; there is one copy in the repo and this does not modify it."""
    location = Path(path).resolve()
    spec = importlib.util.spec_from_file_location("watchlist_search", location)
    if spec is None or spec.loader is None:
        raise WatchlistUnavailable(f"cannot import the watchlist tool at {location}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (OSError, ValueError) as exc:
        raise WatchlistUnavailable(f"the watchlist tool at {location} did not load: {exc}") from exc
    return module.watchlist_search


@lru_cache(maxsize=None)
def watchlist_digest(path: str = WATCHLIST_TOOL) -> str:
    """Hash the list the tool itself resolved, so /health reports the data in use rather than a configured path."""
    data = Path(path).resolve().parent.parent / "data" / "watchlist.json"
    try:
        return f"sha256:{hashlib.sha256(data.read_bytes()).hexdigest()}"
    except OSError as exc:
        raise WatchlistUnavailable(f"the watchlist tool has no data at {data}: {exc}") from exc


def name_variants(name: str) -> tuple[str, ...]:
    """The name as given plus its token reorderings; a pure function of the string, blind to the watchlist."""
    cleaned = " ".join(name.split())
    if not cleaned:
        return ()

    tokens = cleaned.split(" ")
    if len(tokens) < 2:
        return (cleaned,)
    if len(tokens) <= MAX_PERMUTED_TOKENS:
        candidates = [" ".join(order) for order in permutations(tokens)]
    else:
        candidates = [cleaned, " ".join(reversed(tokens))]
    return tuple(dict.fromkeys([cleaned, *candidates]))


def sweep(targets: Iterable[ScreeningTarget], min_score: float, search: Search | None = None) -> ScreeningResult:
    """Every target against every variant, keeping the strongest score per (subject, entry)."""
    search = search or load_tool()
    best: dict[tuple[str, str], tuple[ScreeningTarget, dict, bool]] = {}
    searches = 0

    for target in targets:
        for position, variant in enumerate(name_variants(target.name)):
            searches += 1
            for match in search(variant, min_score):
                key = (target.subject_ref, match["entry_id"])
                previous = best.get(key)
                if previous is None or match["score"] > previous[1]["score"]:
                    best[key] = (target, match, position == 0)

    hits = [_hit(target, match, as_given) for target, match, as_given in best.values()]
    hits.sort(key=lambda found: (found.subject_ref, found.entry_id))
    return ScreeningResult(hits=hits, searches=searches)


def _hit(target: ScreeningTarget, match: dict, as_given: bool) -> Hit:
    corroborated, basis = corroborate(target, match)
    return Hit(
        entry_id=match["entry_id"],
        hit_type=match["type"],
        subject=target.subject,
        subject_ref=target.subject_ref,
        name_score=match["score"],
        corroborated=corroborated,
        corroboration_basis=basis,
        name_variant="as_given" if as_given else "reordered",
    )
