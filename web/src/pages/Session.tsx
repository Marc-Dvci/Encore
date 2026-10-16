import { useState, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";
import { Frown, Meh, Mic2, Sparkles, MessageCircle, Utensils, HeartHandshake, Film, Music } from "lucide-react";
import { api, type Effect, type Plan, type Step } from "../api";
import { Art, Avatar, ErrorBox, Loading, PlayLinks, useFetch } from "../ui";

const REACT_ICONS: Record<string, ReactElement> = {
  lit_up: <Sparkles aria-hidden />,
  sang_along: <Mic2 aria-hidden />,
  no_response: <Meh aria-hidden />,
  upset: <Frown aria-hidden />,
};
const REACTS: [string, string][] = [
  ["lit_up", "Lit up"],
  ["sang_along", "Sang or moved"],
  ["no_response", "No response"],
  ["upset", "Seemed upset"],
];

export default function Session() {
  const { id } = useParams();
  const { data: plan, error, reload } = useFetch<Plan>(`/api/sessions/${id}`, [id]);
  const [done, setDone] = useState<Record<string, string>>({});
  const [effects, setEffects] = useState<Record<string, Effect>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (error) return <ErrorBox error={error} retry={reload} />;
  if (!plan) return <Loading label="Opening the session…" />;
  const recorded: Record<string, string> = {};
  plan.reactions?.forEach((r) => (recorded[r.entity_id] = r.reaction));

  async function react(step: Step, reaction: string) {
    const item = step.item!;
    setBusy(item.entity_id);
    setErr(null);
    try {
      const eff = await api.post<Effect>("/api/reactions", {
        person_id: plan!.resident.id,
        carer_id: plan!.carer.id,
        session_id: plan!.id,
        reaction,
        item: { entity_id: item.entity_id, name: item.name, type: item.type ?? item.kind ?? "artist", genre_tags: item.genre_tags ?? [] },
      });
      setDone((d) => ({ ...d, [item.entity_id]: reaction }));
      setEffects((e) => ({ ...e, [item.entity_id]: eff }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function avoidTag(tag: { tag_id: string; name: string }) {
    await api.post(`/api/people/${plan!.resident.id}/avoid`, { tag_id: tag.tag_id, label: tag.name });
    setErr(null);
  }

  const r = plan.resident;
  const w = plan.words;
  return (
    <div className="session stack lg">
      <div className="row between">
        <div className="row">
          <Avatar name={r.first_name} id={r.id} size="lg" />
          <div>
            <span className="eyebrow">One-to-one · about ten minutes</span>
            <h1>
              {r.first_name} with {plan.carer.first_name}
            </h1>
            <div className="ink2 small">
              {r.first_name} grew up in {r.city} and was 10 to 30 from {plan.window[0]} to {plan.window[1]}.{" "}
              {plan.carer.first_name} grew up in {plan.carer.city}.
            </div>
          </div>
        </div>
        <Link to={`/residents/${r.id}`} className="btn noprint">
          {r.first_name}’s profile
        </Link>
      </div>

      <section className="card stack" aria-label="What to say">
        <span className="eyebrow row tight">
          <MessageCircle size={14} /> What to say {plan.words_source === "template" ? "(template)" : ""}
        </span>
        {w.greeting && <p className="ink2">Greeting: {w.greeting}</p>}
        <p className="say">“{w.opener}”</p>
        <ul className="stack" style={{ gap: 6, margin: 0 }}>
          {w.prompts.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
        <p className="small ink2">If it goes quiet: {w.if_quiet}</p>
      </section>

      {err && <ErrorBox error={err} />}

      {plan.steps.map((s, i) => {
        const it = s.item;
        const isFilm = s.kind === "film";
        const state = it ? done[it.entity_id] ?? recorded[it.entity_id] : undefined;
        const eff = it ? effects[it.entity_id] : undefined;
        return (
          <section key={i} className="card stack" aria-label={s.title}>
            <div className={`step ${isFilm ? "film" : ""}`}>
              {s.kind === "food" && s.place ? (
                <div className="art" style={{ display: "grid", placeItems: "center" }}>
                  <Utensils size={48} className="muted" />
                </div>
              ) : (
                <Art src={it?.image} alt={it?.name ?? s.title} />
              )}
              <div className="stack" style={{ gap: 8 }}>
                <span className="eyebrow row tight">
                  {s.kind === "film" ? <Film size={14} /> : s.kind === "common" ? <HeartHandshake size={14} /> : s.kind === "food" ? <Utensils size={14} /> : <Music size={14} />}
                  {i + 1}. {s.title}
                </span>
                {s.kind === "food" && s.place ? (
                  <>
                    <h2>{s.place.name}</h2>
                    <p>
                      {s.place.dishes.length ? `Known for ${s.place.dishes.join(", ")}. ` : ""}
                      {s.place.distance_km} km away{s.place.wheelchair ? ", wheelchair access listed" : ""}.
                    </p>
                    <p className="small ink2">Talk about it, or plan a Sunday order with the family.</p>
                  </>
                ) : (
                  it && (
                    <>
                      <h2>{s.song ? `“${s.song}”` : it.name}</h2>
                      <div className="ink2">
                        {s.song ? `${it.name} · ` : ""}
                        {it.type === "artist" || s.song ? `recording since ${it.start_year ?? it.year}` : it.year}
                        {it.duration ? ` · ${it.duration} min` : ""}
                      </div>
                    </>
                  )
                )}
                <p className="small ink2">{s.why}</p>
                {s.shared && s.shared.length > 0 && (
                  <div className="row tight">
                    <span className="small muted">Both lean to</span>
                    {s.shared.map((t) => (
                      <span key={t.name} className="chip">
                        {t.name}
                      </span>
                    ))}
                  </div>
                )}
                {it && (s.kind === "film" ? <PlayLinks film={`${it.name} ${it.year}`} /> : <PlayLinks artist={it.name} song={s.song} />)}
              </div>
            </div>
            {it && (
              <div>
                <div className="reacts" role="group" aria-label={`How did ${r.first_name} respond to ${it.name}?`}>
                  {REACTS.map(([k, label]) => (
                    <button key={k} className={`react ${state === k ? "on" : ""}`} aria-pressed={state === k} disabled={busy === it.entity_id} onClick={() => react(s, k)}>
                      {REACT_ICONS[k]}
                      {label}
                    </button>
                  ))}
                </div>
                {eff && (
                  <div className="effect stack" style={{ gap: 6, marginTop: 10 }} aria-live="polite">
                    <b>{eff.change}.</b>
                    {eff.shelf_in.length > 0 && (
                      <span>
                        New on {r.first_name}’s shelf: {eff.shelf_in.map((x) => `${x.name} (${x.year})`).join(", ")}.
                      </span>
                    )}
                    {eff.suggest_tags && eff.suggest_tags.length > 0 && (
                      <span className="row tight">
                        Avoid more like this?
                        {eff.suggest_tags.map((t) => (
                          <button key={t.tag_id} className="btn sm" onClick={() => avoidTag(t)}>
                            Avoid {t.name}
                          </button>
                        ))}
                      </span>
                    )}
                  </div>
                )}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
