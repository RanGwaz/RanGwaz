---
name: frontend-code-only
description: Keep frontend implementation work code-only in this repository. Use when editing this repo's frontend UI or styles; do not perform screenshot, browser, or visual QA unless the user explicitly asks for it.
---

# Frontend Code Only

For this repository, frontend changes should stop after code edits plus ordinary code-level checks.

Do:

- Implement the requested frontend behavior or styling directly.
- Run lightweight build, typecheck, lint, or unit tests when practical.
- Report what changed and which code-level checks passed or failed.

Do not:

- Start a browser just to inspect UI.
- Capture screenshots.
- Run visual QA or responsive screenshot passes.
- Block completion on rendered inspection.

If the user explicitly asks for screenshots, browser testing, or visual QA in a later turn, follow that newer request.
