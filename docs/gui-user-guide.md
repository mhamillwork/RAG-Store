# GUI

Open the GUI host. Sign in with a local account. GLOBAL and LOCAL are separate sidebar entries. The file view lists folders and documents from `GET /api/v1/collections/{id}/listing`. Upload, directory upload, and drag-and-drop call `POST /api/v1/documents/upload`.

Search calls `POST /api/v1/search`. Degraded responses show the reasons returned by the API. Job progress shows measured fields when the API sends them and otherwise says the stage is indeterminate.

Delete asks for confirmation. The GUI delete is a logical delete: the document leaves search results and the original file remains unless a physical delete is requested on the API.
