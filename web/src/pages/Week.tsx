import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, Clapperboard, Flag, HeartHandshake, Music, Printer } from "lucide-react";
import { api, type Plan } from "../api";
import { Art, ErrorBox, Loading, Section, fitColor, fitInk, useFetch } from "../ui";

interface WeekFilm {
  entity_id: string;
  name: string;
  year: number;
  image: string | null;
  duration: number | null;
  genres: string[];
  min_pct: number;
  mean_pct: number;
  least_served: string;
}
interface OneToOne {
  day: string;
  resident: { id: string; first_name: string; city: string; flag: boolean };
  carer: { id: string; first_name: string };
  shared: string[];
  link: { tag: string; resident: string; carer: string } | null;
  n: number;
  rota_carer: string | null;
  week_fit: number | null;
}
interface WeekPlan {
  residents: number;
  carers: { id: string; first_name: string }[];
  films: {
    single: { name: string; year: number; floor: number; least_served: string } | null;
    pair: { films: WeekFilm[]; floor: number; mean: number; least_served: string; per_resident: { id: string; name: string; tuesday: number; thursday: number }[] } | null;
    separately: { films: string[]; floor: number; least_served: string } | null;
  };
  lounge: ({ day: string; kind: "film" } & WeekFilm | { day: string; kind: "music"; name: string; artists: string[]; covered: number; of: number })[];
  one_to_ones: OneToOne[];
  matrix: { resident: string; id: string; carers: { carer: string; id: string; score: number; n: number; chosen: boolean }[] }[];
  pairing: { chosen_shared: number; rota_shared: number; cap: number; rule: string };
  rule: string;
}

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];

export default function Week() {
  const { data, error, reload } = useFetch<WeekPlan>("/api/week");
  const nav = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function plan(o: OneToOne) {
    setBusy(o.resident.id);
    setErr(null);
    try {
      const p = await api.post<Plan>("/api/sessions", { resident: o.resident.id, carer: o.carer.id });
      nav(`/session/${p.id}`);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(null);
    }
  }

  const pair = data?.films.pair;
  const single = data?.films.single;
  const maxN = Math.max(1, ...(data?.matrix.flatMap((m) => m.carers.map((c) => c.n)) ?? [1]));

  return (
    <div className="stack lg">
      <div className="row between">
        <div className="stack" style={{ gap: 6 }}>
          <span className="eyebrow">Monday planning</span>
          <h1>This week</h1>
          <p className="ink2" style={{ maxWidth: 780 }}>
            Two lounge films chosen together, so the resident one film would serve least gets a film that ranks well for
            them; a music hour; and a one-to-one for each resident with the carer whose tastes Qloo finds closest to theirs.
          </p>
        </div>
        <button className="btn" onClick={() => window.print()}>
          <Printer size={16} /> Print the week
        </button>
      </div>

      {error && <ErrorBox error={error} retry={reload} />}
      {!data && !error && <Loading label="Ranking films for every resident and comparing tastes with each carer…" lines={6} />}

      {data && pair && single && (
        <section className="card stack">
          <h2>Two films chosen as a pair</h2>
          <div className="kpis">
            <div className="kpi">
              <div className="v">{single.floor.toFixed(2)}</div>
              <div className="small muted">Least-served resident with one film ({single.least_served})</div>
            </div>
            <div className="kpi">
              <div className="v">{pair.floor.toFixed(2)}</div>
              <div className="small muted">With two films chosen together ({pair.least_served}’s better film)</div>
            </div>
            <div className="kpi">
              <div className="v">{pair.mean.toFixed(2)}</div>
              <div className="small muted">Average of each resident’s better film</div>
            </div>
          </div>
          <p className="small ink2">
            Fit is where a film sits in that resident’s own Qloo ranking of the shortlist (1.00 is their first choice), with
            half credit outside their ages 10 to 30. Encore tries every pair on the shortlist and keeps the one whose
            least-served resident does best.
          </p>
        </section>
      )}

      {data && (
        <div className="grid3">
          {DAYS.filter((d) => data.lounge.some((l) => l.day === d)).map((d) => {
            const l = data.lounge.find((x) => x.day === d)!;
            return (
              <section key={d} className="card stack" aria-label={`${d} in the lounge`}>
                <span className="eyebrow row tight">
                  {l.kind === "film" ? <Clapperboard size={14} /> : <Music size={14} />} {d}, 3 pm
                </span>
                {l.kind === "film" ? (
                  <div className="row" style={{ alignItems: "flex-start" }}>
                    <Art src={l.image} alt={l.name} className="week-poster" />
                    <div className="stack" style={{ gap: 4 }}>
                      <h3>{l.name}</h3>
                      <span className="small ink2">
                        {l.year}
                        {l.duration ? ` · ${l.duration} min` : ""}
                        {l.genres.length ? ` · ${l.genres.slice(0, 2).join(", ")}` : ""}
                      </span>
                    </div>
                  </div>
                ) : (
                  <>
                    <h3>Music hour</h3>
                    <span className="small ink2">{l.artists.join(" · ")}</span>
                    <span className="small">
                      {l.covered} of {l.of} residents hear an artist that fits them at 0.6 or better.{" "}
                      <Link to="/lounge?tab=music">Playlist</Link>
                    </span>
                  </>
                )}
              </section>
            );
          })}
        </div>
      )}

      {data && (
        <Section
          title="One-to-ones"
          aside={
            <span className="small muted">
              Matched pairs share {data.pairing.chosen_shared} tastes in Qloo; an alphabetical rota would share {data.pairing.rota_shared}.
            </span>
          }
        >
          {err && <ErrorBox error={err} />}
          <div className="week-days">
            {DAYS.map((d) => (
              <div key={d} className="stack" style={{ gap: 10 }}>
                <h3>{d}</h3>
                {data.one_to_ones
                  .filter((o) => o.day === d)
                  .map((o) => (
                    <div key={o.resident.id} className="card flat stack" style={{ gap: 6, padding: 14 }}>
                      <div className="row tight">
                        {o.resident.flag && <Flag size={14} aria-label="Staff flag" />}
                        <Link to={`/residents/${o.resident.id}`}>
                          <b>{o.resident.first_name}</b>
                        </Link>
                        <span className="muted">with</span>
                        <b>{o.carer.first_name}</b>
                      </div>
                      {o.link && (
                        <span className="small ink2 row tight" style={{ alignItems: "flex-start" }}>
                          <HeartHandshake size={14} style={{ flex: "none", marginTop: 3 }} />
                          <span>
                            {o.link.tag}: {o.resident.first_name}’s {o.link.resident} and {o.carer.first_name}’s {o.link.carer}
                          </span>
                        </span>
                      )}
                      <span className="tiny muted">
                        {o.n} shared tastes{o.rota_carer && o.rota_carer !== o.carer.first_name ? ` · the rota had ${o.rota_carer}` : ""}
                      </span>
                      <button className="btn sm" disabled={!!busy} onClick={() => plan(o)}>
                        {busy === o.resident.id ? "Planning…" : "Plan session"} <ArrowRight size={14} />
                      </button>
                    </div>
                  ))}
              </div>
            ))}
          </div>
          <p className="small muted">{data.pairing.rule} Residents with a staff flag go first, then those this week’s films serve least.</p>
        </Section>
      )}

      <div className="grid2">
      {data && pair && (
        <Section title="Each resident’s better film" aside={<span className="small muted">Darker is a better fit</span>}>
          <div className="matrix-wrap">
            <table className="matrix">
              <thead>
                <tr>
                  <th />
                  <th>Tuesday: {pair.films[0].name}</th>
                  <th>Thursday: {pair.films[1].name}</th>
                </tr>
              </thead>
              <tbody>
                {pair.per_resident.map((r) => (
                  <tr key={r.id}>
                    <th>{r.name}</th>
                    {[r.tuesday, r.thursday].map((v, i) => {
                      const better = v >= (i ? r.tuesday : r.thursday);
                      return (
                        <td key={i} className="cell" style={{ background: fitColor(v), color: fitInk(v), outline: better ? "2px solid var(--ink)" : undefined }}>
                          {v.toFixed(2)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">The outlined cell is the film that serves each resident better this week.</p>
        </Section>
      )}

      {data && (
        <Section title="Shared tastes, resident by carer" aside={<span className="small muted">From Qloo Compare on each pair’s favourites</span>}>
          <div className="matrix-wrap">
            <table className="matrix">
              <thead>
                <tr>
                  <th />
                  {data.carers.map((c) => (
                    <th key={c.id}>{c.first_name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.matrix.map((m) => (
                  <tr key={m.id}>
                    <th>{m.resident}</th>
                    {m.carers.map((c) => {
                      const v = c.n / maxN;
                      return (
                        <td key={c.id} className="cell" style={{ background: fitColor(v), color: fitInk(v), outline: c.chosen ? "2px solid var(--ink)" : undefined }}>
                          {c.n}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">
            Each cell counts the distinct genres, instruments and themes Qloo finds in both people’s favourites. Outlined:
            the carer assigned. Each carer takes at most {data.pairing.cap} one-to-ones.
          </p>
        </Section>
      )}
      </div>
    </div>
  );
}
