# Fubuki Prompt Library (Repo Source of Truth)

This folder is the **persistent memory** for Fubuki’s learned frameworks, personas, and operating layers.

If you want Fubuki to reliably behave the same way across environments (local, desktop bundle, server), put the knowledge here.

## Files

- `askfubuki_swe_knowledge_base.md`
  - SWE screening / evaluation heuristics and knowledge base.

- `ava_labs_technical_pm_framework.md`
  - Deep interview framework + org learning for Ava Labs Director of Technical PM role.

- `clawd_integration_handoff.md`
  - Integration handoff notes / constraints / operating plan for Clawdbot integration.

- `fubuki_beta_philosophy_layer.md`
  - High-level philosophy / stance / product principles.

- `fubuki_hr_behavioral_science_addendum.md`
  - Behavioral science addendum for HR/support scenarios.

- `fubuki_hr_helpline_persona.md`
  - HR helpline persona layer.

## Static mirror

The desktop/web UI may need access to these prompts.
A mirror exists at:
- `backend/app/static/prompts/`

If you add/edit a prompt in `backend/app/prompts/`, mirror it into `backend/app/static/prompts/` (or update the build/bundling logic to copy them automatically).
