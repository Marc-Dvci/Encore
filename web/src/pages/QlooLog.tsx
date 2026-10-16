import { ShieldCheck } from "lucide-react";
import { ErrorBox, Loading, Section, useFetch } from "../ui";

interface Log {
  rows: { id: number; at: number; purpose: string; path: string; params: [string, string][]; status: number; ms: number; cached: number; results: number | null }[];
  total: number;
  cached: number;
  paths: { path: string; n: number }[];
}

export default function QlooLog() {
  const { data, error, reload, loading } = useFetch<Log>("/api/qloo/log?limit=200");
  return (
    <div className="stack lg">
      <div className="stack" style={{ gap: 6 }}>
        <span className="eyebrow">What Qloo saw</span>
        <h1>Every request Encore sent to Qloo</h1>
        <p className="ink2" style={{ maxWidth: 820 }}>
          Qloo receives entity IDs, a range of years, a hometown, a genre and an age bracket. Names, rooms, care notes and
          reactions stay in Encore. The client enforces it with an allow-list: free text can only be a favourite as the
          family typed it, a town or a genre word, and any request carrying a resident’s or carer’s name is refused before
          it leaves.
        </p>
      </div>
      <div className="notice row">
        <ShieldCheck size={20} />
        <span className="grow small">
          The API key is sent in a header from the server and never reaches the browser. Answers are cached privately on the
          server, as Qloo’s hackathon terms allow, and never committed to the public repository.
        </span>
        <button className="btn sm" onClick={reload} disabled={loading}>
          Refresh
        </button>
      </div>
      {error && <ErrorBox error={error} retry={reload} />}
      {!data && !error && <Loading />}
      {data && (
        <>
          <div className="kpis">
            <div className="kpi">
              <div className="v">{data.total.toLocaleString()}</div>
              <div className="small muted">Requests logged</div>
            </div>
            <div className="kpi">
              <div className="v">{data.total ? Math.round((data.cached / data.total) * 100) : 0}%</div>
              <div className="small muted">Answered from the private cache</div>
            </div>
            {data.paths.slice(0, 4).map((p) => (
              <div key={p.path} className="kpi">
                <div className="v">{p.n.toLocaleString()}</div>
                <div className="small muted mono">{p.path}</div>
              </div>
            ))}
          </div>
          <Section title="Most recent requests">
            <div className="table-wrap">
              <table className="plain">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Why</th>
                    <th>Request</th>
                    <th>Results</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.id}>
                      <td className="small muted" style={{ whiteSpace: "nowrap" }}>
                        {new Date(r.at * 1000).toLocaleTimeString()}
                        <div>{r.cached ? "cache" : `${r.ms} ms`}</div>
                      </td>
                      <td className="small">{r.purpose}</td>
                      <td>
                        <div className="mono">GET {r.path}</div>
                        <div>
                          {r.params.map(([k, v]) => (
                            <span key={k} className="param mono tiny">
                              {k}={v.length > 70 ? v.slice(0, 70) + "…" : v}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="small">{r.status === 200 ? r.results ?? "–" : <span className="chip warn">{r.status}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        </>
      )}
    </div>
  );
}
