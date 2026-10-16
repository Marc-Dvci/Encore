import { Link } from "react-router-dom";
import { UserPlus } from "lucide-react";
import type { Home } from "../api";
import { Avatar, ErrorBox, Loading, useFetch } from "../ui";

export default function Residents() {
  const { data, error, reload } = useFetch<Home>("/api/home");
  return (
    <div className="stack lg">
      <div className="stack" style={{ gap: 6 }}>
        <span className="eyebrow">Maple Court</span>
        <h1>Residents and carers</h1>
        <p className="ink2" style={{ maxWidth: 760 }}>
          Each profile starts from three things a family can tell you in a minute: the year, the hometown and a few
          favourites. Encore does the rest with Qloo.
        </p>
        <Link className="btn primary" style={{ alignSelf: "flex-start", marginTop: 6 }} to="/add">
          <UserPlus size={16} /> Try it with someone in your family
        </Link>
      </div>
      {error && <ErrorBox error={error} retry={reload} />}
      {!data && !error && <Loading label="Loading the home…" />}
      {data && (
        <>
          {data.residents.some((r) => r.guest) && (
            <section className="stack">
              <h2>You added</h2>
              <div className="people">
                {data.residents.filter((r) => r.guest).map((r) => (
                  <Link key={r.id} to={`/residents/${r.id}`} className="person">
                    <Avatar name={r.first_name} id={r.id} />
                    <div className="grow">
                      <b>{r.first_name}</b>
                      <div className="small muted">
                        Born {r.birth_year} · {r.city}
                      </div>
                      <div className="tiny ink2" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {r.favourites.join(" · ")}
                      </div>
                    </div>
                    {r.needs_input > 0 && <span className="chip warn">1 to confirm</span>}
                  </Link>
                ))}
              </div>
            </section>
          )}
          <section className="stack">
            <h2>Residents</h2>
            <div className="people">
              {data.residents.filter((r) => !r.guest).map((r) => (
                <Link key={r.id} to={`/residents/${r.id}`} className="person">
                  <Avatar name={r.first_name} id={r.id} off={!r.present} />
                  <div className="grow">
                    <b>
                      {r.first_name} {r.last_initial}.
                    </b>
                    <div className="small muted">
                      Born {r.birth_year} · {r.city}
                    </div>
                    <div className="tiny ink2" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {r.favourites.join(" · ")}
                    </div>
                  </div>
                  {r.needs_input > 0 && <span className="chip warn">1 to confirm</span>}
                </Link>
              ))}
            </div>
          </section>
          <section className="stack">
            <h2>Carers</h2>
            <div className="people">
              {data.carers.map((c) => (
                <div key={c.id} className="person">
                  <Avatar name={c.first_name} id={c.id} />
                  <div className="grow">
                    <b>{c.first_name}</b>
                    <div className="small muted">
                      Born {c.birth_year} · {c.city}, {c.country}
                    </div>
                    <div className="tiny ink2">{c.favourites.join(" · ")}</div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
