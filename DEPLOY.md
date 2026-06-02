# Deployment Runbook — DigitalOcean App Platform

This is the one-time bootstrap plus the ongoing operations guide for the IETF
Working Group Activity Tracker. It assumes Milestone 2 is merged to `main`.

> **Do the validation spot-check (Step 7) on a small sample before the full
> backfill (Step 8).** That is the gate the build spec calls for.

---

## 0. Architecture recap

One App Platform app, plus a standalone managed Postgres and GitHub Actions:

| Piece | Role | Auth |
|---|---|---|
| `api` Web Service | React debug UI + JSON API + MCP-over-HTTP + `/health` | Basic (UI) / Bearer (MCP) |
| `migrate` Job (PRE_DEPLOY) | `alembic upgrade head` on each deploy | — |
| **standalone** managed Postgres | storage; reachable in-VPC by the app and over SSL by Actions | SSL + role |
| GitHub Actions `pipeline.yml` | weekly ingest + 3-hourly poll + on-demand `workflow_dispatch` | repo secrets |
| GitHub Actions `deploy.yml` | `doctl apps update` on push to `main` | repo secrets |

The pipeline (ingestion + LLM batches) runs in **GitHub Actions**, not on the
app — there is no always-on worker.

---

## 1. Prerequisites

- A DigitalOcean account, and [`doctl`](https://docs.digitalocean.com/reference/doctl/how-to/install/) authenticated: `doctl auth init`.
- This repo on GitHub at `SwaggerAllen/IETF-Tracker-MCP` (matches `.do/app.yaml`).
- An Anthropic API key with Batch access.
- `main` is green in CI.

Generate the shared secrets you'll need (keep them somewhere safe):

```sh
openssl rand -hex 24   # MCP_BEARER_TOKEN
openssl rand -hex 16   # UI_BASIC_AUTH_PASS
```

---

## 2. Create the managed Postgres cluster

The app spec references a cluster named `wg-activity-db`. Create it first:

```sh
doctl databases create wg-activity-db \
  --engine pg --version 16 \
  --size db-s-1vcpu-1gb --num-nodes 1 --region nyc

# Wait until status is "online", then capture the id and the PUBLIC connection URI:
DB_ID=$(doctl databases list --format ID,Name --no-header | awk '/wg-activity-db/{print $1}')
doctl databases connection "$DB_ID" --format URI --no-header
```

That URI (host, port, `defaultdb`, `doadmin`, password, `?sslmode=require`) is the
**public** connection string GitHub Actions will use. The app itself uses the
in-VPC binding `${db.DATABASE_URL}` automatically — you do not set `DATABASE_URL`
on the app.

> **Least privilege (recommended):** instead of `doadmin`, create a dedicated
> role + database for the app and use that role's URI for Actions:
> ```sh
> doctl databases db create "$DB_ID" wgtracker
> doctl databases user create "$DB_ID" wgtracker_app
> ```
> Grant it rights on the `wgtracker` database, and build the URI from that user.

### Trusted sources (firewall)

DO managed databases deny all external connections by default. GitHub-hosted
runners have **dynamic IPs**, so you can't IP-allowlist them. Two options:

1. **Pragmatic (single-user):** allow public connections and rely on
   `sslmode=verify-full` + a strong, dedicated-role password. Add the App as a
   trusted source so in-VPC traffic is covered:
   ```sh
   APP_ID=<set after Step 3>
   doctl databases firewalls append "$DB_ID" --rule app:"$APP_ID"
   ```
   Leave general inbound open (no IP rule) so Actions can connect over TLS.
2. **Tighter:** run the pipeline from a self-hosted runner on a fixed IP and
   allowlist only that IP. More infra; only worth it if you're uneasy about (1).

For `verify-full`, download the cluster CA cert (`doctl databases get "$DB_ID"`
exposes it / the console offers a download) and append `&sslmode=verify-full&sslrootcert=...`
to the Actions `DATABASE_URL`. `sslmode=require` (encrypt, don't verify host) is
the simpler baseline.

---

## 3. Create the App

```sh
doctl apps create --spec .do/app.yaml --format ID --no-header
# => save this as APP_ID
```

This provisions the `api` service and the `migrate` job, and attaches the
`wg-activity-db` cluster. The first deploy will fail health checks until the
secrets in Step 4 are set — that's expected.

---

## 4. Set the App's secrets

Set these on the **`api`** service (Console → your app → Settings → `api` →
Environment Variables, or via an out-of-git spec). `GITHUB_REPO` is already a
plain value in the spec; the rest are secrets:

| Key | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your Anthropic key |
| `UI_BASIC_AUTH_USER` | a username for the debug UI |
| `UI_BASIC_AUTH_PASS` | the `openssl` password from Step 1 |
| `MCP_BEARER_TOKEN` | the `openssl` token from Step 1 |
| `GITHUB_DISPATCH_TOKEN` | a fine-grained PAT with **Actions: read/write** on this repo |
| `COST_CEILING_USD` | `5` for the validation run (raise later) |

`DATABASE_URL` is **not** set here — it's bound to the cluster via
`${db.DATABASE_URL}` in `.do/app.yaml`.

> Secrets via CLI: keep a local, git-ignored `app.prod.yaml` (a copy of
> `.do/app.yaml` with `value:` filled in for each SECRET) and
> `doctl apps update "$APP_ID" --spec app.prod.yaml`. Never commit it.

Redeploy after setting secrets; the `/health` check should go green.

---

## 5. GitHub repo secrets

Repo → Settings → Secrets and variables → Actions → **New repository secret**:

| Secret | Value |
|---|---|
| `DIGITALOCEAN_ACCESS_TOKEN` | a DO API token (Console → API) |
| `DIGITALOCEAN_APP_ID` | the `APP_ID` from Step 3 |
| `DATABASE_URL` | the **public** cluster URI from Step 2 (`?sslmode=require` or `verify-full`) |
| `ANTHROPIC_API_KEY` | your Anthropic key |

`deploy.yml` no-ops safely until `DIGITALOCEAN_APP_ID` is present; once set, every
push to `main` runs `doctl apps update --spec .do/app.yaml --wait`.

---

## 6. Deploy

- Auto: push to `main` (or merge the PR) → `deploy.yml` runs.
- Manual: Actions → **Deploy to DigitalOcean** → *Run workflow*.

The `migrate` PRE_DEPLOY job runs `alembic upgrade head` against the cluster
before the new `api` rolls out. Confirm:

```sh
curl -s https://<your-app-url>/health        # {"status":"ok"}
```

---

## 7. Validation spot-check (do this BEFORE backfill)

Keep `COST_CEILING_USD=5` so spend is hard-capped, then run one working group
through the pipeline from the Actions tab:

1. Actions → **Pipeline** → *Run workflow* → stage **`ingest`**. This fetches the
   `mls` (+ `mimi`, `cfrg`) archives, reconstructs threads, syncs drafts, and
   submits a summarization batch (auto-stops at the ceiling).
2. Wait, then run **Pipeline → `poll`** once or twice (batches take up to ~24h;
   usually under an hour). `poll` applies summaries and submits categorization;
   the next `poll` applies categories.
3. Inspect, and **verify against the original threads**:
   - Debug UI: `https://<app>/` (Basic auth) — threads, summaries, key positions,
     consensus, **source links**, drafts, and the Pipeline tab's cost + batches.
   - or the API: `curl -u user:pass https://<app>/api/threads`, `/api/cost`.
   Check that: summaries reflect the threads, **source URLs resolve to the right
   messages**, categorization is sensible, and `cost` is within the $20–50
   backfill estimate trajectory.

If something's off, fix before spending more. The most likely things to validate
against reality (flagged in `PLAN.md` §14): the mbox export shape and the
datatracker field mapping.

---

## 8. Backfill + go live

Once you're satisfied:

- Raise the ceiling: set `COST_CEILING_USD` to `200` (your budget) on `api`, and
  bump it for Actions too if you add it there. Redeploy.
- Run **Pipeline → `ingest`** again to summarize the rest, then `poll` until
  batches drain (`/api/cost` and `/api/batches` track progress).
- The **schedules in `pipeline.yml` now run on their own** (weekly ingest,
  3-hourly poll) since they only fire from `main`.

---

## 9. Connect the MCP server to Claude

The MCP server is at `https://<your-app-url>/mcp` (Streamable HTTP), bearer-auth
with `MCP_BEARER_TOKEN`. In Claude Desktop / Code, add a remote MCP server with
that URL and an `Authorization: Bearer <MCP_BEARER_TOKEN>` header. The tools
(`search_threads`, `get_thread_detail`, `recent_activity`, `topic_overview`,
`list_drafts`, `get_draft`, `draft_discussion_history`) all return source URLs so
Claude can cite them.

---

## 10. Operations

- **Cost / budget:** `GET /api/cost` or the UI Pipeline tab; the worker refuses to
  submit new batches once spend ≥ `COST_CEILING_USD`.
- **Re-trigger a stage:** UI Pipeline tab buttons (they `workflow_dispatch`
  `pipeline.yml`), or Actions → Pipeline → Run workflow.
- **Add a working group / topic:** edit `config.yaml`, commit, redeploy. Topic
  changes take effect on the next `recategorize` (Pipeline → `recategorize`) —
  cheap, no re-summarization.
- **Logs:** App Platform aggregates the `api` service's structured JSON logs;
  pipeline logs live in the Actions run logs.
- **Scheduled-workflow auto-disable:** GitHub disables crons after 60 days of repo
  inactivity — push something or re-enable in the Actions tab if it goes quiet.

---

## 11. Teardown

```sh
doctl apps delete "$APP_ID"
doctl databases delete "$DB_ID"
```

Revoke the DO API token, the GitHub PAT, and rotate the Anthropic key if needed.
