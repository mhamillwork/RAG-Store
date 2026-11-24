import { useEffect, useState } from "react";
import { Job, jobs, retryJob } from "../api/client";

const MEASURABLE = ["pages_processed", "page_count", "ocr_pages_processed", "chunks_generated", "chunks_embedded"];

export function JobsPage() {
  const [rows, setRows] = useState<Job[]>([]);
  const [error, setError] = useState("");

  async function reload() {
    try {
      setRows((await jobs()).jobs);
      setError("");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Jobs could not be loaded.");
    }
  }

  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => void reload(), 5000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <section className="panel">
      <div className="toolbar"><button onClick={() => void reload()}>Refresh</button></div>
      {error && <p className="error">{error}</p>}
      <table>
        <thead><tr><th>State</th><th>Type</th><th>Progress</th><th>Error</th><th></th></tr></thead>
        <tbody>
          {rows.map((job) => {
            const measured = MEASURABLE.filter((key) => job.progress?.[key] != null).map((key) => `${key}: ${String(job.progress[key])}`);
            return (
              <tr key={job.id}>
                <td>{job.state}</td>
                <td>{job.job_type}</td>
                <td>{measured.length ? measured.join(", ") : "Progress is indeterminate for this stage."}</td>
                <td>{job.last_error}</td>
                <td>{job.state === "failed" && <button onClick={() => void retryJob(job.id).then(reload)}>Retry</button>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
