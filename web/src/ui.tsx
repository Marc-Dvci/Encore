import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Music, Film, Tv, BookOpen, Loader2, AlertTriangle, ExternalLink } from "lucide-react";
import { api, spotifyUrl, youtubeUrl, type Item } from "./api";

export function useFetch<T>(url: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0);
  const load = useCallback(async () => {
    if (!url) return;
    const n = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const d = await api.get<T>(url);
      if (n === seq.current) setData(d);
    } catch (e) {
      if (n === seq.current) setError((e as Error).message);
    } finally {
      if (n === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, ...deps]);
  useEffect(() => {
    load();
  }, [load]);
  return { data, error, loading, reload: load, setData };
}

const AVATAR = ["#8c2f4b", "#00756a", "#9a5b13", "#4a5a9c", "#7a4a8c", "#3f6f3a", "#a4442b", "#2f6a87"];
export function Avatar({ name, id, size, off }: { name: string; id: string; size?: "sm" | "lg"; off?: boolean }) {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return (
    <span className={`avatar ${size ?? ""} ${off ? "off" : ""}`} style={{ background: AVATAR[h % AVATAR.length] }} aria-hidden>
      {name.slice(0, 1)}
    </span>
  );
}

export function LaneChip({ lane }: { lane: string }) {
  const home = lane === "home";
  return (
    <span className={`chip ${home ? "home" : "family"}`}>
      <i className="dot" style={{ background: home ? "var(--home)" : "var(--family)" }} />
      {home ? "From home" : "Family favourites"}
    </span>
  );
}

export function TypeIcon({ type, size = 16 }: { type: string; size?: number }) {
  if (type === "artist") return <Music size={size} aria-hidden />;
  if (type === "movie") return <Film size={size} aria-hidden />;
  if (type === "tv_show") return <Tv size={size} aria-hidden />;
  return <BookOpen size={size} aria-hidden />;
}

/** Qloo images need the API key, so they are served through Encore's own /img proxy. */
export function imgUrl(src: string | null | undefined) {
  if (!src) return null;
  const m = src.match(/^https:\/\/images\.qloo\.com\/i\/(.+)$/);
  return m ? `/img/${m[1]}` : src;
}

export function Art({ src: raw, alt, className, children }: { src: string | null | undefined; alt: string; className?: string; children?: ReactNode }) {
  const [ok, setOk] = useState(true);
  const src = imgUrl(raw);
  return (
    <div className={className ?? "art"} style={src && ok ? { backgroundImage: `url(${src})` } : undefined} role="img" aria-label={alt}>
      {src && ok ? <img src={src} alt="" style={{ display: "none" }} onError={() => setOk(false)} /> : <span className="art-fallback"><span>{alt.slice(0, 1)}</span></span>}
      {children}
    </div>
  );
}

export function ItemCard({ item, actions }: { item: Item; actions?: ReactNode }) {
  const film = item.type === "movie" || item.type === "tv_show" || item.type === "book";
  const song = item.songs?.[0];
  return (
    <article className={`item ${film ? "film" : ""}`}>
      <Art src={item.image} alt={item.name}>
        <span className="lane">{item.lanes[0] && <LaneChip lane={item.lanes[0]} />}</span>
      </Art>
      <div className="body">
        <div className="t">{item.name}</div>
        {song && <div className="song">“{song}”</div>}
        <div className="small muted">
          {item.type === "artist" ? `Active since ${item.start_year ?? item.year}` : item.year}
          {item.type !== "artist" && item.age_then != null && <> · age {item.age_then}</>}
          {item.duration ? <> · {item.duration} min</> : null}
        </div>
        {item.because.length > 0 && <div className="tiny ink2">Qloo links it to {item.because.join(" and ")}</div>}
        {actions}
      </div>
    </article>
  );
}

export function PlayLinks({ artist, song, film }: { artist?: string; song?: string | null; film?: string }) {
  return (
    <span className="row tight">
      {artist && (
        <a className="btn sm" href={spotifyUrl(artist, song)} target="_blank" rel="noreferrer">
          <Music size={14} /> Spotify <ExternalLink size={12} />
        </a>
      )}
      <a className="btn sm" href={youtubeUrl(film ? `${film} film scene` : `${artist} ${song ?? ""}`)} target="_blank" rel="noreferrer">
        YouTube <ExternalLink size={12} />
      </a>
    </span>
  );
}

export function Loading({ label = "Asking Qloo…", lines = 3 }: { label?: string; lines?: number }) {
  return (
    <div className="stack" aria-live="polite">
      <div className="row muted small">
        <Loader2 size={16} className="spin" /> {label}
      </div>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: 22, width: `${90 - i * 14}%` }} />
      ))}
    </div>
  );
}

export function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  return (
    <div className="notice warn row" role="alert">
      <AlertTriangle size={18} /> <span className="grow">{error}</span>
      {retry && (
        <button className="btn sm" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}

/** Sequential single-hue fill for a 0..1 fit. */
export function fitColor(v: number) {
  const p = Math.round(12 + Math.max(0, Math.min(1, v)) * 88);
  return `color-mix(in oklab, var(--seq-hi) ${p}%, var(--seq-lo))`;
}
export function fitInk(v: number) {
  return v > 0.55 ? "#fff" : "var(--ink)";
}

export function useTip() {
  const [tip, setTip] = useState<{ x: number; y: number; text: ReactNode } | null>(null);
  const node = tip ? (
    <div className="tip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 280), top: tip.y + 14 }}>
      {tip.text}
    </div>
  ) : null;
  return {
    node,
    bind: (text: ReactNode) => ({
      onMouseMove: (e: React.MouseEvent) => setTip({ x: e.clientX, y: e.clientY, text }),
      onMouseLeave: () => setTip(null),
      onFocus: (e: React.FocusEvent) => {
        const r = (e.target as HTMLElement).getBoundingClientRect();
        setTip({ x: r.right, y: r.bottom, text });
      },
      onBlur: () => setTip(null),
    }),
  };
}

/** A timeline from birth to the end of the reminiscence window, the window shaded and each shelf item placed at its year. */
export function EraRibbon({ birth, window: w, items }: { birth: number; window: [number, number]; items: Item[] }) {
  const { node, bind } = useTip();
  const start = birth;
  const end = w[1] + 12;
  const W = 1000;
  const base = 150;
  const x = (y: number) => 20 + ((y - start) / (end - start)) * (W - 40);
  const ticks: number[] = [];
  for (let y = Math.ceil(start / 5) * 5; y <= end; y += 5) ticks.push(y);
  const placed = items
    .filter((i) => i.year)
    .map((i) => ({ i, y: i.type === "artist" ? birth + (i.age_then ?? 0) : (i.year as number) }))
    .sort((a, b) => a.y - b.y);
  const stackAt: Record<number, number> = {};
  return (
    <div className="ribbon">
      <svg viewBox={`0 0 ${W} ${base + 30}`} role="img" aria-label={`Timeline from ${start} to ${end}; ages 10 to 30 run ${w[0]} to ${w[1]}. ${placed.length} items placed.`}>
        <rect x={x(w[0])} y={4} width={x(w[1]) - x(w[0])} height={base - 4} rx={8} fill="var(--accent-soft)" />
        <text x={x(w[0]) + 10} y={22} className="lbl" style={{ fill: "var(--accent)", fontWeight: 700, fontSize: 13 }}>
          Ages 10 to 30 · {w[0]}–{w[1]}
        </text>
        <line x1={0} x2={W} y1={base} y2={base} stroke="var(--line-2)" />
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={base} y2={base + 6} stroke="var(--line-2)" />
            <text x={x(t)} y={base + 20} textAnchor="middle" className="lbl">
              {t === start ? `born ${t}` : `${t} · ${t - birth}`}
            </text>
          </g>
        ))}
        {placed.map(({ i, y }) => {
          const k = Math.round(y);
          const level = (stackAt[k] = (stackAt[k] ?? 0) + 1);
          const cy = base - 12 - (level - 1) * 15;
          const home = i.lanes[0] === "home";
          return (
            <circle
              key={i.entity_id}
              cx={x(y)}
              cy={cy}
              r={6.5}
              fill={home ? "var(--home)" : "var(--family)"}
              stroke="var(--surface)"
              strokeWidth={2}
              tabIndex={0}
              {...bind(
                <>
                  <b>{i.name}</b>
                  <br />
                  {Math.round(y)} · age {Math.round(y - birth)} · {home ? "from home" : "linked to the family’s favourites"}
                </>,
              )}
            />
          );
        })}
      </svg>
      <div className="tiny muted">Year · age</div>
      {node}
    </div>
  );
}

export function Section({ title, aside, children, id }: { title: ReactNode; aside?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section className="card" id={id}>
      <div className="card-h">
        <h2>{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}
