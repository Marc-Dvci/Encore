import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { Candidate } from "../api";
import { Art, ErrorBox, Loading, PlayLinks, Section, fitColor, fitInk, useFetch, useTip } from "../ui";

interface FilmPick {
  pick: Candidate | null;
  candidates: Candidate[];
  excluded: { name: string; year: number; why: string }[];
  alternatives: { rule: string; name: string; year: number; min_pct: number; least_served: string; mean_pct: number }[];
  residents: string[];
  max_minutes: number;
  rule: string;
}
interface MusicHour {
  playlist: (Candidate & { song: string | null })[];
  coverage: { name: string; best: string; pct: number }[];
  residents: string[];
  rule: string;
}

export default function Lounge() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "music" ? "music" : "film";
  const [minutes, setMinutes] = useState(110);
  return (
    <div className="stack lg">
      <div className="row between">
        <div className="stack" style={{ gap: 6 }}>
          <span className="eyebrow">The lounge</span>
          <h1>Choosing for everyone in the room</h1>
          <p className="ink2" style={{ maxWidth: 780 }}>
            Each resident nominates films from their own youth. Qloo then ranks the whole shortlist for every resident’s
            tastes, and Encore picks the film whose least-served resident is served best.
          </p>
        </div>
        <div className="toggle" role="tablist">
          <button role="tab" aria-selected={tab === "film"} className={tab === "film" ? "on" : ""} onClick={() => setParams(params.get("add") ? { add: params.get("add")! } : {})}>
            Film
          </button>
          <button role="tab" aria-selected={tab === "music"} className={tab === "music" ? "on" : ""} onClick={() => setParams({ tab: "music", ...(params.get("add") ? { add: params.get("add")! } : {}) })}>
            Music hour
          </button>
        </div>
      </div>
      {params.get("add") && (
        <div className="notice small">
          Today’s lounge with the person you added in the room. Their fit is computed the same way as every resident’s.{" "}
          <Link to="/lounge">Back to the home’s lounge</Link>
        </div>
      )}
      {tab === "film" ? <FilmTab minutes={minutes} setMinutes={setMinutes} add={params.get("add")} /> : <MusicTab add={params.get("add")} />}
    </div>
  );
}

function FilmTab({ minutes, setMinutes, add }: { minutes: number; setMinutes: (n: number) => void; add: string | null }) {
  const extra = add ? `&add=${encodeURIComponent(add)}` : "";
  const { data, error, loading, reload } = useFetch<FilmPick>(`/api/lounge?domain=movie&max_minutes=${minutes}${extra}`, [minutes, add]);
  const { node, bind } = useTip();
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (!data) return <Loading label="Asking Qloo to rank the shortlist for each resident…" lines={6} />;
  const pick = data.pick;
  if (!pick) return <p>No film fits today’s constraints.</p>;
  const cols = data.candidates.slice(0, 8);
  const rows = pick.per_resident;
  const compare = [{ rule: "Encore: best for the least-served", name: pick.name, year: pick.year, min_pct: pick.min_pct, least_served: pick.least_served, mean_pct: pick.mean_pct }, ...data.alternatives];
  return (
    <div className="stack lg" style={{ opacity: loading ? 0.6 : 1 }}>
      <section className="card">
        <div className="hero">
          <Art src={pick.image} alt={pick.name} className="poster" />
          <div className="stack">
            <span className="eyebrow">Today’s pick for {data.residents.length} residents</span>
            <h2 style={{ fontSize: "2rem" }}>{pick.name}</h2>
            <div className="ink2">
              {pick.year} · {pick.duration} min · {pick.genres.join(", ")}
            </div>
            <div className="kpis">
              <div className="kpi">
                <div className="v">{pick.min_pct.toFixed(2)}</div>
                <div className="small muted">Fit for the least-served ({pick.least_served})</div>
              </div>
              <div className="kpi">
                <div className="v">{pick.mean_pct.toFixed(2)}</div>
                <div className="small muted">Average fit in the room</div>
              </div>
              <div className="kpi">
                <div className="v">{data.candidates.length}</div>
                <div className="small muted">Films on the shortlist</div>
              </div>
            </div>
            <p className="small">Nominated by {pick.nominated_by.join(", ")}.</p>
            <label className="small row tight noprint">
              Longest film the lounge can sit through
              <select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
                {[90, 100, 110, 120, 140].map((m) => (
                  <option key={m} value={m}>
                    {m} minutes
                  </option>
                ))}
              </select>
            </label>
            <PlayLinks film={`${pick.name} ${pick.year}`} />
          </div>
        </div>
      </section>

      <Section title="What each way of choosing costs the least-served resident">
        <div className="bars" role="table" aria-label="Fit for the least-served resident under each rule">
          {compare.map((c, i) => (
            <div key={c.rule} className={`bar-row ${i === 0 ? "pick" : ""}`} role="row">
              <div role="cell">
                <b>{c.rule}</b>
                <div className="small muted">
                  {c.name} ({c.year}) · least served: {c.least_served}
                </div>
              </div>
              <div className="bar-track" role="cell" aria-hidden>
                <div className="bar-fill" style={{ width: `${Math.max(2, c.min_pct * 100)}%` }} />
              </div>
              <div role="cell" style={{ fontVariantNumeric: "tabular-nums", fontWeight: 700 }}>
                {c.min_pct.toFixed(2)}
              </div>
            </div>
          ))}
        </div>
        <p className="small ink2" style={{ marginTop: 12 }}>
          {data.rule}.
        </p>
      </Section>

      <Section title="Fit for every resident" aside={<span className="small muted">Top {cols.length} of {data.candidates.length} films; darker is a better fit</span>}>
        <div className="matrix-wrap">
          <table className="matrix">
            <thead>
              <tr>
                <th />
                {cols.map((c, i) => (
                  <th key={c.entity_id} className={i === 0 ? "pick" : ""} scope="col">
                    {c.name} <span className="muted">({c.year})</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <th scope="row">{r.name}</th>
                  {cols.map((c, i) => {
                    const v = c.per_resident.find((x) => x.id === r.id)!;
                    return (
                      <td
                        key={c.entity_id}
                        className={`cell ${i === 0 ? "pick" : ""}`}
                        style={{ background: fitColor(v.pct), color: fitInk(v.pct) }}
                        tabIndex={0}
                        {...bind(
                          <>
                            <b>{r.name}</b> · {c.name}
                            <br />
                            Rank in {r.name}’s own Qloo list {v.rank_pct.toFixed(2)}
                            <br />
                            Era credit {v.era} → fit {v.pct.toFixed(2)}
                          </>,
                        )}
                      >
                        {v.pct.toFixed(2)}
                      </td>
                    );
                  })}
                </tr>
              ))}
              <tr className="summary">
                <th scope="row">Least served</th>
                {cols.map((c) => (
                  <td key={c.entity_id}>{c.min_pct.toFixed(2)}</td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
        {node}
        <p className="small ink2" style={{ marginTop: 10 }}>
          Fit = the film’s place in that resident’s own Qloo ranking of the shortlist (0 last, 1 first), with half credit
          when it falls outside their ages 10 to 30.
        </p>
      </Section>

      {data.excluded.length > 0 && (
        <Section title="Left off the shortlist">
          <details>
          <summary className="small">{dedupe(data.excluded).length} films left off: too long for the lounge, or carrying a tag on someone’s avoid list</summary>
          <ul className="small" style={{ margin: "8px 0 0" }}>
            {dedupe(data.excluded).map((x) => (
              <li key={x.name}>
                {x.name} ({x.year}): {x.why}
              </li>
            ))}
          </ul>
          </details>
        </Section>
      )}
    </div>
  );
}

function dedupe<T extends { name: string }>(xs: T[]) {
  const seen = new Set<string>();
  return xs.filter((x) => (seen.has(x.name) ? false : (seen.add(x.name), true)));
}

function MusicTab({ add }: { add: string | null }) {
  const { data, error, reload } = useFetch<MusicHour>(`/api/lounge?domain=artist${add ? `&add=${encodeURIComponent(add)}` : ""}`, [add]);
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (!data) return <Loading label="Building the playlist…" lines={6} />;
  return (
    <div className="grid2">
      <Section title="The playlist">
        <ol className="stack" style={{ gap: 10, margin: 0, paddingLeft: 24 }}>
          {data.playlist.map((s) => (
            <li key={s.entity_id}>
              <div className="row between">
                <div>
                  <b>{s.song ?? s.name}</b>
                  <div className="small muted">
                    {s.name} · for {s.nominated_by.join(", ")}
                  </div>
                </div>
                <PlayLinks artist={s.name} song={s.song} />
              </div>
            </li>
          ))}
        </ol>
      </Section>
      <Section title="A song for everyone">
        <p className="small ink2" style={{ marginBottom: 10 }}>
          {data.rule}.
        </p>
        <table className="plain">
          <thead>
            <tr>
              <th>Resident</th>
              <th>Best fit in the hour</th>
              <th>Fit</th>
            </tr>
          </thead>
          <tbody>
            {data.coverage.map((c) => (
              <tr key={c.name}>
                <td>{c.name}</td>
                <td>{c.best}</td>
                <td>
                  <span className="fitdot" style={{ background: fitColor(c.pct), color: fitInk(c.pct), width: 40, borderRadius: 8 }}>
                    {c.pct.toFixed(2)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  );
}
