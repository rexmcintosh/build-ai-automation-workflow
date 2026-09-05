# Ultimate Portugal writing engine

**Contract:** v1.0 · **Date:** 2026-09-05 · **Observed entrypoints:** `ultimate-portugal/engine/morning-run.sh`, `engine/poller-cron.sh`, `engine/seo-run.sh`

## Purpose and authority

**Default mode:** deploy-capable, change-producing editorial workflow. The weekday morning run performs the engine’s headless workflow; the poller processes decisions; the Monday SEO transaction decides, acts through its checker, and reports to the owner. Canonical editorial state is the Ultimate Portugal `engine/` data and decision records.

The jobs may mutate and publish only work authorized by their engine prompts, decision data, and SEO transaction. Shared writer locking prevents conflicting edits. They must not act on unrelated repositories or continue past a failed SEO transaction stage.

**Secrets, names only:** `VENICE_API_KEY`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `BENTO_SHARED_PUBLISHABLE_KEY`, `BENTO_SHARED_SECRET_KEY`, `BENTO_ULTIMATEPORTUGAL_SITE_UUID`, `DRAFT_APPROVAL_SECRET`, `DATAFORSEO_USERNAME`, `DATAFORSEO_PASSWORD`, plus additional keys loaded by the poller from `~/.env`.

## Success and evidence

Success is a completed, non-skipped lock-held run plus the matching engine decision, revision, deployment, or owner-report record. Inspect `~/projects/.session-gc/writing-engine-morning.log`, `writing-engine-poller.log`, `writing-engine-seo.log`, the Ultimate Portugal `engine/` state, and the SEO transaction report. A process exit does not prove a publish or email reached its recipient.

## Failure, escalation, and gaps

Morning and SEO runs have timeouts; lock contention is a skip or bounded wait. There is no common alert for failed scheduled runs. The poller imports the whole `~/.env`, which exceeds narrow secret custody. Contract ownership belongs with this site, not this automation repository.
