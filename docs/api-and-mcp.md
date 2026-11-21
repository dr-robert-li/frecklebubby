# API and MCP

This guide tells you how to connect Claude with MCP and how to use the REST API.

## Connect Claude (MCP)

Frecklebubby has an MCP server at `<BASE_URL>/mcp`. Claude can then log entries, start timers, read reports and
search the knowledge library for you. Claude can also read the day and night plan, the next sleep time, the
milestones, the insights and the support report.

You can say it in plain words ("she had 120 ml at 2 and I put her in the car seat"): Claude uses one tool per kind
of entry, or the `log_in_plain_words` tool, and the entry is saved, not only read.

1. On claude.ai, open **Settings > Connectors > Add custom connector**.
2. Enter `<BASE_URL>/mcp` and add it.
3. Select **Connect** and sign in with Google or GitHub (the same account as in Frecklebubby).

The connector then also shows in the Claude mobile app for the same account. Each family member does these steps
in their own Claude account.

**Local MCP clients** (for example Claude Desktop or Claude Code on the same computer) can use stdio. No sign-in
applies; the tools act as one user:

```bash
docker compose exec app frecklebubby-mcp --stdio --user you@example.com
# without containers:
uv run frecklebubby-mcp --stdio --user you@example.com
```

`--user` can be left out when the database has only one user.

> Tested with a real Clerk development instance through a Cloudflare Tunnel (0.3.1).

## REST API

All functions of the app are in the REST API at `<BASE_URL>/api/v1`. The API reference (OpenAPI) is at
`<BASE_URL>/api/docs`, and the machine-readable file at `<BASE_URL>/api/openapi.json`.

For scripts, make a personal access token in **Settings > API tokens**. The app shows the token only once.

```bash
TOKEN=fb_pat_...
# list children
curl -H "Authorization: Bearer $TOKEN" https://frecklebubby.example.com/api/v1/children
# log a 120 ml formula bottle now for child 1
curl -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"type\":\"bottle\",\"started_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"data\":{\"amount_ml\":120,\"milk_type\":\"Formula\"}}" \
  https://frecklebubby.example.com/api/v1/children/1/entries
```

To list entries, use `GET /children/{id}/entries`. It gives the newest entries first. The parameters are:

- `type`: one type. Give it again for each more type (`?type=bottle&type=pump`).
- `from`, `to`: the time range of the start time.
- `sort`: `time` (default), `duration`, `volume`, `weight`, `height`, `head` or `temperature`. With an amount, the
  list has only the entries that have this amount.
- `dir`: `desc` (default: newest or largest first) or `asc`.
- `limit` (default 50, maximum 1000) and `offset` for the next page.

`GET /children/{id}/export.csv` gives the entries as a CSV file. It accepts `type`, `from`, `to`, `sort` and `dir`
in the same way, and has no limit. With no parameter it gives all entries, the oldest first.

A time without an offset is read in the family time zone. Errors come back as `{"detail": "plain message"}`.
