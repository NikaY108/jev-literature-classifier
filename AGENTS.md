# AGENTS.md

## Project goal

Build a local-first literature classification workbench. Developers upload real
PDFs through an HTML interface, review and correct extracted metadata, define or
generate a taxonomy, classify papers with Jev, inspect the full category
probability distribution, review uncertain results, and export the outcome.
Zotero is an optional output connector and must not be required by the core app.

## Product constraints

- Build and validate the HTML upload workflow before adding Zotero integration.
- Jev performs bounded classification against an approved taxonomy.
- A generative LLM is used only for taxonomy generation.
- The generative-model connector defaults to SiliconFlow but accepts services
  compatible with OpenAI Chat Completions, Bearer authentication, and JSON output.
- Missing generative-model credentials disable candidate generation only. Manual
  taxonomy creation and Jev classification must remain available.
- After model settings are saved, verify the Jev key and selected model through
  the TypeSafe models endpoint. Never present a non-empty key as a verified connection.
- Papers that do not fit the approved taxonomy are marked unclassified. Do not
  create new categories or trigger targeted reclassification from review results.
- Do not add representative-paper or representative-sample features.
- Do not add baseline-model comparisons until the product workflow is complete.
- Do not manufacture a literature evaluation dataset. Small technical fixtures
  are allowed only for automated tests.
- Never write to Zotero without a preview and explicit user confirmation.
- Zotero import operates on one selected classification run. Reuse an unambiguous
  existing item or create a generic document item and import its PDF attachment.
- Zotero import lets users independently select classification tags, collection
  directories, or both. At least one representation is required.
- Store Zotero item associations locally for idempotent retries. Never persist a
  Zotero local authorization key or forward local Zotero data elsewhere.
- Zotero tags use `文献分类/<分类体系名称>/<最终类别>`. Deferred, failed, and
  unclassified results use `文献分类/<分类体系名称>/未分类`. Replace tags only
  inside the current taxonomy path and preserve all other tags.
- Zotero collections use `文献分类/<分类体系名称>/<最终类别>` as a three-level
  hierarchy. Move items only between direct category collections of the current
  taxonomy and preserve every unrelated user collection.
- Keep raw PDFs, extracted text, databases, and API keys out of Git.
- Model settings are single-user local configuration stored only in the project
  `.env`. API responses may expose configured/not-configured flags but never keys.
- Require metadata confirmation only for parsing failures or quality problems
  that can materially affect classification; ordinary missing keywords are
  informational and must not block the workflow.
- Treat the user's taxonomy objective as the fixed classification dimension;
  corpus terms may refine category boundaries but must not replace that dimension.
- Never mutate a taxonomy version used by classification runs. Editing creates a
  new active version and preserves earlier versions for historical results.
- Deleting a taxonomy requires explicit confirmation and permanently removes its
  entire version family, categories, classification runs, and results. Never delete
  a taxonomy or result while its classification run is queued or running.
- Deleting one classification result also requires explicit confirmation. Recompute
  its run totals afterward and remove the run when it has no results left.
- Deleting a classification run requires explicit confirmation and permanently
  removes every result in that run while preserving its taxonomy version.
- Category codes are internal stable identifiers. Never require users to enter
  or interpret them; generate missing codes from category names or row order.

## Technology

- Python 3.12
- FastAPI and Pydantic
- SQLAlchemy with SQLite
- pypdf for initial PDF text extraction
- TypeSafe Python SDK for Jev
- Native HTML, CSS, and JavaScript served by FastAPI
- pytest for backend tests

## Directory map

- `app/main.py`: FastAPI application and static-file mounting.
- `app/api/`: HTTP routes.
- `app/core/`: configuration, database, and shared helpers.
- `app/models/`: SQLAlchemy persistence models.
- `app/schemas/`: request and response schemas.
- `app/services/`: parsing, classification, taxonomy generation, jobs, exports.
- `app/services/zotero.py`: Zotero Local API detection, matching, item writes,
  and PDF attachment upload.
- `frontend/`: HTML, CSS, browser JavaScript, and any future frontend-local dependencies.
- `docs/images/`: sanitized public documentation images only; never include private
  literature metadata, local paths, or model credentials.
- `start_server.py`: VS Code-friendly local server entry point.
- `tests/`: automated engineering tests with mocked external model calls.
- `data/`: runtime data only; ignored by Git.
- `TODO.md`: current status and next action. Read it before every task.
- `user-guide.md`: user-facing instructions. Keep it aligned with shipped UI.

## Working rules

1. Read `AGENTS.md` and `TODO.md` before editing.
2. Inspect `git status` before and after a task when the directory is a Git repo.
3. Update `TODO.md` when starting, finishing, reprioritizing, or blocking work.
4. Update `user-guide.md` in the same change as user-visible behavior.
5. Update this file when architecture, commands, or constraints change.
6. Use `apply_patch` for manual file edits.
7. Keep model providers behind service interfaces.
8. Validate all model output with Pydantic before persisting it.
9. Record document hash, taxonomy version, model version, and input level for
   every classification so a run can be reproduced.
10. Use concise comments only for non-obvious behavior.
11. Do not create or run automated tests unless the user explicitly asks. Give
    the user concise manual verification steps instead.

## Code conventions

- Use type hints for public functions and service boundaries.
- Prefer small modules with explicit dependencies over global mutable state.
- API responses use stable snake_case field names.
- Store timestamps in UTC.
- Use semantic HTML and accessible labels, keyboard states, and dialogs.
- Report user-initiated operation outcomes through the shared in-page notification
  component. Use success, error, warning, or information states as appropriate;
  keep destructive confirmation dialogs separate from result notifications.
- UI colors come from CSS variables. Use cold-white content surfaces, graphite
  navigation, and cyan interaction accents. Green is reserved for success states.
- Keep the interface aligned with a modern research workbench: sans-serif titles,
  moderate information density, fine dividers, and consistent small-radius controls.
  Avoid decorative floating sections and preserve existing workflows and wording
  during visual-only changes. Native CSS motion must honor reduced-motion settings.
- Organize documents by attention state and local upload date instead of showing
  the full library as one permanently expanded list.
- Browse classification results through taxonomy-version and run selectors plus
  category tabs. Show one category table at a time, with items needing review
  and lower-confidence items first.
- Do not expose secrets or full document text in logs.
- Keep public screenshots and examples free of private paper titles, filenames,
  local paths, API keys, and unlicensed document content.
- Never persist API keys in browser storage or return them from an API response.
- Deleting local results removes local Zotero association records but never
  deletes items, attachments, or tags already written to Zotero.

## Common commands

```powershell
F:\Anaconda\envs\paper_manage\python.exe -m pip install -r requirements.txt
F:\Anaconda\envs\paper_manage\python.exe start_server.py
F:\Anaconda\envs\paper_manage\python.exe -m uvicorn app.main:app --reload --port 8000
F:\Anaconda\envs\paper_manage\python.exe -m pytest
F:\Anaconda\envs\paper_manage\python.exe -m ruff check .
```

Open `http://127.0.0.1:8000` after starting the server.

## Verification ownership

- The user performs functional and model-quality testing manually.
- Agents do not create or run tests unless the user explicitly requests it.
- After a user-visible change, document the shortest manual verification path.
- Never call paid model APIs without explicit user direction.

## Files and data that must not be committed

- `.env`
- `data/`
- uploaded PDFs or extracted full text
- SQLite databases and journal files
- API keys, access tokens, or Zotero credentials
- local virtual environments and caches

## Dependency placement

- Install backend dependencies only into the existing `paper_manage` Conda environment.
- Do not create a project-level Python virtual environment.
- The current frontend is dependency-free. If frontend packages are introduced,
  install them under `frontend/` and keep their manifest and lockfile there.
