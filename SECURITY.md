# Security and private data

This is a local single-user application. Bind to 127.0.0.1, open the local interface to establish an HttpOnly session, and keep the frontend/backend on the same hostname. Cross-site origins and unexpected Host headers are rejected. Databases, logs, backups and browser profiles are never mounted as public files.

The existing credential configuration, provider router and campus login implementation are preserved by the owner's explicit request. The local Settings API still supplies existing credential fields to the authenticated Settings interface. Keep the backend off public networks. Existing provider TLS behavior is not changed by this release.

Never publish `.env`, API keys, UMPASS accounts/passwords, JWT bearer/cookie tokens, browser profiles, uploaded documents, handwritten images, SQLite databases or backups. Backups contain private study data and must also stay local.

A release must pass both exact-value comparisons against local credential values and generic key/JWT pattern scans. Review the publication allowlist as well as .gitignore; ignored paths alone are not a security boundary.

If a secret is exposed, revoke it at the provider and remove it from published history. Do not include the value in a public issue.
