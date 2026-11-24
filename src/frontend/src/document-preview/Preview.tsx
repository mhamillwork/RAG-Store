import { useEffect, useState } from "react";
import { documentDetail, documentTables, documentText, DocumentDetail, getToken, TablePreview } from "../api/client";

export function Preview({ documentId, onClose }: { documentId: string; onClose: () => void }) {
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [text, setText] = useState("");
  const [tables, setTables] = useState<TablePreview[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        setDetail(await documentDetail(documentId));
        setTables((await documentTables(documentId)).tables);
        try {
          setText(await documentText(documentId));
        } catch {
          setText("");
        }
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "The document could not be loaded.");
      }
    })();
  }, [documentId]);

  return (
    <section className="panel">
      <button onClick={onClose}>Back</button>
      {error && <p className="error">{error}</p>}
      {detail && (
        <>
          <h2>{detail.filename}</h2>
          <p>{detail.scope} · {detail.relative_path} · {detail.lifecycle_state} · {detail.ingestion_state || "no job"} · chunks {detail.chunk_count}</p>
          <p className="muted">Parser {String(detail.version?.parser || "")}. Checksum {String(detail.version?.checksum || "")}. Conversion {String(detail.conversion?.status || "not stored")}. OCR {String((detail.conversion?.ocr as Record<string, unknown> | undefined)?.engine || "not recorded")}.</p>
          <p>
            <a href={`/api/v1/documents/${detail.id}/download`} onClick={(event) => { event.preventDefault(); void download(detail.id, detail.filename); }}>Download original</a>
            {" · "}
            <a href={`/api/v1/documents/${detail.id}/markdown`} onClick={(event) => { event.preventDefault(); void download(detail.id, `${detail.filename}.md`, "markdown"); }}>Markdown</a>
            {" · "}
            <a href={`/api/v1/documents/${detail.id}/docling?include_content=true`} onClick={(event) => { event.preventDefault(); void download(detail.id, `${detail.filename}.json`, "docling?include_content=true"); }}>Docling JSON</a>
          </p>
          {text && <pre>{text.slice(0, 20000)}</pre>}
          {tables.map((table) => (
            <div key={table.id}>
              <h3>{table.caption || `Table ${table.id}`}</h3>
              <table>
                <thead><tr>{(table.content.headers || []).map((header) => <th key={header}>{header}</th>)}</tr></thead>
                <tbody>{(table.content.rows || []).map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody>
              </table>
            </div>
          ))}
        </>
      )}
    </section>
  );
}

async function download(id: string, filename: string, kind = "download") {
  const response = await fetch(`/api/v1/documents/${id}/${kind}`, { headers: { Authorization: `Bearer ${getToken()}` } });
  if (!response.ok) return;
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
