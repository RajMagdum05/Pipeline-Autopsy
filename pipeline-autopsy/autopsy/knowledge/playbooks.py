"""Load and retrieve curated playbooks using exact diagnostic keys."""

from pathlib import Path

import yaml
from sqlalchemy import text

from autopsy.db.models import PlaybookRecord


_ROOT = Path(__file__).resolve().parents[2]


def _parse(path, pack):
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise ValueError(f"Playbook {path} is missing YAML front matter")
    _, front_matter, body = raw.split("---", 2)
    metadata = yaml.safe_load(front_matter) or {}
    if not isinstance(metadata, dict) or not metadata.get("id") or not metadata.get("title"):
        raise ValueError(f"Playbook {path} requires id and title")
    match = metadata.get("match", {})
    if not isinstance(match, dict):
        raise ValueError(f"Playbook {path} match must be a mapping")
    return {
        "id": str(metadata["id"]), "title": str(metadata["title"]),
        "match": match, "body": body.strip(), "pack": pack,
    }


def load_playbooks(root=None):
    """Parse generic and pack playbooks from disk, in deterministic order."""
    root = Path(root) if root else _ROOT
    loaded = []
    generic_dir = root / "playbooks"
    if generic_dir.exists():
        loaded.extend(_parse(path, "generic") for path in sorted(generic_dir.glob("*.md")))
    packs_dir = root / "packs"
    if packs_dir.exists():
        for directory in sorted(packs_dir.glob("*/playbooks")):
            loaded.extend(_parse(path, directory.parent.name) for path in sorted(directory.glob("*.md")))
    ids = [item["id"] for item in loaded]
    if len(ids) != len(set(ids)):
        raise ValueError("Playbook IDs must be unique")
    return loaded


def sync_playbooks(db, root=None):
    """Upsert current curated files and remove stale rows."""
    playbooks = load_playbooks(root)
    wanted = {item["id"] for item in playbooks}
    for item in playbooks:
        row = db.get(PlaybookRecord, item["id"])
        if row is None:
            row = PlaybookRecord(id=item["id"])
            db.add(row)
        row.title = item["title"]
        row.match = item["match"]
        row.body = item["body"]
        row.pack = item["pack"]
    for row in db.query(PlaybookRecord).all():
        if row.id not in wanted:
            db.delete(row)
    db.flush()
    return playbooks


def _stage_type(stage):
    return str(stage or "").split("@", 1)[0]


def _score(playbook, finding, spans):
    match = playbook.match or {}
    observations = finding.get("observations", [])
    score = 0
    check_id = match.get("check_id")
    if check_id and any(row.get("code") == check_id for row in observations):
        score += 8
    error_type = match.get("error_type")
    if error_type and any(span.get("error_type") == error_type
                          and _stage_type(span.get("stage_name") or span.get("stage")) == _stage_type(finding.get("stage"))
                          for span in spans):
        score += 4
    if match.get("classification") and match["classification"] == finding.get("classification"):
        score += 2
    if match.get("stage") and match["stage"] == _stage_type(finding.get("stage")):
        score += 1
    return score


def _text_fallback(db, findings):
    query_text = " ".join(
        [str(finding.get("classification") or "") for finding in findings]
        + [str(row.get("code") or "") for finding in findings for row in finding.get("observations", [])]
    ).strip()
    terms = [term.lower() for term in query_text.replace("_", " ").split() if len(term) > 2]
    if not terms:
        return []
    if db.bind.dialect.name == "postgresql":
        sql = text("""SELECT p.id, p.title, p.body, p.pack, p.match,
                    ts_rank_cd(to_tsvector('english', p.title || ' ' || p.body), plainto_tsquery('english', :q)) AS rank
                    FROM playbooks p WHERE to_tsvector('english', p.title || ' ' || p.body)
                    @@ plainto_tsquery('english', :q) ORDER BY rank DESC, p.id LIMIT 1""")
        rows = db.execute(sql, {"q": query_text}).mappings().all()
        return [dict(row) for row in rows if row["rank"] > 0]
    rows = db.query(PlaybookRecord).all()
    ranked = []
    for row in rows:
        haystack = f"{row.title} {row.body}".lower()
        rank = sum(term in haystack for term in terms)
        if rank:
            ranked.append((rank, row))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].id))
    return [{"id": row.id, "title": row.title, "body": row.body, "pack": row.pack,
             "match": row.match, "rank": rank} for rank, row in ranked[:1]]


def retrieve(db, findings, spans=()):
    """Return the best two keyed matches, otherwise one lexical fallback."""
    sync_playbooks(db)
    records = db.query(PlaybookRecord).all()
    scored = []
    for playbook in records:
        score = max((_score(playbook, finding, spans) for finding in findings), default=0)
        if score >= 2:
            scored.append((score, playbook))
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    if scored:
        return [{"playbook_id": row.id, "title": row.title, "body": row.body,
                 "pack": row.pack, "score": score} for score, row in scored[:2]]
    return [{"playbook_id": row["id"], "title": row["title"], "body": row["body"],
             "pack": row["pack"], "score": row.get("rank", 0)}
            for row in _text_fallback(db, findings)]


__all__ = ["load_playbooks", "retrieve", "sync_playbooks"]
