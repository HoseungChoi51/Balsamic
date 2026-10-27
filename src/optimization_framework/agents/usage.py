"""Per-call LLM usage of harness agents: tokens, cache, reasoning, and cost.

Pi prices every call from its model catalog (`cost_usd`). Only calls billed through
an API key are charges (`charged_usd`); subscription calls keep their list-price
estimate for comparison but are not counted against the campaign's API cap.

Each call names the agent run it was made in (run_id) and the researcher's request that run serves (root_thread_id,
root_message_id, root_run_id: the request root of campaigns/mandates.py), so a mandate's model spend is the sum of its own
request's calls (spent()). Calls recorded before this, and report stages started outside a request, name none.
"""
import json

from .families import family_of

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS llm_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT NOT NULL UNIQUE,
        campaign_id TEXT NOT NULL, agent_id TEXT NOT NULL, role TEXT, provider TEXT, model TEXT,
        family TEXT, thinking_level TEXT, billing TEXT NOT NULL,
        input INTEGER NOT NULL, output INTEGER NOT NULL, cache_read INTEGER NOT NULL, cache_write INTEGER NOT NULL,
        reasoning INTEGER NOT NULL, total_tokens INTEGER NOT NULL, cost_usd REAL, charged_usd REAL NOT NULL,
        occurred_at TEXT NOT NULL, run_id TEXT, root_thread_id TEXT, root_message_id TEXT, root_run_id TEXT)""",
    "CREATE INDEX IF NOT EXISTS llm_usage_campaign_time ON llm_usage(campaign_id, occurred_at)",
)
ROOT_COLUMNS = ("run_id", "root_thread_id", "root_message_id", "root_run_id")
COLUMNS = ("event_key, campaign_id, agent_id, role, provider, model, family, thinking_level, billing, input, output, cache_read, "
           "cache_write, reasoning, total_tokens, cost_usd, charged_usd, occurred_at, " + ", ".join(ROOT_COLUMNS))
INSERT = f"INSERT OR IGNORE INTO llm_usage({COLUMNS}) VALUES ({','.join('?' * (18 + len(ROOT_COLUMNS)))})"
LEGACY_PROVIDER = "openai-codex"
SUBSCRIPTION_PROVIDERS = {"openai-codex"}


def ensure(store):
    with store.connection() as db:
        for statement in SCHEMA:
            db.execute(statement)
        present = {row[1] for row in db.execute("PRAGMA table_info(llm_usage)").fetchall()}
        for column in ROOT_COLUMNS:
            if column not in present:   # a table made before calls named their run: old rows keep none
                db.execute(f"ALTER TABLE llm_usage ADD COLUMN {column} TEXT")
        db.execute("CREATE INDEX IF NOT EXISTS llm_usage_campaign_root ON llm_usage(campaign_id, root_thread_id)")
        empty = db.execute("SELECT 1 FROM llm_usage LIMIT 1").fetchone() is None
    if empty:
        backfill(store)


def _row(campaign_id, agent, event_key, event, occurred_at, run_id=None, root=None):
    usage = event.get("usage") or {}
    provider = event.get("provider") or agent.get("provider") or LEGACY_PROVIDER
    model = event.get("model") or agent.get("model")
    billing = event.get("billing") or ("subscription" if provider in SUBSCRIPTION_PROVIDERS else "unknown")
    cost = usage.get("cost_usd")
    return (event_key, campaign_id, agent["id"], agent.get("role"), provider, model, family_of(provider, model),
            event.get("thinking_level") or agent.get("reasoning_effort"), billing,
            int(usage.get("input", 0)), int(usage.get("output", 0)), int(usage.get("cacheRead", 0)),
            int(usage.get("cacheWrite", 0)), int(usage.get("reasoning", 0)), int(usage.get("totalTokens", 0)),
            cost, (cost or 0.0) if billing == "api" else 0.0, occurred_at,
            run_id, *((root or {}).get(key) for key in ("thread_id", "message_id", "run_id")))


def record(store, campaign_id, agent, event_key, event, *, run_id=None, root=None):
    """Idempotent per harness event; returns the amount charged to the API cap. run_id is the agent run the call was made in
    (the event's own when it names one), root the researcher's request that run serves."""
    root = root if isinstance(root, dict) and root.get("thread_id") else None
    row = _row(campaign_id, agent, event_key, event, event.get("occurred_at"), event.get("run_id") or run_id, root)
    with store.connection() as db:
        inserted = db.execute(INSERT, row).rowcount
    return row[16] if inserted else 0.0


def backfill(store):
    """Import calls recorded before per-call accounting; their model comes from the agent."""
    agents = {a["id"]: a for a in store.list("agent_session")}
    with store.connection() as db:
        rows = db.execute("SELECT campaign_id, event_key, body, payload_ref FROM agent_events "
                          "WHERE json_extract(body, '$.event_type') = 'pi.assistant.message'").fetchall()
        for campaign_id, event_key, body, reference in rows:
            event = json.loads(body)
            payload = event.get("payload")
            if payload is None and reference:
                raw = db.execute("SELECT body FROM agent_payloads WHERE digest=?", (reference,)).fetchone()
                payload = json.loads(raw[0]) if raw else {}
            agent = agents.get(event.get("agent_id"))
            if not agent or not (payload or {}).get("usage"):
                continue
            db.execute(INSERT, _row(campaign_id, agent, event_key, payload, payload.get("occurred_at") or event["occurred_at"]))


def charged(store, campaign_id):
    with store.connection() as db:
        return db.execute("SELECT COALESCE(SUM(charged_usd),0) FROM llm_usage WHERE campaign_id=?", (campaign_id,)).fetchone()[0]


def spent(store, campaign_id, root=None, since=None):
    """API dollars charged under one request (root: thread, message, run, matched as mandates.same_root matches them), or, for
    no root, in the whole campaign since a time: what a mandate's model envelope counts."""
    where, args = "campaign_id=?", [campaign_id]
    if root is not None:
        where += " AND root_thread_id=?"
        args.append(root.get("thread_id"))
        if root.get("message_id"):
            where += " AND root_message_id=?"
            args.append(root["message_id"])
        else:
            where += " AND root_message_id IS NULL AND root_run_id=?"
            args.append(root.get("run_id"))
    if since is not None:
        where += " AND occurred_at>=?"
        args.append(since)
    with store.connection() as db:
        return db.execute(f"SELECT COALESCE(SUM(charged_usd),0) FROM llm_usage WHERE {where}", args).fetchone()[0]


def last_thinking_levels(store, campaign_id):
    """Each agent's thinking level at its latest call: what the chosen level came to on the model."""
    with store.connection() as db:
        return dict(db.execute("SELECT agent_id, thinking_level FROM llm_usage WHERE id IN "
                               "(SELECT MAX(id) FROM llm_usage WHERE campaign_id=? GROUP BY agent_id)", (campaign_id,)).fetchall())


BUCKETS = {"hour": "%Y-%m-%dT%H:00:00Z", "day": "%Y-%m-%dT00:00:00Z"}
TOTALS = ("COUNT(*) AS calls, COALESCE(SUM(input),0) AS input, COALESCE(SUM(output),0) AS output, "
          "COALESCE(SUM(cache_read),0) AS cache_read, COALESCE(SUM(cache_write),0) AS cache_write, "
          "COALESCE(SUM(reasoning),0) AS reasoning, COALESCE(SUM(total_tokens),0) AS total_tokens, "
          "SUM(cost_usd) AS cost_usd, COUNT(cost_usd) AS priced_calls, COALESCE(SUM(charged_usd),0) AS charged_usd, "
          "MIN(occurred_at) AS first_at, MAX(occurred_at) AS last_at")


def summary(store, campaign_id, *, since=None, bucket="hour"):
    where, args = "campaign_id=?", [campaign_id]
    if since:
        where += " AND occurred_at>=?"
        args.append(since)
    with store.connection() as db:
        def rows(query, params=args):
            return [dict(row) for row in db.execute(query, params).fetchall()]
        totals = rows(f"SELECT {TOTALS} FROM llm_usage WHERE {where}")[0]
        groups = {key: rows(f"SELECT {columns}, {TOTALS} FROM llm_usage WHERE {where} GROUP BY {columns} ORDER BY total_tokens DESC")
                  for key, columns in (("by_model", "family, provider, model, billing"), ("by_agent", "agent_id, role"),
                                       ("by_thinking", "provider, model, thinking_level"))}
        series = rows(f"SELECT strftime('{BUCKETS[bucket]}', occurred_at) AS bucket, {TOTALS} FROM llm_usage "
                      f"WHERE {where} GROUP BY bucket ORDER BY bucket")
    return {"campaign_id": campaign_id, "since": since, "bucket": bucket, "totals": totals, **groups, "series": series}
