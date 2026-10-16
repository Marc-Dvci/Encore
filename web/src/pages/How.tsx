import { Link } from "react-router-dom";
import { Section, useFetch } from "../ui";

interface EvalRow {
  metric: string;
  encore: string;
  llm_only: string;
  note: string;
}
interface Eval {
  available?: boolean;
  generated_at?: string;
  model?: string;
  residents?: number;
  rows?: EvalRow[];
  group?: { rule: string; film: string; year: number | null; min_fit: number; least_served: string; mean_fit: number }[];
  music_ablation?: { lane: string; in_window: number; total: number }[];
}

const FLOW = [
  ["Family", "Birth year, hometown and up to three favourites, typed in a minute on the family form. No name is asked."],
  ["Qloo Search", "Matches each favourite to one entity. When a title has several releases, Encore keeps the one from the resident’s youth; anything ambiguous goes to staff."],
  ["Qloo Insights", "Two lanes per domain: the family’s favourites, and home (country of release, or the home country’s music genre). Films, TV and books are filtered to the years the resident was 10 to 30."],
  ["Encore code", "Checks each artist’s active years against that window, weights by age, interleaves the lanes and removes anything on an avoid list."],
  ["Lounge", "Qloo ranks one shared shortlist for every resident (filter.results.entities). Code picks the film whose least-served resident is served best."],
  ["The week", "Encore tries every pair of shortlist films and keeps the pair whose least-served resident’s better film fits best. Qloo Compare on every resident and carer pair scores the tastes they share, and each carer gets an even share of one-to-ones, strongest matches first."],
  ["One-to-one", "Qloo Compare and explainability find what a resident and their carer share. Insights on places finds the food of home near the care home."],
  ["Gemini", "Writes the words the carer says. It never chooses an item or a number."],
  ["Session", "A carer taps how the resident responded. A song that lit them up becomes a signal in the next Qloo query; anything that upset them is excluded."],
];

export default function How() {
  const { data } = useFetch<Eval>("/api/eval");
  return (
    <div className="stack lg" style={{ maxWidth: 980 }}>
      <div className="stack" style={{ gap: 8 }}>
        <span className="eyebrow">How it works</span>
        <h1>A taste agent for care-home activity coordinators</h1>
        <p className="ink2">
          An activities coordinator in a care home runs sessions for dozens of residents who grew up in different decades
          and countries, with carers who often grew up decades later and somewhere else. Families can name a song or two.
          Encore turns that into the culture of each resident’s youth, a one-to-one session a carer can run in ten
          minutes, and a lounge film that leaves nobody out.
        </p>
        <p className="ink2">
          US nursing homes must run an activities programme built on each resident’s interests and preferences
          (42 CFR 483.24(c), survey tag F679). Encore produces that programme and its record. See an{" "}
          <Link to="/record/r-tomasz">example record</Link>, the <Link to="/week">week’s plan</Link>, or{" "}
          <Link to="/add">try it with someone in your family</Link>.
        </p>
      </div>

      <Section title="From three favourites to a session">
        <ol className="stack" style={{ margin: 0, paddingLeft: 0, listStyle: "none", gap: 10 }}>
          {FLOW.map(([h, t], i) => (
            <li key={h} className="row" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
              <span className="chip solid" style={{ minWidth: 30, justifyContent: "center" }}>
                {i + 1}
              </span>
              <span>
                <b>{h}.</b> {t}
              </span>
            </li>
          ))}
        </ol>
        <p className="small ink2" style={{ marginTop: 12 }}>
          Every pick, rank and number on screen comes from Qloo and Encore’s code. The model writes words. Each request
          Encore sends to Qloo is listed on <Link to="/qloo">What Qloo saw</Link>.
        </p>
      </Section>

      <Section title="Encore against a model on its own" aside={data?.generated_at ? <span className="small muted">Run {data.generated_at.slice(0, 10)} on {data.residents} residents</span> : undefined}>
        {data?.rows ? (
          <>
            <p className="small ink2" style={{ marginBottom: 10 }}>
              The same model ({data.model}) was given each resident’s birth year, hometown and family favourites and asked
              for the singers and films of their youth. Every answer was then looked up in Qloo and scored by code.
            </p>
            <div className="table-wrap">
              <table className="plain">
                <thead>
                  <tr>
                    <th>Measure</th>
                    <th>Encore</th>
                    <th>Model alone</th>
                    <th>How it was measured</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.metric}>
                      <td>
                        <b>{r.metric}</b>
                      </td>
                      <td>{r.encore}</td>
                      <td>{r.llm_only}</td>
                      <td className="small ink2">{r.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.group && (
              <>
                <h3 style={{ margin: "18px 0 8px" }}>The lounge film, four ways</h3>
                <table className="plain">
                  <thead>
                    <tr>
                      <th>Rule</th>
                      <th>Film</th>
                      <th>Least-served fit</th>
                      <th>Average fit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.group.map((g) => (
                      <tr key={g.rule}>
                        <td>{g.rule}</td>
                        <td>
                          {g.film} {g.year ? `(${g.year})` : ""}
                        </td>
                        <td>
                          {g.min_fit.toFixed(2)} <span className="muted small">({g.least_served})</span>
                        </td>
                        <td>{g.mean_fit.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
            {data.music_ablation && (
              <>
                <h3 style={{ margin: "18px 0 8px" }}>Why the music lanes look the way they do</h3>
                <table className="plain">
                  <thead>
                    <tr>
                      <th>Qloo request for artists, seeded by the family’s favourites</th>
                      <th>Artists active in the resident’s ages 10 to 30</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.music_ablation.map((m) => (
                      <tr key={m.lane}>
                        <td>{m.lane}</td>
                        <td>
                          {m.in_window} of {m.total} ({Math.round((m.in_window / Math.max(1, m.total)) * 100)}%)
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </>
        ) : (
          <p className="muted">The evaluation has not been run on this server yet.</p>
        )}
      </Section>

      <Section title="Data and limits">
        <ul className="stack" style={{ margin: 0, gap: 8 }}>
          <li>Residents, carers and the home are fictional. Song, film and place data come from Qloo.</li>
          <li>Qloo receives entity IDs, years, a hometown, genre words and an age bracket. Names, rooms and notes stay in Encore.</li>
          <li>Qloo affinity describes audiences. Encore uses it to order and compare, and never shows it as a prediction about one person.</li>
          <li>Coverage follows Qloo’s catalogue: Polish, Mexican and Italian music of the 1950s is rich; Korean music of the same years is thin, so Min-ja’s shelf leans on films.</li>
          <li>Notable songs are listed per artist; a song can be later than the artist’s start year.</li>
        </ul>
      </Section>
    </div>
  );
}
