import { useEffect, useState } from "react";
import { adminUsers, audit, systemStatus } from "../api/client";

export function AdminPage() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [users, setUsers] = useState<Array<Record<string, string>>>([]);
  const [events, setEvents] = useState<Array<Record<string, string>>>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        setStatus(await systemStatus() as Record<string, unknown>);
        setUsers((await adminUsers()).users);
        setEvents((await audit()).events);
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "Administration data is unavailable.");
      }
    })();
  }, []);

  return (
    <section className="panel">
      <h2>Administration</h2>
      {error && <p className="error">{error}</p>}
      <pre>{JSON.stringify(status, null, 2)}</pre>
      <h3>Users</h3>
      <ul>{users.map((user) => <li key={user.id}>{user.username} · {user.role} · {user.is_active ? "active" : "disabled"}</li>)}</ul>
      <h3>Audit</h3>
      <ul>{events.slice(0, 50).map((event) => <li key={event.id}>{event.created_at} · {event.action} · {event.target_type}</li>)}</ul>
    </section>
  );
}
