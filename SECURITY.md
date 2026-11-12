# Security policy

## Keep credentials out of Git

Use `.env.example` as the template and keep the real `.env` file local. Never commit:

- API keys for University of Macau GenAI, DeepSeek, OpenAI, or other providers.
- UMPASS usernames or passwords.
- JWT bearer tokens, `token` cookie values, browser cookies, or browser profile directories.
- Uploaded lecture files, handwritten images, SQLite databases, logs, or generated exports that may contain private course material.

The repository ignores common runtime locations, but check `git status` and review the final diff before every push.

## If a credential is exposed

1. Revoke or rotate the credential immediately at its provider.
2. Remove it from every published commit and invalidate the old token.
3. Open a private security report with the repository owner.

Do not include the secret in the report. Describe its type, location, and approximate exposure time instead.
