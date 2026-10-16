import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, Lock, Music, Film, Tv, BookOpen, Plus, X } from "lucide-react";
import { api, type Home } from "../api";
import { ErrorBox, Loading, useFetch } from "../ui";

const KINDS: { key: string; label: string; icon: React.ReactNode; hint: string }[] = [
  { key: "artist", label: "Singer or band", icon: <Music size={15} />, hint: "Nat King Cole" },
  { key: "movie", label: "Film", icon: <Film size={15} />, hint: "Roman Holiday" },
  { key: "tv_show", label: "TV show", icon: <Tv size={15} />, hint: "The Ed Sullivan Show" },
  { key: "book", label: "Book", icon: <BookOpen size={15} />, hint: "To Kill a Mockingbird" },
];

interface Fav {
  label: string;
  kind: string;
}

interface Added {
  id: string;
  favourites: { label: string; kind: string; status: string; entity_name: string | null }[];
}

export default function Add() {
  const home = useFetch<Home>("/api/home");
  const nav = useNavigate();
  const [relation, setRelation] = useState("Grandma");
  const [year, setYear] = useState(1948);
  const [city, setCity] = useState("");
  const [country, setCountry] = useState("United States");
  const [favs, setFavs] = useState<Fav[]>([
    { label: "", kind: "artist" },
    { label: "", kind: "movie" },
  ]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const mine = home.data?.residents.filter((r) => r.guest) ?? [];
  const filled = favs.filter((f) => f.label.trim().length >= 2);
  const ready = city.trim().length >= 2 && filled.length > 0 && !busy;

  function setFav(i: number, patch: Partial<Fav>) {
    setFavs(favs.map((f, k) => (k === i ? { ...f, ...patch } : f)));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.post<Added>("/api/people", {
        relation,
        birth_year: year,
        city: city.trim(),
        country,
        favourites: filled.map((f) => ({ label: f.label.trim(), kind: f.kind })),
      });
      nav(`/residents/${r.id}`);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  const years = Array.from({ length: 56 }, (_, i) => 1975 - i);

  return (
    <div className="stack lg" style={{ maxWidth: 860 }}>
      <div className="stack" style={{ gap: 6 }}>
        <span className="eyebrow">The family form</span>
        <h1>Try it with someone you love</h1>
        <p className="ink2">
          This is the form a family fills in when someone moves into a care home. Tell Encore three things you could say in
          a minute: the year they were born, where they grew up, and a favourite or two. Encore asks Qloo for the songs,
          films and shows of their ages 10 to 30, then plans a ten-minute session around them.
        </p>
      </div>

      {home.error && <ErrorBox error={home.error} retry={home.reload} />}
      {!home.data && !home.error && <Loading label="Loading…" lines={2} />}

      {home.data && (
        <form className="card stack lg" onSubmit={submit} aria-label="Add someone">
          <div className="grid3">
            <label className="stack" style={{ gap: 6 }}>
              <b>Who are they to you?</b>
              <select value={relation} onChange={(e) => setRelation(e.target.value)}>
                {home.data.relations.map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </label>
            <label className="stack" style={{ gap: 6 }}>
              <b>Born in</b>
              <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
                {years.map((y) => (
                  <option key={y}>{y}</option>
                ))}
              </select>
              <span className="tiny muted">
                Ages 10 to 30: {year + 10} to {year + 30}
              </span>
            </label>
            <label className="stack" style={{ gap: 6 }}>
              <b>Grew up in</b>
              <input type="text" value={city} onChange={(e) => setCity(e.target.value)} placeholder="Town or city" maxLength={60} required />
              <select value={country} onChange={(e) => setCountry(e.target.value)} aria-label="Country">
                {home.data.countries.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
          </div>

          <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0, gap: 10 }}>
            <legend>
              <b>A favourite or two</b> <span className="small muted">(up to three, spelled the way you would say it)</span>
            </legend>
            {favs.map((f, i) => (
              <div key={i} className="row" style={{ gap: 8 }}>
                <select value={f.kind} onChange={(e) => setFav(i, { kind: e.target.value })} aria-label={`Favourite ${i + 1} type`}>
                  {KINDS.map((k) => (
                    <option key={k.key} value={k.key}>
                      {k.label}
                    </option>
                  ))}
                </select>
                <input type="text"
                  className="grow"
                  value={f.label}
                  onChange={(e) => setFav(i, { label: e.target.value })}
                  placeholder={`e.g. ${KINDS.find((k) => k.key === f.kind)?.hint}`}
                  maxLength={80}
                  aria-label={`Favourite ${i + 1}`}
                />
                {favs.length > 1 && (
                  <button type="button" className="btn ghost sm" aria-label="Remove" onClick={() => setFavs(favs.filter((_, k) => k !== i))}>
                    <X size={14} />
                  </button>
                )}
              </div>
            ))}
            {favs.length < 3 && (
              <button type="button" className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => setFavs([...favs, { label: "", kind: "tv_show" }])}>
                <Plus size={14} /> Add another
              </button>
            )}
          </fieldset>

          <div className="notice small row tight" style={{ alignItems: "flex-start" }}>
            <Lock size={16} style={{ flex: "none", marginTop: 2 }} />
            <span>
              Encore asks for no name. Qloo receives the favourites as you typed them, a range of years and the country.
              The person you add is visible only in this browser and is removed at the nightly reset (08:00 UTC). Every
              request is listed on <Link to="/qloo">What Qloo saw</Link>.
            </span>
          </div>

          {err && <ErrorBox error={err} />}
          <div className="row between">
            <span className="small muted">{busy ? "Matching your favourites in Qloo…" : `${filled.length} favourite${filled.length === 1 ? "" : "s"} ready`}</span>
            <button className="btn primary" type="submit" disabled={!ready}>
              {busy ? "Looking them up…" : "See the culture of their youth"} <ArrowRight size={16} />
            </button>
          </div>
        </form>
      )}

      {mine.length > 0 && (
        <section className="stack">
          <h2>You added</h2>
          <div className="people">
            {mine.map((r) => (
              <Link key={r.id} to={`/residents/${r.id}`} className="person">
                <div className="grow">
                  <b>{r.first_name}</b>
                  <div className="small muted">
                    Born {r.birth_year} · {r.city}, {r.country}
                  </div>
                  <div className="tiny ink2">{r.favourites.join(" · ")}</div>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
