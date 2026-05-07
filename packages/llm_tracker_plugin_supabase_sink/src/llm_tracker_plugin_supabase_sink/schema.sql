-- llm_tracker_plugin_supabase_sink v0.1 schema (ADR-0007 reference plugin).
--
-- This is the byte-exact DDL applied to the operator's Supabase project on
-- 2026-05-08 via `mcp__supabase__apply_migration` (migration names:
-- `create_exchanges_table` and `enable_rls_on_exchanges`). Checked into the
-- repo for reproducibility — re-creating a fresh sink target is just running
-- this file end-to-end.
--
-- service_role bypasses RLS at the Postgres level; the plugin (which uses
-- the service_role key) is unaffected by `enable row level security`.
-- Anon / authenticated roles are locked out — protects the prompt + response
-- payload if the anon (publishable) key ever leaks.

create table public.exchanges (
  -- Identity
  exchange_id text primary key,
  session_id text not null,

  -- Timestamps
  ts_started_ms bigint not null,                          -- epoch ms when the proxy received the request
  ts_inserted timestamptz not null default now(),         -- when Supabase wrote this row

  -- Provenance
  mode text not null,                                     -- proxy mode at the time (L | A | R)
  endpoint text not null,                                 -- e.g. "v1/messages"
  model_requested text,
  model_served text,
  stop_reason text,

  -- Usage (Anthropic SSE message_start + message_delta)
  input_tokens int,
  output_tokens int,
  cache_creation_input_tokens int,
  cache_read_input_tokens int,

  -- Content (extracted by the plugin's SSE parser; nullable for hooks
  -- that don't reach assembly, e.g. blocked / aborted exchanges)
  request_text text,
  response_text text,
  raw_request jsonb,
  raw_response jsonb,

  -- Plugin-side identity for forensics
  source text not null                                    -- e.g. "supabase_sink/0.1.0"
);

comment on table public.exchanges is
  'llm-tracker exchange records uploaded by llm_tracker_plugin_supabase_sink. '
  'See docs/decisions/0007-central-server-as-optional-plugin.md and '
  'docs/worklog/2026-05-07-supabase-sink.md for context.';

create index idx_exchanges_session on public.exchanges (session_id, ts_started_ms);
create index idx_exchanges_inserted on public.exchanges (ts_inserted);

alter table public.exchanges enable row level security;
