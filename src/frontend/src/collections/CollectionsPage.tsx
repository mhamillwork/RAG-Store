import { FormEvent, useState } from "react";
import { Collection, createCollection } from "../api/client";

export function CollectionsPage({ collections, scope, canWrite, onCreated }: { collections: Collection[]; scope: "global" | "local"; canWrite: boolean; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await createCollection(name, scope, description);
      setName("");
      setDescription("");
      onCreated();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "The collection was not created.");
    }
  }

  return (
    <section className="panel">
      <ul>{collections.filter((item) => item.scope === scope).map((item) => <li key={item.id}>{item.name} {item.is_default ? "(default)" : ""} — {item.description}</li>)}</ul>
      {canWrite && (
        <form className="toolbar" onSubmit={(event) => void submit(event)}>
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="collection-name" />
          <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Description" />
          <button type="submit">Create {scope} collection</button>
        </form>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  );
}
