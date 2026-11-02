# Standards

- Python 3.11 or later. Source lives in `src/doclo/`, tests in `tests/`.
- Every change has a test that fails without it.
- Prefer the standard library; add a dependency only when the piece needs it, and name it in the pull request.
- Names say what a thing is or does. Comments explain why, not what.
- Do not change `LICENSE`, `NOTICE` or the package metadata unless the piece says so.
- Never commit secrets, credentials or generated PDFs.
