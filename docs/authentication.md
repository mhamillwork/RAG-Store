# Authentication

Local passwords are hashed with argon2. Access tokens are HS256 JWTs. Refresh tokens and API keys are stored as SHA-256 hashes. API keys start with `rag_`.

The first account can be created from `RAG_STORE_AUTH__BOOTSTRAP_ADMIN_USERNAME` and `RAG_STORE_AUTH__BOOTSTRAP_ADMIN_PASSWORD` when `user_count()` is zero. The insert uses an advisory lock.

OIDC settings are stored and not yet used for a redirect login. Failed logins write an audit event and do not reveal whether the username exists.
