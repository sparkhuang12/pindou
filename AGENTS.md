# Project instructions

Before changing this repository, read and follow `ARCHITECTURE.md` in full.

- Preserve the frontend/API/worker/core boundaries defined there.
- Long-running image or model work must run through `processing_jobs` and the independent worker.
- Update `ARCHITECTURE.md`, deployment documentation, and verification whenever a public contract or boundary changes.
- Run `python3 verification/architecture_check.py` before handing off changes.
