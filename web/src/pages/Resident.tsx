import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, Check, Clapperboard, FileText, Flag, MapPin, Plus, Quote, ShieldOff, Trash2, Utensils, X } from "lucide-react";
import { api, type Home, type Item, type Plan, type Profile } from "../api";
import { Art, Avatar, EraRibbon, ErrorBox, ItemCard, Loading, PlayLinks, Section, TypeIcon, useFetch } from "../ui";

const KIND_LABEL: Record<string, string> = { artist: "Singer or band", movie: "Film", tv_show: "TV show", book: "Book" };
const REACTION_LABEL: Record<string, string> = { lit_up: "Lit up", sang_along: "Sang or moved", no_response: "No response", upset: "Seemed upset" };

export default function Resident() {
  const { id } = useParams();
  const prof = useFetch<Profile>(`/api/people/${id}/profile`, [id]);
  const home = useFetch<Home>("/api/home");
  const nav = useNavigate();
  const [carer, setCarer] = useState("c-priya");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState("artist");

  const p = prof.data;
  if (prof.error) return <ErrorBox error={prof.error} retry={prof.reload} />;
  if (!p) return <Loading label="Looking up the culture of their youth with Qloo…" lines={6} />;
  const person = p.person;
  const shelves = p.era?.shelves ?? {};
  const all: Item[] = Object.values(shelves).flatMap((s) => s.items.slice(0, 8));

  async function act(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
      await prof.reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function plan() {
    setBusy(true);
    try {
      const s = await api.post<Plan>("/api/sessions", { resident: person.id, carer });
      nav(`/session/${s.id}`);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="side">
      <aside className="stack">
        <div className="card stack">
          <div className="row">
            <Avatar name={person.first_name} id={person.id} size="lg" />
            <div>
              <h1 style={{ fontSize: "2rem" }}>
                {person.first_name}
                {person.last_initial ? ` ${person.last_initial}.` : ""}
              </h1>
              <div className="ink2">
                {person.age} · born {person.birth_year}
              </div>
            </div>
          </div>
          <div className="small stack" style={{ gap: 4 }}>
            <span className="row tight">
              <MapPin size={15} /> Grew up in {person.city}, {person.country}
            </span>
            <span className="muted">
              Speaks {person.languages}
              {person.room ? ` · Room ${person.room}` : ""}
            </span>
          </div>
          {person.guest && (
            <div className="notice small stack" style={{ gap: 8 }}>
              <span>
                You added {person.first_name} with the family form. Only this browser sees this page, and it is removed at the
                nightly reset.
              </span>
              <span className="row tight">
                <Link className="btn sm" to={`/lounge?add=${person.id}`}>
                  <Clapperboard size={14} /> Bring {person.first_name} to the lounge
                </Link>
                <button
                  className="btn ghost sm"
                  onClick={async () => {
                    await api.del(`/api/people/${person.id}`);
                    nav("/add");
                  }}
                >
                  <Trash2 size={14} /> Remove
                </button>
              </span>
            </div>
          )}
          {!person.guest && person.family_note && (
            <blockquote className="small ink2" style={{ margin: 0, borderLeft: "3px solid var(--line-2)", paddingLeft: 10 }}>
              <Quote size={14} /> {person.family_note}
            </blockquote>
          )}
          {person.care_note && (
            <div className="notice small">
              <span className="row tight">
                <Flag size={14} /> <b>Staff note</b>
              </span>
              {person.care_note}
              <div className="tiny muted">Stays in Encore. Never sent to Qloo or to the model.</div>
            </div>
          )}
          <div className="stack" style={{ gap: 8 }}>
            <label className="small row tight">
              Plan a one-to-one with
              <select value={carer} onChange={(e) => setCarer(e.target.value)}>
                {home.data?.carers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.first_name}
                  </option>
                ))}
              </select>
            </label>
            <button className="btn primary" onClick={plan} disabled={busy}>
              {busy ? "Planning…" : "Plan session"} <ArrowRight size={16} />
            </button>
            <Link className="btn" to={`/record/${person.id}`}>
              <FileText size={16} /> Activity record
            </Link>
          </div>
        </div>

        <div className="card stack" id="favourites">
          <h3>From the family</h3>
          {err && <ErrorBox error={err} />}
          <ul className="stack" style={{ gap: 8, listStyle: "none", padding: 0, margin: 0 }}>
            {p.favourites.map((f) => (
              <li key={f.id} className="row tight">
                <TypeIcon type={f.kind} />
                <span className="grow">
                  {f.entity_name ?? f.label}
                  {f.source === "session" && <span className="chip good" style={{ marginLeft: 6 }}>from a session</span>}
                  {f.status === "needs_input" && <span className="chip warn" style={{ marginLeft: 6 }}>confirm</span>}
                  {f.status === "unresolved" && <span className="chip warn" style={{ marginLeft: 6 }}>not in Qloo</span>}
                </span>
                <button className="btn ghost sm" aria-label={`Remove ${f.label}`} onClick={() => act(() => api.del(`/api/people/${person.id}/favourites/${f.id}`))}>
                  <X size={14} />
                </button>
              </li>
            ))}
          </ul>
          {p.pending.map((f) => (
            <div key={f.id} className="notice small stack" style={{ gap: 8 }}>
              <span>
                The family wrote “<b>{f.label}</b>”. Which one do they mean?
              </span>
              {f.candidates.slice(0, 3).map((c) => (
                <button key={c.entity_id} className="btn sm" style={{ justifyContent: "flex-start" }}
                  onClick={() => act(() => api.post(`/api/favourites/${f.id}/confirm`, { entity_id: c.entity_id, entity_name: c.name }))}>
                  <Check size={14} /> {c.name} {c.year ? `(${c.year})` : ""}
                </button>
              ))}
            </div>
          ))}
          <form
            className="row tight"
            onSubmit={(e) => {
              e.preventDefault();
              if (label.trim().length < 2) return;
              act(() => api.post(`/api/people/${person.id}/favourites`, { label, kind })).then(() => setLabel(""));
            }}
          >
            <input type="text" className="grow" placeholder="Add a favourite" value={label} onChange={(e) => setLabel(e.target.value)} aria-label="Favourite name" />
            <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind">
              {Object.entries(KIND_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
            <button className="btn sm" aria-label="Add favourite">
              <Plus size={14} />
            </button>
          </form>
        </div>

        <div className="card stack">
          <h3 className="row tight">
            <ShieldOff size={18} /> Avoid
          </h3>
          <div className="row tight">
            {p.avoid.length === 0 && <span className="small muted">Nothing on the list.</span>}
            {p.avoid.map((a) => (
              <span key={a.id} className="chip">
                {a.label}
                <span className="muted">· {a.source}</span>
                <button className="btn ghost sm" style={{ padding: 0 }} aria-label={`Remove ${a.label}`} onClick={() => act(() => api.del(`/api/people/${person.id}/avoid/${a.id}`))}>
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
          {p.house_rules.map(([, l]) => (
            <span key={l} className="small muted">
              House rule: {l}
            </span>
          ))}
        </div>
      </aside>

      <div className="stack lg">
        {p.errors.length > 0 && <ErrorBox error={`Some answers are missing: ${p.errors[0]}`} retry={prof.reload} />}
        {p.era && (
          <Section
            title={`The culture of ${person.first_name}’s youth`}
            aside={
              <div className="legend">
                <span>
                  <i style={{ background: "var(--home)" }} /> From {person.country}
                </span>
                <span>
                  <i style={{ background: "var(--family)" }} /> Linked to the family’s favourites
                </span>
              </div>
            }
          >
            <EraRibbon birth={person.birth_year} window={p.era.window} items={all} />
            <p className="small ink2" style={{ marginTop: 6 }}>
              People remember the most from ages 10 to 30, the reminiscence bump. Encore asks Qloo for what was released
              in {person.first_name}’s window, and for artists active in it.
            </p>
          </Section>
        )}

        {p.family.some((f) => f.songs.length) && (
          <Section title="The family’s own picks">
            <div className="shelf">
              {p.family
                .filter((f) => f.entity_id)
                .map((f) => (
                  <article key={f.id} className={`item ${f.kind !== "artist" ? "film" : ""}`}>
                    <Art src={f.image} alt={f.name} />
                    <div className="body">
                      <div className="t">{f.name}</div>
                      {f.songs[0] && <div className="song">“{f.songs[0]}”</div>}
                      <div className="small muted">{f.year}</div>
                      {f.kind === "artist" && <PlayLinks artist={f.name} song={f.songs[0]} />}
                    </div>
                  </article>
                ))}
            </div>
          </Section>
        )}

        {["artist", "movie", "tv_show", "book"].map((d) => {
          const s = shelves[d];
          if (!s || !s.items.length) return null;
          return (
            <Section
              key={d}
              title={
                <span className="row tight">
                  <TypeIcon type={d} size={20} /> {s.label}
                </span>
              }
              aside={
                <span className="small muted">
                  {s.considered} from Qloo{s.outside_era ? `, ${s.outside_era} outside ${s.window[0]}–${s.window[1]} left out` : ""}
                </span>
              }
            >
              <div className="shelf">
                {s.items.map((it) => (
                  <ItemCard key={it.entity_id} item={it} actions={d === "artist" ? <PlayLinks artist={it.name} song={it.songs?.[0]} /> : undefined} />
                ))}
              </div>
            </Section>
          );
        })}

        {p.food && p.food.places.length > 0 && (
          <Section
            title={
              <span className="row tight">
                <Utensils size={20} /> A taste of home near Maple Court
              </span>
            }
            aside={<span className="small muted">Ordered by Qloo for people who share {person.first_name}’s tastes</span>}
          >
            <div className="table-wrap">
              <table className="plain">
                <thead>
                  <tr>
                    <th>Place</th>
                    <th>Known for</th>
                    <th>Distance</th>
                    <th>Access</th>
                  </tr>
                </thead>
                <tbody>
                  {p.food.places.slice(0, 5).map((pl) => (
                    <tr key={pl.entity_id}>
                      <td>
                        <b>{pl.name}</b>
                        <div className="tiny muted">{pl.address}</div>
                      </td>
                      <td>{pl.dishes.join(", ") || <span className="muted">–</span>}</td>
                      <td>{pl.distance_km} km</td>
                      <td>{pl.wheelchair ? "Wheelchair access listed" : <span className="muted">Not listed</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        <Section title="What sessions have shown">
          {p.history.length === 0 ? (
            <p className="muted">No sessions recorded yet. Reactions recorded in a session change what Encore asks Qloo next.</p>
          ) : (
            <table className="plain">
              <tbody>
                {p.history.map((h) => (
                  <tr key={h.id}>
                    <td className="small muted">{h.at.slice(0, 16)}</td>
                    <td>{h.entity_name}</td>
                    <td>{REACTION_LABEL[h.reaction] ?? h.reaction}</td>
                    <td className="small muted">{h.carer ? `with ${h.carer}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>
      </div>
    </div>
  );
}
