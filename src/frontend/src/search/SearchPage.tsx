import { FormEvent, useState } from "react";
import { search, SearchResponse } from "../api/client";

export function SearchPage({ onOpen }: { onOpen: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("hybrid");
  const [scope, setScope] = useState("all");
  const [topK, setTopK] = useState(10);
  const [rerank, setRerank] = useState(false);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      setResult(await search({ query, mode, scope, top_k: topK, rerank }));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Search failed.");
    }
  }

  return (
    <section className="panel">
      <form className="toolbar" onSubmit={(event) => void submit(event)}>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search knowledge" />
        <select value={mode} onChange={(event) => setMode(event.target.value)}>
          <option value="hybrid">Hybrid</option>
          <option value="semantic">Semantic</option>
          <option value="keyword">Keyword</option>
        </select>
        <select value={scope} onChange={(event) => setScope(event.target.value)}>
          <option value="all">Global and local</option>
          <option value="global">Global only</option>
          <option value="local">Local only</option>
        </select>
        <input type="number" min={1} max={50} value={topK} onChange={(event) => setTopK(Number(event.target.value))} />
        <label><input type="checkbox" checked={rerank} onChange={(event) => setRerank(event.target.checked)} /> Rerank</label>
        <button type="submit">Search</button>
      </form>
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="hits">
          <p className="muted">Mode {result.mode}. {result.degraded ? `Degraded: ${result.degradation_reasons.join(", ")}` : "Full retrieval."} {result.rerank_applied ? "Reranking applied." : ""}</p>
          {result.hits.map((hit) => (
            <article key={String(hit.chunk_id)} className="card">
              <button onClick={() => onOpen(String(hit.document_id))}>{String(hit.filename)}</button>
              <p>{String(hit.excerpt || hit.content || "")}</p>
              <p className="muted">{String(hit.scope)} / {String(hit.collection)} / page {String(hit.page_number ?? "n/a")} / score {String(hit.score ?? "")} {hit.rerank_score != null ? `/ rerank ${String(hit.rerank_score)}` : ""}</p>
            </article>
          ))}
          {result.hits.length === 0 && <p>No matching chunks.</p>}
        </div>
      )}
    </section>
  );
}
