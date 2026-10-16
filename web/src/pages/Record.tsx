import { useParams, Link } from "react-router-dom";
import { Printer } from "lucide-react";
import { ErrorBox, Loading, useFetch } from "../ui";

interface RecordData {
  person: { id: string; first_name: string; last_initial: string; birth_year: number; age: number; city: string; country: string; languages: string; room: string; family_note: string | null };
  home: { name: string; town: string; coordinator: string };
  favourites: { id: number; label: string; kind: string; entity_name: string | null; status: string; source: string; added_at: string }[];
  avoid: { id: number; label: string; source: string; added_at: string }[];
  house_rules: [string, string][];
  reactions: { id: number; at: string; entity_name: string; entity_type: string; reaction: string; carer: string | null; note: string | null }[];
  sessions: { id: string; at: string; carer: string; items: string[] }[];
}

const KIND: Record<string, string> = { artist: "Music", movie: "Film", tv_show: "Television", book: "Books" };
const REACTION: Record<string, string> = { lit_up: "Lit up", sang_along: "Sang or moved along", no_response: "No response", upset: "Seemed upset" };

export default function Record() {
  const { id } = useParams();
  const { data, error, reload } = useFetch<RecordData>(`/api/record/${id}`, [id]);
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (!data) return <Loading label="Preparing the record…" />;
  const p = data.person;
  return (
    <div className="stack lg" style={{ maxWidth: 900 }}>
      <div className="row between noprint">
        <Link to={`/residents/${p.id}`}>← {p.first_name}’s profile</Link>
        <button className="btn" onClick={() => window.print()}>
          <Printer size={16} /> Print
        </button>
      </div>
      <div className="stack" style={{ gap: 4 }}>
        <span className="eyebrow">Activities programme · individual record</span>
        <h1>
          {p.first_name} {p.last_initial}.
        </h1>
        <p className="ink2">
          {data.home.name}, {data.home.town} · Room {p.room} · Born {p.birth_year} in {p.city}, {p.country} · Speaks {p.languages}
        </p>
        <p className="small muted">
          Supports the activities requirement for US nursing homes (42 CFR 483.24(c), survey tag F679): a programme
          built on the resident’s own interests and preferences, with a record of participation.
        </p>
      </div>

      <section className="card">
        <h3 style={{ marginBottom: 8 }}>Interests and preferences</h3>
        {p.family_note && <p style={{ marginBottom: 10 }}>{p.family_note}</p>}
        <table className="plain">
          <thead>
            <tr>
              <th>Interest</th>
              <th>Kind</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {data.favourites.map((f) => (
              <tr key={f.id}>
                <td>{f.entity_name ?? f.label}</td>
                <td>{KIND[f.kind] ?? f.kind}</td>
                <td>{f.source === "family" ? "Family" : `Session, ${f.added_at.slice(0, 10)}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h3 style={{ marginBottom: 8 }}>To avoid</h3>
        <ul style={{ margin: 0 }}>
          {data.avoid.map((a) => (
            <li key={a.id}>
              {a.label} <span className="muted small">({a.source}, {a.added_at.slice(0, 10)})</span>
            </li>
          ))}
          {data.house_rules.map(([, l]) => (
            <li key={l}>
              {l} <span className="muted small">(house rule)</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h3 style={{ marginBottom: 8 }}>Participation and response</h3>
        {data.reactions.length === 0 ? (
          <p className="muted">No sessions recorded yet.</p>
        ) : (
          <table className="plain">
            <thead>
              <tr>
                <th>Date</th>
                <th>Activity item</th>
                <th>Response</th>
                <th>Staff</th>
              </tr>
            </thead>
            <tbody>
              {data.reactions.map((r) => (
                <tr key={r.id}>
                  <td>{r.at.slice(0, 16)}</td>
                  <td>
                    {r.entity_name} <span className="muted small">({KIND[r.entity_type] ?? r.entity_type})</span>
                  </td>
                  <td>{REACTION[r.reaction] ?? r.reaction}</td>
                  <td>{r.carer ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h3 style={{ marginBottom: 8 }}>One-to-one sessions planned</h3>
        {data.sessions.length === 0 ? (
          <p className="muted">None yet.</p>
        ) : (
          <table className="plain">
            <tbody>
              {data.sessions.map((s) => (
                <tr key={s.id}>
                  <td>{s.at.slice(0, 16)}</td>
                  <td>with {s.carer}</td>
                  <td>{s.items.filter(Boolean).join(" · ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <p className="small muted">Prepared by Encore for {data.home.coordinator}, activities coordinator.</p>
    </div>
  );
}
