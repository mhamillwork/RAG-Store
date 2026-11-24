# LOCAL knowledge

Each user has an immutable `storage_key` of the form `user-` plus 12 hex characters and a default LOCAL collection named `documents`. Another user, including an administrator using the normal API, receives 404 rather than 403 for that data.

Deduplication matches checksum and path inside one collection. It does not say whether some other user already stored the same bytes.
