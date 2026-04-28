"""Salesforce — STUB. v1 routes through Zapier; direct API can come later.

Pattern:
    Hermes -> POST signed JSON to ZAPIER_SALESFORCE_WEBHOOK ->
    Zap routes to the matching Salesforce action (lookup, create note, log call,
    update opportunity stage, etc.) -> Zap returns 200 immediately and an async
    update lands back via a return webhook (also Zapier).

Planned surface:
    lookup_account(name_or_domain: str) -> Account | None
    log_email_to_account(account_id: str, summary: str, message_link: str) -> None
    update_opp_stage(opp_id: str, new_stage: str, note: str) -> None
    create_task(opp_id: str, title: str, due: date) -> None

Design notes:
- Sign every request with HMAC-SHA256(ZAPIER_SHARED_SECRET, body) in the
  X-Hermes-Sig header so Zapier can verify it's us before doing the write.
- Idempotency key: include 'request_id' (UUIDv4) in payload, store in state.kv
  for 24h to prevent double-writes on retries.
- For lookups that need a synchronous response, build a paired Zap that POSTs
  back to a separate Hermes endpoint — but v1 lookups can be cached and
  refreshed on a schedule instead, avoiding the inbound webhook.
"""
