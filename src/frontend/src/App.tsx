import { FormEvent, useEffect, useState } from "react";
import { Collection, collections, login, me, setToken, getToken } from "./api/client";
import { Account, isAdmin } from "./auth/session";
import { AdminPage } from "./administration/AdminPage";
import { CollectionsPage } from "./collections/CollectionsPage";
import { Preview } from "./document-preview/Preview";
import { Browser } from "./file-manager/Browser";
import { JobsPage } from "./ingestion/JobsPage";
import { SearchPage } from "./search/SearchPage";

type View = "global" | "local" | "collections" | "search" | "jobs" | "admin";

export function App() {
  const [account, setAccount] = useState<Account | null>(null);
  const [view, setView] = useState<View>("global");
  const [rows, setRows] = useState<Collection[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function refresh() {
    if (!getToken()) return;
    const profile = await me();
    setAccount(profile);
    setRows((await collections()).collections);
  }

  useEffect(() => {
    if (getToken()) void refresh().catch(() => setToken(""));
  }, []);

  async function submitLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      const body = await login(String(form.get("username")), String(form.get("password")));
      setToken(body.access_token);
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Login failed.");
    }
  }

  if (!account) {
    return (
      <main className="login panel">
        <h1>RAG Store</h1>
        <form onSubmit={(event) => void submitLogin(event)}>
          <label>Username<br /><input name="username" autoComplete="username" /></label>
          <label>Password<br /><input name="password" type="password" autoComplete="current-password" /></label>
          <button type="submit">Sign in</button>
        </form>
        {error && <p className="error">{error}</p>}
      </main>
    );
  }

  const admin = isAdmin(account);
  return (
    <div className="app">
      <aside className="sidebar">
        <h1>RAG Store</h1>
        <p>{account.username}</p>
        <h2>Knowledge</h2>
        <button className={view === "global" ? "active" : ""} onClick={() => { setView("global"); setOpenId(null); }}>GLOBAL knowledge</button>
        <button className={view === "local" ? "active" : ""} onClick={() => { setView("local"); setOpenId(null); }}>My LOCAL knowledge</button>
        <button className={view === "collections" ? "active" : ""} onClick={() => setView("collections")}>Collections</button>
        <button className={view === "search" ? "active" : ""} onClick={() => setView("search")}>Knowledge search</button>
        <h2>Ingestion</h2>
        <button className={view === "jobs" ? "active" : ""} onClick={() => setView("jobs")}>Jobs</button>
        {admin && <h2>Administration</h2>}
        {admin && <button className={view === "admin" ? "active" : ""} onClick={() => setView("admin")}>System status</button>}
        <button onClick={() => { setToken(""); setAccount(null); }}>Sign out</button>
        <p className="muted">Local storage {account.quota.used_bytes} / {account.quota.max_bytes} bytes</p>
      </aside>
      <main className="main">
        {openId && <Preview documentId={openId} onClose={() => setOpenId(null)} />}
        {!openId && view === "global" && <Browser scope="global" collections={rows} canWrite={admin} onOpen={setOpenId} />}
        {!openId && view === "local" && <Browser scope="local" collections={rows} canWrite={account.role !== "service"} onOpen={setOpenId} />}
        {!openId && view === "collections" && <CollectionsPage collections={rows} scope={admin ? "global" : "local"} canWrite={account.role !== "service"} onCreated={() => void refresh()} />}
        {!openId && view === "search" && <SearchPage onOpen={setOpenId} />}
        {!openId && view === "jobs" && <JobsPage />}
        {!openId && view === "admin" && admin && <AdminPage />}
      </main>
    </div>
  );
}
