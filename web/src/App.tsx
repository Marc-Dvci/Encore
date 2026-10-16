import { NavLink, Route, Routes, Link } from "react-router-dom";
import { Music2, Sun, Users, Clapperboard, MessageCircle, Eye, Info } from "lucide-react";
import Today from "./pages/Today";
import Residents from "./pages/Residents";
import Resident from "./pages/Resident";
import Session from "./pages/Session";
import Lounge from "./pages/Lounge";
import Ask from "./pages/Ask";
import Record from "./pages/Record";
import QlooLog from "./pages/QlooLog";
import How from "./pages/How";
import { useFetch } from "./ui";

interface Status {
  qloo: string;
  model_live: boolean;
  warm: { done: number; total: number; running: boolean };
}

export default function App() {
  const { data: status } = useFetch<Status>("/api/status");
  return (
    <>
      <a href="#main" className="sr">
        Skip to content
      </a>
      <header className="top">
        <div className="top-inner">
          <Link to="/" className="brand" aria-label="Encore, today">
            <span className="brand-mark">
              <Music2 size={20} />
            </span>
            <span>
              <span className="brand-name">Encore</span>
              <div className="brand-home">Maple Court · Evanston</div>
            </span>
          </Link>
          <nav className="nav" aria-label="Main">
            <NavLink to="/" end>
              <Sun size={16} /> Today
            </NavLink>
            <NavLink to="/residents">
              <Users size={16} /> Residents
            </NavLink>
            <NavLink to="/lounge">
              <Clapperboard size={16} /> Lounge
            </NavLink>
            <NavLink to="/ask">
              <MessageCircle size={16} /> Ask Encore
            </NavLink>
            <NavLink to="/qloo">
              <Eye size={16} /> What Qloo saw
            </NavLink>
            <NavLink to="/how">
              <Info size={16} /> How it works
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="page" id="main">
        <Routes>
          <Route path="/" element={<Today />} />
          <Route path="/residents" element={<Residents />} />
          <Route path="/residents/:id" element={<Resident />} />
          <Route path="/session/:id" element={<Session />} />
          <Route path="/lounge" element={<Lounge />} />
          <Route path="/ask" element={<Ask />} />
          <Route path="/record/:id" element={<Record />} />
          <Route path="/qloo" element={<QlooLog />} />
          <Route path="/how" element={<How />} />
          <Route path="*" element={<p>That page does not exist. <Link to="/">Back to today</Link></p>} />
        </Routes>
      </main>
      <footer className="foot">
        <span>
          Encore is a demonstration with fictional residents. Taste data from Qloo; words written by Gemini; every
          pick and number computed by Encore.
        </span>
        <span className="row tight">
          <span className="chip">
            <i className="dot" style={{ background: status?.qloo === "live" ? "var(--good)" : "var(--warn)" }} /> Qloo{" "}
            {status?.qloo ?? "…"}
          </span>
          <span className="chip">
            <i className="dot" style={{ background: status?.model_live ? "var(--good)" : "var(--warn)" }} /> Model{" "}
            {status ? (status.model_live ? "live" : "templates") : "…"}
          </span>
        </span>
      </footer>
    </>
  );
}
