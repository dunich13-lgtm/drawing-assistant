# И4 — Day 0 course workspace

This folder holds the И4 course work (source: maitapp.com/i4/programa/day0/).

## Layout
- `CLAUDE.md` — this file; instructions Claude reads at the start of every session
- `specs/` — one spec per feature, made with the implement-spec workflow (see below)
- `Meta-brain/` — Obsidian vault, the "second brain" (Енграм idea). Claude may read and search it.
- `linear/` — notes on the Linear workspace (project name, task conventions)
- `.env` — secret keys (Gemini, OpenRouter). **Never commit it, never print it.** `.env.example` shows the variable names.
- `scripts/check-ai-keys.ps1` — checks both keys with one tiny free request each.

## Second brain: Meta-brain (Obsidian vault)
- `Meta-brain/` is its own Obsidian vault. Claude reads/writes it as plain files in this folder.
- It is LOCAL ONLY (gitignored, user's choice): never commit, push or upload its notes.
- The Obsidian MCP tools (`mcp__obsidian__*`) are connected to a DIFFERENT vault ("Arch explanatory note", work). Don't read or change that vault for this project unless asked.

## Issue tracker: Linear
- Connected via the official Linear connector. Team **Nino** (key `NIN`), project **Drawing assistant**.
- `/to-tickets` and any new tasks go to that project, in team Nino. Don't touch NIN-1…NIN-4 (Linear welcome issues).
- Ask before deleting or bulk-changing issues.

## AI models (outside Claude) — FREE TIER ONLY, no payments
- Main: Google Gemini free tier (`GEMINI_*` in `.env`). Real free limits (checked 2026-11-26):
  - `gemini-3.5-flash-lite` — everyday/bulk: 15/min, 500/day
  - `gemini-3.8-flash` and `gemini-3.6-flash` — smart (JEV judge, hard drawings): 5/min, 20/day each
  - 250K tokens/min each. Daily limits reset at midnight Pacific (10:00 Bulgaria). Busy (503) calls may still count, so don't retry in tight loops; batch jobs must wait ~4 s between Lite calls. Free-tier content may be used by Google to improve products — never send confidential/client drawings to it.
- Backup: OpenRouter, `:free` models only (`OPENROUTER_*`), ~50 requests/day, 20/min.
- Never add billing, buy credits, or call a paid model. On rate-limit errors (HTTP 429), wait and retry, or fall back to the other provider.
- Both use the OpenAI-style chat API, so switching provider = changing base URL, key and model.

## Voice and images
- Voice dictation: Windows built-in voice typing (Win+H, Bulgarian + English, Win+Space to switch). Dictated text may lack punctuation; read intent, not exact wording.
- Image generation: skipped for now (no free option; kie.ai is optional per the course).

## Rules for Claude
- Ask before installing anything or signing in. Never spend money: free tiers only.
- Never commit keys or tokens. Check `git status` before every commit.
- Matt Pocock's skills workflow: ask one question at a time (grill) → write the spec (to-spec) → split into tasks (to-tickets) → build (implement).
- When I mention something I want remembered, add it to `Meta-brain/`.

## Placeholders (details to come)
- implement-spec workflow: Matt Pocock's `/implement-spec` skill (installed globally) — builds what `/to-spec` + `/to-tickets` produced. Course-specific details: TODO
- Ник's system: TODO
- Sandcastle: TODO
- JEV (judge that runs on OpenRouter): TODO
- Notes from the 5-minute video: TODO
