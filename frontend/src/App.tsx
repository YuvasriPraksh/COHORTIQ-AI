import { useSession } from "./auth/session";
import { AdminAuditPage } from "./components/AdminAuditPage";
import { AdminUsersPage } from "./components/AdminUsersPage";
import { AskWorkspace } from "./components/AskWorkspace";
import { AdminChangeRadarPage } from "./components/AdminChangeRadarPage";
import { ModulesPage } from "./components/ModulesPage";
import { Notice } from "./components/Notice";
import { RegulationsPage } from "./components/RegulationsPage";
import { UpdatesPage } from "./components/UpdatesPage";
import { SignIn } from "./components/SignIn";
import { Welcome } from "./components/Welcome";
import { navigate, useHashPath } from "./nav/router";
import { HistoryProvider } from "./state/history";

function initialsFor(name: string | null, email: string): string {
  const source = (name || email).trim();
  const parts = source.split(/[\s.@]+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0]![0]}${parts[1]![0]}`.toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

export function App() {
  const { session, signOut } = useSession();
  const path = useHashPath();

  if (session.status === "restoring") {
    return (
      <div className="splash" role="status">
        <span className="brand__mark brand__mark--pulse" aria-hidden="true" />
        <span className="visually-hidden">Loading CohortIQ…</span>
      </div>
    );
  }

  if (session.status === "signed_out") {
    const roleFromPath = path.match(/^\/auth\/(student|staff|administrator)$/)?.[1];
    if (path === "/signup") {
      return <SignIn key="signup" initialRole="student" initialMode="register" notice={session.notice} />;
    }
    if (roleFromPath === "student" || roleFromPath === "staff" || roleFromPath === "administrator") {
      return <SignIn key={roleFromPath} initialRole={roleFromPath} notice={session.notice} />;
    }
    if (path === "/signin") return <SignIn key="signin" initialRole={null} notice={session.notice} />;
    return <Welcome notice={session.notice} />;
  }

  const { user, token } = session;
  const isAdmin = user.role === "administrator";
  const displayName = user.full_name || user.email;
  const roleLabel = user.role === "administrator" ? "Administrator" : user.role === "staff" ? "Staff / Teacher" : "Student";

  const navItems = [
    { path: "/", label: "Ask" },
    { path: "/regulations", label: "Regulations" },
    ...(isAdmin ? [{ path: "/admin/change-radar", label: "Change Radar" }] : [{ path: "/updates", label: "Updates" }]),
    { path: "/modules", label: "Modules" },
    ...(isAdmin
      ? [
          { path: "/admin/users", label: "Users" },
          { path: "/admin/audit", label: "Audit Log" },
        ]
      : []),
  ];

  function renderPage() {
    if (path === "/regulations") return <RegulationsPage token={token} user={user} />;
    if (path === "/admin/change-radar") {
      if (!isAdmin) return <Notice tone="error" title="Administrator access required" />;
      return <AdminChangeRadarPage token={token} />;
    }
    if (path === "/updates") {
      if (isAdmin) return <Notice tone="error" title="This page is for student and staff cohort updates" />;
      return <UpdatesPage token={token} />;
    }
    if (path === "/modules") return <ModulesPage isAdmin={isAdmin} />;
    if (path === "/admin/users") {
      if (!isAdmin) {
        return <Notice tone="error" title="Administrator access required" />;
      }
      return <AdminUsersPage token={token} currentUser={user} />;
    }
    if (path === "/admin/audit") {
      if (!isAdmin) {
        return <Notice tone="error" title="Administrator access required" />;
      }
      return <AdminAuditPage token={token} />;
    }
    return <AskWorkspace token={token} user={user} />;
  }

  return (
    <HistoryProvider key={token}>
      <div className="shell shell--app">
        <a className="skip-link" href="#main-content">
          Skip to main content
        </a>
        <aside className="sidebar" aria-label="Application sidebar">
          <a
            href="#/"
            className="brand brand--link sidebar__brand"
            onClick={(event) => {
              event.preventDefault();
              navigate("/");
            }}
          >
            <span className="brand__mark" aria-hidden="true" />
            CohortIQ
          </a>
          <p className="sidebar__section-label">Workspace</p>
          <nav className="nav" aria-label="Main navigation">
            {navItems.map((item) => {
              const active = path === item.path || (item.path === "/" && !navItems.some((n) => n.path === path));
              return (
                <a
                  key={item.path}
                  href={`#${item.path}`}
                  className={`nav__link${active ? " nav__link--active" : ""}`}
                  aria-current={active ? "page" : undefined}
                  onClick={(event) => {
                    event.preventDefault();
                    navigate(item.path);
                  }}
                >
                  {item.label}
                </a>
              );
            })}
          </nav>
          {user.admission_batch && user.programme ? (
            <div className="sidebar__cohort">
              <span className="sidebar__section-label">Your cohort</span>
              <strong>Batch {user.admission_batch}</strong>
              <span>{user.programme}</span>
            </div>
          ) : null}
        </aside>
        <div className="shell__content">
          <header className="topbar">
            <p className="topbar__context">{isAdmin ? "Administration" : user.role === "staff" ? "Staff workspace" : "Academic regulations"}</p>
            <div className="topbar__user">
              <span className="topbar__avatar" aria-hidden="true" title={displayName}>
                {initialsFor(user.full_name, user.email)}
              </span>
              <span className="topbar__name">
                <span>{displayName}</span>
                <span className="chip chip--small">{roleLabel}</span>
              </span>
              <button type="button" className="button button--ghost button--compact" onClick={() => signOut()}>
                Sign out
              </button>
            </div>
          </header>
          <main id="main-content" className="main" tabIndex={-1}>
            {renderPage()}
          </main>
          <footer className="footer">
            Answers are generated from approved regulations and may be incomplete. Check the cited pages before relying
            on them.
          </footer>
        </div>
      </div>
    </HistoryProvider>
  );
}
