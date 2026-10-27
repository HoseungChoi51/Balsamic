"""The lineage forest: typed edges from parent links, rounds as columns, a stable order for drawing without a layout engine."""


def edges_of(rows):
    ids = {row["id"] for row in rows}
    edges = []
    for row in rows:
        for link in row.get("parent_links") or []:
            edges.append({"from": link["id"], "to": row["id"], "kind": link.get("kind", "revision"), "external": link["id"] not in ids})
    return edges


def rounds_of(rows):
    """Round numbers: the recorded one, else the generation (roots are round 0, children one more than their deepest parent)."""
    by_id = {row["id"]: row for row in rows}
    memo = {}

    def generation(identity, seen=()):
        if identity in memo:
            return memo[identity]
        row = by_id.get(identity)
        if row is None or identity in seen:
            return 0
        if row.get("round") is not None:
            memo[identity] = row["round"]
            return memo[identity]
        parents = [link["id"] for link in row.get("parent_links") or [] if link["id"] in by_id]
        memo[identity] = 1 + max((generation(p, (*seen, identity)) for p in parents), default=-1)
        return memo[identity]
    return {row["id"]: generation(row["id"]) for row in rows}


def layout(rows):
    """Nodes with a column (round) and a lane (depth-first order under their first parent): a forest the page can draw."""
    rounds = rounds_of(rows)
    by_id = {row["id"]: row for row in rows}
    children = {}
    roots = []
    for row in rows:
        parents = [link["id"] for link in row.get("parent_links") or [] if link["id"] in by_id]
        if parents:
            children.setdefault(parents[0], []).append(row["id"])
        else:
            roots.append(row["id"])
    lane = {}
    counter = [0]

    def visit(identity):
        lane[identity] = counter[0]; counter[0] += 1
        for child in sorted(children.get(identity, []), key=lambda c: (by_id[c].get("created_at") or "", c)):
            visit(child)
    for root in sorted(roots, key=lambda r: (by_id[r].get("created_at") or "", r)):
        visit(root)
    return [{"id": row["id"], "round": rounds[row["id"]], "lane": lane.get(row["id"], 0), "stage": row["stage"], "label": row.get("label"), "title": row["title"], "short_title": row.get("short_title"),
             "family": row.get("family"), "autonomous": row.get("autonomous", False), "stop_reason": row.get("stop_reason"),
             "stop_label": (row.get("stop") or {}).get("label")} for row in rows], max(rounds.values(), default=0)
