# Pindou architecture memory

## Product direction

- The primary product surface is a browser workspace for pin-bead creators.
- The intended workflow is upload, rectangular selection, GrabCut extraction, optional pixel-art treatment, editable outline coloring, palette quantization, then PNG/JSON/CSV export.
- Keep the existing CLI operational. Web features should call the same segmentation, quantization, palette and rendering modules rather than duplicating them.

## Runtime architecture

- `ARCHITECTURE.md` is the binding architecture contract and `AGENTS.md` requires future agents to read it before changes.
- `frontend/` is an independently served build-free HTML/CSS/JavaScript application. Nginx serves assets and proxies only `/api` to FastAPI.
- `backend.main` is the API process. HTTP concerns live in `backend/api`, business and processing logic in `backend/services`, dependencies/middleware/serializers in dedicated modules.
- `backend.worker` is a separate process. Docker uses the PostgreSQL-backed `processing_jobs` queue; processing endpoints return 202 and the frontend polls `/api/jobs/{id}`. Local tests may use eager mode.
- `pindou.web` is only a compatibility import for `backend.main`. It must not gain new routes.
- `pindou.storage.Store` uses SQLAlchemy. It falls back to SQLite for local development and uses `PINDOU_DATABASE_URL` for PostgreSQL in Docker. Runtime image data lives under `PINDOU_DATA_DIR`, defaulting to `data/`.
- Uploaded and generated images are stored outside the public static tree. Authenticated asset routes enforce project ownership.
- Passwords use PBKDF2-SHA256 with random salts. Login uses a signed HttpOnly, SameSite=Lax cookie. Production requires a stable `PINDOU_SESSION_SECRET`, HTTPS and `PINDOU_COOKIE_SECURE=1`.
- Deployment uses separate Nginx frontend, non-root FastAPI API, non-root Worker and PostgreSQL 16 containers. Database and image data are separate named volumes and must be backed up together.
- Database domains are users/roles/status, image project metadata, append-style activity audit records, processing jobs with structured input/output, and user-to-admin messages.
- Administrators are bootstrapped from environment variables and use a dedicated `/admin` UI. Normal project assets enforce ownership; administrator previews use separate role-protected routes.
- Project and account lifecycle controls now include project rename/duplicate/delete, task cancel with worker heartbeats and bounded retry, password change with session invalidation, JSON account export and password-confirmed account deletion. Per-user quotas and process-local request limits are configured through `PINDOU_*` environment variables.
- Audit and job logging deliberately exclude passwords, session cookies, API keys and image Base64. Processing parameters and prompts are visible to administrators, which requires an explicit privacy policy in a public deployment.

## Image processing decisions

- User selection coordinates are normalized in the browser and converted to source-image pixels on the server.
- `make_subject_mask_from_box` initializes OpenCV GrabCut from the rectangular selection and retains the largest component.
- Manual mask refinement applies normalized keep/remove brush points to the saved full-resolution mask through the `refine_mask` worker operation and atomically rebuilds the cutout.
- `local_pixel_art` is the always-available offline fallback. It quantizes colors, applies a one-pixel outline at low resolution and scales with nearest-neighbor sampling.
- Optional remote generation uses a deliberately small gateway contract configured by `PINDOU_MODEL_API_URL`, `PINDOU_MODEL_API_KEY` and `PINDOU_MODEL_NAME`. Secrets never enter frontend code.
- Pattern generation prefers a saved painted grid, then the styled image, then the transparent cutout, then the original plus saved mask.
- Coloring grids persist shape (`mask`) separately from paint (`cells`). Erasing a color never destroys the extracted outline. `coloring.json` is the editable source and `painted.png` is its transparent rendered asset.
- Final pattern generation prefers a saved coloring grid and maps every custom hex color to the nearest allowed bead code without resampling the grid geometry.
- AI coloring sends a rendered line-art grid through the existing image-model gateway, samples only returned colors, and reapplies the saved mask. Shape changes from a model response are therefore discarded.
- Random coloring is implemented locally in browser JavaScript as coherent region coloring and never calls an external model.
- A project may restrict matching to a user-entered inventory of bead codes. Empty inventory means all 221 built-in colors; invalid codes fail before generation.

## UI decisions

- Visual direction: compact desktop image editor, cold neutral surfaces, one berry accent, consistent 8-12 px radius scale.
- The desktop layout has project history, central canvas and parameter inspector. Below 680 px it becomes a single column with a fixed workflow bar.
- Light and dark tokens are both supported. Motion is limited to feedback and loading states and honors reduced-motion preferences.
- The coloring canvas uses pointer events and offers brush, flood fill, eraser, eyedropper, a native color picker, all 221 palette swatches, undo/redo, clear, algorithmic random color and optional AI color controls.
- The main workspace exposes mask refinement controls and active-job cancellation; the account dialog exposes password rotation, JSON export and account deletion.
- The profile dialog includes aggregate usage and user messages. The administrator console covers users, projects, activity logs, processing job input/output and message resolution.

## Verification

- `verification/smoke_test.py` covers the original CLI pipeline.
- `verification/web_smoke_test.py` covers registration, upload, extraction, local stylization, coloring-grid creation and persistence, painted-source pattern generation, protected downloads, profile/usage/messages, cross-account isolation, administrator authorization, audit/job inspection, account disabling and logout using an in-process ASGI transport.
