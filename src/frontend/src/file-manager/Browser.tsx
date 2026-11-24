import { useEffect, useState } from "react";
import {
  Collection,
  createFolder,
  listing,
  moveDocument,
  reindex,
  removeDocument,
  renameDocument,
  reprocess,
  uploadFile,
} from "../api/client";

export function Browser({ scope, collections, canWrite, onOpen }: { scope: "global" | "local"; collections: Collection[]; canWrite: boolean; onOpen: (id: string) => void }) {
  const mine = collections.filter((item) => item.scope === scope);
  const [collectionId, setCollectionId] = useState(mine.find((item) => item.is_default)?.id || mine[0]?.id || "");
  const [path, setPath] = useState("");
  const [view, setView] = useState<"list" | "grid">("list");
  const [filter, setFilter] = useState("");
  const [data, setData] = useState<Awaited<ReturnType<typeof listing>> | null>(null);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  async function reload(nextPath = path, nextCollection = collectionId) {
    if (!nextCollection) return;
    setError("");
    try {
      setData(await listing(nextCollection, nextPath));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "The folder could not be listed.");
    }
  }

  useEffect(() => {
    if (!collectionId && mine[0]) setCollectionId(mine[0].id);
  }, [mine, collectionId]);

  useEffect(() => {
    if (!collectionId) return;
    let cancelled = false;
    listing(collectionId, path)
      .then((body) => { if (!cancelled) setData(body); })
      .catch((exc: unknown) => { if (!cancelled) setError(exc instanceof Error ? exc.message : "The folder could not be listed."); });
    return () => { cancelled = true; };
  }, [collectionId, path]);

  async function sendFiles(files: FileList | File[]) {
    if (!canWrite) {
      setError(scope === "global" ? "Only administrators can change global knowledge." : "You cannot change this folder.");
      return;
    }
    const collection = mine.find((item) => item.id === collectionId);
    if (!collection) return;
    for (const file of Array.from(files)) {
      const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath || "";
      const parent = relative.includes("/") ? relative.split("/").slice(0, -1).join("/") : path;
      await uploadFile(scope, collection.name, file, parent);
    }
    await reload();
  }

  const folders = data?.folders || [];
  const documents = (data?.documents || []).filter((item) => String(item.filename || "").toLowerCase().includes(filter.toLowerCase()));

  return (
    <section className={dragging ? "panel drop" : "panel"} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); void sendFiles(event.dataTransfer.files); }}>
      <div className="toolbar">
        <select value={collectionId} onChange={(event) => { setCollectionId(event.target.value); setPath(""); }}>
          {mine.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        <span className="crumbs">
          <button onClick={() => setPath("")}>{scope}</button>
          {path.split("/").filter(Boolean).map((part, index, parts) => (
            <button key={part} onClick={() => setPath(parts.slice(0, index + 1).join("/"))}>{part}</button>
          ))}
        </span>
        <input placeholder="Filter filename" value={filter} onChange={(event) => setFilter(event.target.value)} />
        <button onClick={() => setView(view === "list" ? "grid" : "list")}>{view === "list" ? "Grid" : "List"}</button>
        {canWrite && <button onClick={async () => { const name = window.prompt("Folder path"); if (name) { await createFolder(collectionId, path ? `${path}/${name}` : name); await reload(); } }}>New folder</button>}
        {canWrite && <label>Upload<input type="file" multiple hidden onChange={(event) => { if (event.target.files) void sendFiles(event.target.files); }} /></label>}
        {canWrite && <label>Upload directory<input type="file" multiple hidden ref={(node) => { if (node) node.setAttribute("webkitdirectory", ""); }} onChange={(event) => { if (event.target.files) void sendFiles(event.target.files); }} /></label>}
      </div>
      {error && <p className="error">{error}</p>}
      <div className={view}>
        {folders.map((folder) => (
          <button className={view === "list" ? "row" : "card"} key={folder.id} onClick={() => setPath(folder.path)}>
            <span className="icon folder" /> {folder.name}
          </button>
        ))}
        {documents.map((document) => (
          <article className={view === "list" ? "row" : "card"} key={String(document.id)}>
            <span className="icon" />
            <button onClick={() => onOpen(String(document.id))}>{String(document.filename)}</button>
            <span>{String(document.ingestion_state || document.lifecycle_state || "")}</span>
            <span>
              {canWrite && <button onClick={async () => { const name = window.prompt("New filename", String(document.filename)); if (name) { await renameDocument(String(document.id), name); await reload(); } }}>Rename</button>}
              {canWrite && <button onClick={() => setPendingDelete(String(document.id))}>Delete</button>}
              {canWrite && <button onClick={() => void reindex(String(document.id))}>Reindex</button>}
              {canWrite && <button onClick={() => void reprocess(String(document.id), "force")}>Force OCR</button>}
              {canWrite && <button onClick={async () => { const target = window.prompt("Collection id"); if (target) { await moveDocument(String(document.id), target); await reload(); } }}>Move</button>}
            </span>
          </article>
        ))}
      </div>
      {pendingDelete && (
        <div className="dialog">
          <div className="panel">
            <p>Delete this document from search results? The original file is retained unless an administrator chooses physical deletion through the API.</p>
            <button onClick={async () => { await removeDocument(pendingDelete); setPendingDelete(null); await reload(); }}>Delete</button>
            <button onClick={() => setPendingDelete(null)}>Cancel</button>
          </div>
        </div>
      )}
    </section>
  );
}
