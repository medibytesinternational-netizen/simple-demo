import { useEffect } from "react";
import { Link, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { PipelinePage } from "./pages/Pipeline";
import { UnsupportedHimsPage } from "./pages/UnsupportedHims";
import shell from "./SimpleShell.module.css";

function SiteShell() {
  const location = useLocation();
  const pipelineActive = location.pathname === "/pipeline" || location.pathname === "/";
  const himsActive = location.pathname.startsWith("/hims");

  useEffect(() => {
    document.title = `${himsActive ? "HIMS capabilities" : "Dictation pipeline"} · MediBytes`;
  }, [himsActive]);

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <div className="app-main">
        <header className="topbar glass">
          <Link to="/pipeline" className="topbar-brand" aria-label="MediBytes home">
            <span className="brand-mark" aria-hidden="true">MB</span>
            <span className="brand-text">
              <span className="brand-name">MediBytes</span>
              <span className="brand-sub">Dictation to discharge note</span>
            </span>
          </Link>
          <div className="breadcrumbs" aria-label="Current section">
            <span className="crumb-current">{himsActive ? "HIMS capabilities" : "Processing workspace"}</span>
          </div>
          <div className="topbar-right">
            <span className="env-pill"><span className="env-dot" />Product pipeline</span>
          </div>
        </header>

        <nav className={shell.nav} aria-label="Main navigation">
          <Link to="/pipeline" className={`${shell.navLink} ${pipelineActive ? shell.active : ""}`} aria-current={pipelineActive ? "page" : undefined}>
            Dictation pipeline
          </Link>
          <Link to="/hims/capabilities" className={`${shell.navLink} ${himsActive ? shell.active : ""}`} aria-current={himsActive ? "page" : undefined}>
            HIMS modules
          </Link>
          <span className={shell.navNote}>One active backend: MediBytes</span>
        </nav>

        <main className="content-scroll" id="main-content" tabIndex={-1}>
          <div className="content"><Outlet /></div>
        </main>
        <footer className={shell.footer}>
          <span>MediBytes processing workspace</span>
          <span>Audio processing · verification · discharge note</span>
        </footer>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<SiteShell />}>
        <Route index element={<Navigate to="/pipeline" replace />} />
        <Route path="pipeline" element={<PipelinePage />} />
        <Route path="hims/*" element={<UnsupportedHimsPage />} />
        <Route path="*" element={<Navigate to="/pipeline" replace />} />
      </Route>
    </Routes>
  );
}
