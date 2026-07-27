"""Reference mock tool: watchlist_search(name) -> list[match].
Candidates may use this as-is or reimplement. Uses stdlib difflib for fuzzy scoring.
Contract:
  watchlist_search(name: str, min_score: float = 0.75) -> list[dict]
  each match: {entry_id, matched_name, score (0..1), type, program, country, dob}
"""
import json, difflib, os
_WL = json.load(open(os.path.join(os.path.dirname(__file__), "..", "data", "watchlist.json"), encoding="utf-8"))

def _score(a, b):
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()

def watchlist_search(name, min_score=0.75):
    out = []
    for e in _WL:
        names = [e["name"]] + e.get("aliases", [])
        best = max(_score(name, n) for n in names)
        if best >= min_score:
            out.append({"entry_id": e["entry_id"], "matched_name": e["name"], "score": round(best, 3),
                        "type": e["type"], "program": e["program"], "country": e["country"], "dob": e.get("dob")})
    return sorted(out, key=lambda m: m["score"], reverse=True)

if __name__ == "__main__":
    import sys
    print(json.dumps(watchlist_search(sys.argv[1] if len(sys.argv) > 1 else "Viktor Petrov"), indent=2))
