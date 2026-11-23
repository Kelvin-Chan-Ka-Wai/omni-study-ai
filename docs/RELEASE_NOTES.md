# Reliability and study workflow release

This release fixes broken wrong-bank scoring calls and frontend image/submission endpoints, adds exact section validation, source-page links, note history, preserved practice variants, review scheduling, recoverable exam drafts, backend timing, atomic/repeat-safe submission, cancelable generation, offline PDF downloads, and private study backup/restore.

The owner's existing `.env`, API/provider configuration, GenAI integration, UMPASS login code and Settings panel are preserved. Credential storage/routing migrations are excluded from this release. No private study material or credentials belong in the public tree.

Database changes are additive. An existing database receives a private recovery snapshot before new columns are added. Grading interruptions and generation restarts are recoverable without changing previous mastery records.

Validation: isolated regression tests, actual PDF rendering, production frontend build, legacy-database migration on a private copy, browser workflow checks and exact credential/pattern scans of the public upload set. No live paid model calls are part of the automated regression suite.

## Faster note and assessment generation

A nine-section finance chapter with a 56 MB textbook produced complete AI lessons with textbook citations in 17.1 seconds from the Generate button to rendered notes in a local Chromium test (DeepSeek fallback route). With a deliberately stalled provider, the same selection displayed results in 106.4 seconds: one previously saved note was retained and eight previously empty sections received labeled source reading guides. These are measured examples, not guarantees for every device or provider.

The quiz, mock test, midterm and final were checked with and without a question bank. Each paper was reopened and checked against its expected size and marks (8/25, 15/50, 29/100 and 29/100). Generation retains the full note prompts and validates papers before saving. No benchmark course files or model output are distributed.
