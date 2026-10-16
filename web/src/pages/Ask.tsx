import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Send, Wrench, Loader2 } from "lucide-react";
import { api } from "../api";
import { ErrorBox } from "../ui";

interface Trace {
  tool: string;
  args: Record<string, unknown>;
  ok: boolean;
  error?: string;
  qloo: { purpose: string; path: string; params: [string, string][]; cached: boolean; results: number | null; ms: number }[];
}
interface Card {
  kind: string;
  id?: string;
  [k: string]: unknown;
}
interface Reply {
  answer: string;
  trace: Trace[];
  cards: Card[];
  source: "model" | "template";
  note?: string;
}
interface Msg {
  role: "user" | "model";
  text: string;
  reply?: Reply;
}

const SUGGESTIONS = [
  "Priya is sitting with Tomasz at three. What should she play first, and what might they both like?",
  "Pick the lounge film for today. Nothing over 100 minutes.",
  "Which songs would get Rosa and Giuseppe singing?",
  "Plan a music hour for everyone in the lounge.",
  "Plan this week: which two films, and who should sit with whom?",
];

export default function Ask() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  async function send(message: string) {
    if (!message.trim() || busy) return;
    const history = msgs.map((m) => ({ role: m.role, text: m.text }));
    setMsgs((m) => [...m, { role: "user", text: message }]);
    setText("");
    setBusy(true);
    setErr(null);
    try {
      const r = await api.post<Reply>("/api/agent", { message, history });
      setMsgs((m) => [...m, { role: "model", text: r.answer, reply: r }]);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
      setTimeout(() => end.current?.scrollIntoView({ behavior: "smooth", block: "end" }), 50);
    }
  }

  return (
    <div className="stack lg" style={{ maxWidth: 940 }}>
      <div className="stack" style={{ gap: 6 }}>
        <span className="eyebrow">Ask Encore</span>
        <h1>Plan in plain words</h1>
        <p className="ink2">
          The agent plans with Encore’s tools and shows each call it made, with the Qloo requests behind it. It can look,
          rank and plan; only staff record reactions and change avoid lists.
        </p>
      </div>

      {msgs.length === 0 && (
        <div className="stack" style={{ gap: 8 }}>
          {SUGGESTIONS.map((s) => (
            <button key={s} className="btn" style={{ justifyContent: "flex-start", textAlign: "left", borderRadius: 14 }} onClick={() => send(s)}>
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="chat" aria-live="polite">
        {msgs.map((m, i) => (
          <div key={i} className="stack" style={{ gap: 8 }}>
            <div className={`msg ${m.role}`}>{m.role === "model" ? <Rich text={m.text} /> : m.text}</div>
            {m.reply && <Evidence reply={m.reply} />}
          </div>
        ))}
        {busy && (
          <div className="msg model row tight muted">
            <Loader2 size={16} className="spin" /> Working with Qloo…
          </div>
        )}
        <div ref={end} />
      </div>
      {err && <ErrorBox error={err} />}

      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          send(text);
        }}
      >
        <input type="text" className="grow" style={{ padding: "12px 14px", borderRadius: 999 }} placeholder="Ask about a resident, the lounge, or a one-to-one" value={text} onChange={(e) => setText(e.target.value)} aria-label="Message" />
        <button className="btn primary" disabled={busy}>
          <Send size={16} /> Send
        </button>
      </form>
    </div>
  );
}

function Evidence({ reply }: { reply: Reply }) {
  const plan = reply.cards.find((c) => c.kind === "plan");
  return (
    <div className="trace small">
      {reply.note && <span className="muted">{reply.note}</span>}
      {reply.trace.map((t, i) => (
        <details key={i}>
          <summary>
            <span className="row tight" style={{ display: "inline-flex" }}>
              <Wrench size={14} /> <b>{t.tool}</b>
              <span className="muted">
                ({Object.entries(t.args)
                  .filter(([, v]) => v !== null && v !== undefined && !(Array.isArray(v) && !v.length))
                  .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : v}`)
                  .join(" · ")}
                )
              </span>
              · {t.qloo.length} Qloo request{t.qloo.length === 1 ? "" : "s"}
              {t.qloo.filter((q) => q.cached).length ? `, ${t.qloo.filter((q) => q.cached).length} from cache` : ""}
              {!t.ok && <span className="chip warn">{t.error}</span>}
            </span>
          </summary>
          <div className="stack" style={{ gap: 6, marginTop: 6 }}>
            {t.qloo.map((q, j) => (
              <div key={j}>
                <span className="mono">GET {q.path}</span> <span className="muted">· {q.purpose}</span>
                <div>
                  {q.params.map(([k, v]) => (
                    <span key={k + v} className="param mono">
                      {k}={v.length > 60 ? v.slice(0, 60) + "…" : v}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </details>
      ))}
      {plan && (
        <Link className="btn sm" to={`/session/${plan.id as string}`} style={{ justifySelf: "start" }}>
          Open the session plan
        </Link>
      )}
    </div>
  );
}

/** Minimal, safe rendering of the agent's markdown: paragraphs, bullet lists, bold and italics. */
function Rich({ text }: { text: string }) {
  const blocks: { list: boolean; lines: string[] }[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trimEnd();
    const bullet = /^\s*[*-]\s+/.test(line);
    if (!line.trim()) {
      blocks.push({ list: false, lines: [] });
      continue;
    }
    const last = blocks[blocks.length - 1];
    if (last && last.list === bullet && last.lines.length) last.lines.push(line.replace(/^\s*[*-]\s+/, ""));
    else blocks.push({ list: bullet, lines: [line.replace(/^\s*[*-]\s+/, "")] });
  }
  const inline = (t: string) =>
    t.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).map((part, i) =>
      part.startsWith("**") ? <b key={i}>{part.slice(2, -2)}</b> : part.startsWith("*") && part.length > 2 ? <i key={i}>{part.slice(1, -1)}</i> : part,
    );
  return (
    <div className="stack" style={{ gap: 8, whiteSpace: "normal" }}>
      {blocks
        .filter((b) => b.lines.length)
        .map((b, i) =>
          b.list ? (
            <ul key={i} style={{ margin: 0, paddingLeft: 20 }}>
              {b.lines.map((l, j) => (
                <li key={j}>{inline(l)}</li>
              ))}
            </ul>
          ) : (
            <p key={i}>{b.lines.map((l, j) => (
              <span key={j}>{j > 0 && <br />}{inline(l)}</span>
            ))}</p>
          ),
        )}
    </div>
  );
}
