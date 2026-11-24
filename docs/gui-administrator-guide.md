# Administration GUI

The system-status view is rendered only when `/api/v1/users/me` reports `role=admin`. It loads `/api/v1/admin/system-status`, the user list, and the audit log. Counts follow administrator visibility and omit other users' LOCAL documents.

Embedding and reranking status report whether a URL and model are configured. They do not invent a healthy probe of vLLM.
