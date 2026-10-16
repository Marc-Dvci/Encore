import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, Sparkles, Clapperboard, Music, HelpCircle, Flag, UserPlus, CalendarDays } from "lucide-react";
import { api, type Candidate, type Home, type Plan } from "../api";
import { Art, Avatar, ErrorBox, Loading, fitColor, fitInk, useFetch, useTip } from "../ui";

interface FilmPick {
  pick: Candidate | null;
  alternatives: { rule: string; name: string; year: number; min_pct: number; least_served: string; mean_pct: number }[];
  residents: string[];
  max_minutes: number;
}
interface Music {
  playlist: (Candidate & { song: string | null })[];
  coverage: { name: string; best: string; pct: number }[];
}

export default function Today() {
  const home = useFetch<Home>("/api/home");
  const film = useFetch<FilmPick>("/api/lounge?domain=movie");
  const music = useFetch<Music>("/api/lounge?domain=artist");
  const nav = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [carerFor, setCarerFor] = useState<Record<string, string>>({});
  const { node, bind } = useTip();

  const queue = useMemo(() => {
    if (!home.data) return [];
    const fit: Record<string, number> = {};
    film.data?.pick?.per_resident.forEach((r) => (fit[r.id] = r.pct));
    return home.data.residents
      .filter((r) => r.present && !r.guest)
      .map((r) => ({ r, fit: fit[r.id] ?? 1 }))
      .sort((a, b) => Number(!!b.r.staff_note) - Number(!!a.r.staff_note) || a.fit - b.fit)
      .slice(0, 4);
  }, [home.data, film.data]);

  const carers = home.data?.carers ?? [];
  const defaultCarer = (i: number, id: string) => carerFor[id] ?? (id === "r-tomasz" ? "c-priya" : carers[i % carers.length]?.id);

  async function plan(rid: string, cid: string) {
    setBusy(rid);
    setErr(null);
    try {
      const p = await api.post<Plan>("/api/sessions", { resident: rid, carer: cid });
      nav(`/session/${p.id}`);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(null);
    }
  }

  async function togglePresent(id: string, present: boolean) {
    await api.post(`/api/people/${id}/present`, { present });
    await home.reload();
    film.reload();
    music.reload();
  }

  const h = home.data;
  const pick = film.data?.pick;
  const popular = film.data?.alternatives?.find((a) => a.rule.startsWith("Most popular"));
  const pending = h?.residents.filter((r) => r.needs_input > 0) ?? [];

  return (
    <div className="stack lg">
      <div className="stack" style={{ gap: 6 }}>
        <span className="eyebrow">{h ? `${h.lounge_time} · ${h.name}` : "Today"}</span>
        <h1>Good afternoon{h ? `, ${h.coordinator}` : ""}.</h1>
        <p className="ink2" style={{ maxWidth: 760 }}>
          {h ? `${h.present} of ${h.residents.length} residents are in the lounge. ` : ""}
          Encore has looked up the songs, films and shows of each one's youth with Qloo, and picked an afternoon that
          leaves nobody out.
        </p>
        <div className="row" style={{ marginTop: 6 }}>
          <Link className="btn primary" to="/add">
            <UserPlus size={16} /> Try it with someone in your family
          </Link>
          <Link className="btn" to="/week">
            <CalendarDays size={16} /> Plan the week
          </Link>
        </div>
      </div>

      {home.error && <ErrorBox error={home.error} retry={home.reload} />}

      {h && (
        <section aria-label="Who is in the lounge" className="card flat">
          <div className="card-h">
            <h3>In the lounge</h3>
            <span className="small muted">Tap a resident to mark them in or out; the picks update.</span>
          </div>
          <div className="row" style={{ gap: 8 }}>
            {h.residents.filter((r) => !r.guest).map((r) => (
              <button
                key={r.id}
                className="btn sm"
                style={{ paddingLeft: 4, opacity: r.present ? 1 : 0.6 }}
                aria-pressed={r.present}
                onClick={() => togglePresent(r.id, !r.present)}
                title={r.present ? "In the lounge" : "Not in the lounge"}
              >
                <Avatar name={r.first_name} id={r.id} size="sm" off={!r.present} /> {r.first_name}
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="grid2">
        <section className="card">
          <div className="card-h">
            <h2 className="row tight">
              <Clapperboard size={22} /> This afternoon’s film
            </h2>
            <Link to="/lounge" className="small">
              How it was chosen
            </Link>
          </div>
          {film.loading && !film.data && <Loading label="Ranking the shortlist for every resident with Qloo…" />}
          {film.error && <ErrorBox error={film.error} retry={film.reload} />}
          {pick && (
            <div className="hero">
              <Art src={pick.image} alt={pick.name} className="poster" />
              <div className="stack">
                <div>
                  <h2 style={{ fontSize: "1.8rem" }}>{pick.name}</h2>
                  <div className="ink2">
                    {pick.year} · {pick.duration} min · {pick.genres.slice(0, 2).join(", ")}
                  </div>
                </div>
                <div>
                  <div className="eyebrow" style={{ marginBottom: 6 }}>
                    Fit for each resident present
                  </div>
                  <div className="dots">
                    {pick.per_resident.map((r) => (
                      <span
                        key={r.id}
                        className="fitdot"
                        tabIndex={0}
                        style={{ background: fitColor(r.pct), color: fitInk(r.pct) }}
                        {...bind(
                          <>
                            <b>{r.name}</b>: fit {r.pct.toFixed(2)}
                            <br />
                            rank in their own list {r.rank_pct.toFixed(2)} × era {r.era}
                          </>,
                        )}
                      >
                        {r.name.slice(0, 2)}
                      </span>
                    ))}
                  </div>
                  {node}
                </div>
                <p className="small">
                  Least-served resident: <b>{pick.least_served}</b>, fit {pick.min_pct.toFixed(2)}.
                  {popular && popular.name !== pick.name && (
                    <>
                      {" "}
                      The most popular film on the shortlist, {popular.name}, would leave {popular.least_served} at{" "}
                      {popular.min_pct.toFixed(2)}.
                    </>
                  )}
                </p>
              </div>
            </div>
          )}
        </section>

        <section className="card">
          <div className="card-h">
            <h2 className="row tight">
              <Music size={22} /> Music hour
            </h2>
            <Link to="/lounge?tab=music" className="small">
              Full playlist
            </Link>
          </div>
          {music.loading && !music.data && <Loading label="Building a playlist with a song for everyone…" />}
          {music.error && <ErrorBox error={music.error} retry={music.reload} />}
          {music.data && (
            <div className="stack">
              <ol className="stack" style={{ gap: 8, margin: 0, paddingLeft: 22 }}>
                {music.data.playlist.slice(0, 7).map((s) => (
                  <li key={s.entity_id}>
                    <b>{s.song ?? s.name}</b> <span className="muted">· {s.name}</span>
                  </li>
                ))}
              </ol>
              <p className="small ink2">
                {music.data.coverage.filter((c) => c.pct >= 0.6).length} of {music.data.coverage.length} residents hear
                an artist that fits them at 0.6 or better.
              </p>
            </div>
          )}
        </section>
      </div>

      <section className="card">
        <div className="card-h">
          <h2 className="row tight">
            <Sparkles size={22} /> One-to-ones to plan
          </h2>
          <span className="small muted">Staff flags first, then whoever today’s film serves least.</span>
        </div>
        {err && <ErrorBox error={err} />}
        {!h || (film.loading && !film.data) ? (
          <Loading label="Waiting for the lounge pick…" lines={2} />
        ) : (
          <div className="stack" style={{ gap: 10 }}>
            {queue.map(({ r, fit }, i) => (
              <div key={r.id} className="row" style={{ padding: "10px 0", borderTop: i ? "1px solid var(--line)" : undefined }}>
                <Avatar name={r.first_name} id={r.id} />
                <div className="grow">
                  <Link to={`/residents/${r.id}`}>
                    <b>{r.first_name}</b>
                  </Link>{" "}
                  <span className="muted">
                    · {r.age} · {r.city}
                  </span>
                  <div className="small ink2">
                    {r.staff_note ? (
                      <span className="row tight">
                        <Flag size={14} /> {r.staff_note}
                      </span>
                    ) : (
                      <>Film fit {fit.toFixed(2)}</>
                    )}
                  </div>
                </div>
                <label className="small row tight">
                  <span className="muted">with</span>
                  <select value={defaultCarer(i, r.id)} onChange={(e) => setCarerFor({ ...carerFor, [r.id]: e.target.value })}>
                    {carers.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.first_name}
                      </option>
                    ))}
                  </select>
                </label>
                <button className="btn primary" disabled={!!busy} onClick={() => plan(r.id, defaultCarer(i, r.id))}>
                  {busy === r.id ? "Planning…" : "Plan session"} <ArrowRight size={16} />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {pending.length > 0 && (
        <section className="card tint">
          <div className="card-h">
            <h3 className="row tight">
              <HelpCircle size={18} /> Needs you
            </h3>
          </div>
          {pending.map((r) => (
            <p key={r.id}>
              {r.first_name}’s family named a favourite Qloo could not match on its own.{" "}
              <Link to={`/residents/${r.id}#favourites`}>Choose the right one</Link>
            </p>
          ))}
        </section>
      )}
    </div>
  );
}
