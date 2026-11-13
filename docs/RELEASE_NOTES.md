# Reliability and study workflow release

This release fixes broken wrong-bank scoring calls and frontend image/submission endpoints, adds exact section validation, source-page links, note history, preserved practice variants, review scheduling, recoverable exam drafts, backend timing, atomic/repeat-safe submission, cancelable generation, offline PDF downloads, and private study backup/restore.

The owner's existing `.env`, API/provider configuration, GenAI integration, UMPASS login code and Settings panel are preserved. Credential storage/routing migrations are excluded from this release. No private study material or credentials belong in the public tree.

Database changes are additive. An existing database receives a private recovery snapshot before new columns are added. Grading interruptions and generation restarts are recoverable without changing previous mastery records.

Validation: isolated regression tests, actual PDF rendering, production frontend build, legacy-database migration on a private copy, browser workflow checks and exact credential/pattern scans of the public upload set. No live paid model calls are part of the automated regression suite.
