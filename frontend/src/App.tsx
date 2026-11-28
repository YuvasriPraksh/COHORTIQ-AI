import { useEffect, useState, type ReactElement } from "react";

import { useSession } from "./auth/session";
import { AdminAuditPage } from "./components/AdminAuditPage";
import { AdminChangeRadarPage } from "./components/AdminChangeRadarPage";
import { AdminUsersPage } from "./components/AdminUsersPage";
import { AskWorkspace } from "./components/AskWorkspace";
import { DashboardPage } from "./components/DashboardPage";
import { Icon, LogoMark, type IconName } from "./components/icons";
import { ImpactTwinPage } from "./components/ImpactTwinPage";
import { Notice } from "./components/Notice";
import { RegulationsPage } from "./components/RegulationsPage";
import { SignIn } from "./components/SignIn";
import { StoredRegulationsPage } from "./components/StoredRegulationsPage";
import { UpdatesPage } from "./components/UpdatesPage";
import { UploadRegulationsPage } from "./components/UploadRegulationsPage";
import { navigate, useHashPath } from "./nav/router";
import { AboutPage } from "./site/AboutPage";
import { FeaturesPage } from "./site/FeaturesPage";
import { HowItWorksPage } from "./site/HowItWorksPage";
import { LandingPage } from "./site/LandingPage";
import { PublicLayout, ThemeToggle } from "./site/PublicLayout";
import { HistoryProvider } from "./state/history";

function initialsFor(name: string | null, email: string): string {
  const source = (name || email).trim();
  const parts = source.split(/[\s.@]+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0]![0]}${parts[1]![0]}`.toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

interface NavItem {
  path: string;
  label: string;
  icon: IconName;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const ADMIN_NAV: NavGroup[] = [
  { label: "Overview", items: [{ path: "/dashboard", label: "Dashboard", icon: "grid" }, { path: "/", label: "Ask", icon: "message" }] },
  {
    label: "Regulations",
    items: [
      { path: "/admin/upload", label: "Upload Regulations", icon: "upload" },
      { path: "/admin/regulations", label: "Stored Regulations", icon: "files" },
      { path: "/admin/change-radar", label: "Change Radar", icon: "radar" },
    ],
  },
  {
    label: "Administration",
    items: [
      { path: "/admin/users", label: "Users", icon: "users" },
      { path: "/admin/audit", label: "Audit Log", icon: "activity" },
    ],
  },
];

const MEMBER_NAV: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { path: "/dashboard", label: "Dashboard", icon: "grid" },
      { path: "/", label: "Ask", icon: "message" },
      { path: "/impact-twin", label: "My Academic Impact Twin", icon: "target" },
      { path: "/regulations", label: "Regulations", icon: "book" },
      { path: "/updates", label: "Updates", icon: "bell" },
    ],
  },
];

const PUBLIC_PAGES: Record<string, () => ReactElement> = {
  "/features": () => <FeaturesPage />,
  "/how-it-works": () => <HowItWorksPage />,
  "/about": () => <AboutPage />,
};

export function App() {
  const { session, signOut } = useSession();
  const fullPath = useHashPath();
  const [path = "/", query = ""] = fullPath.split("?");
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => setDrawerOpen(false), [fullPath]);

  if (session.status === "restoring") {
    return (
      <div className="splash" role="status">
        <span className="splash__mark"><LogoMark size={52} /></span>
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
    const publicPage = PUBLIC_PAGES[path];
    return (
      <PublicLayout path={publicPage ? path : "/"}>
        {publicPage ? publicPage() : <LandingPage notice={session.notice} />}
      </PublicLayout>
    );
  }

  const { user, token } = session;
  const isAdmin = user.role === "administrator";
  const displayName = user.full_name || user.email;
  const roleLabel = isAdmin ? "Administrator" : user.role === "staff" ? "Staff / Teacher" : "Student";
  const groups = isAdmin ? ADMIN_NAV : MEMBER_NAV;
  const allItems = groups.flatMap((group) => group.items);
  const activeItem = allItems.find((item) => item.path === path) ?? allItems.find((item) => item.path === "/")!;
  const params = new URLSearchParams(query);

  function adminOnly(page: ReactElement) {
    return isAdmin ? page : <Notice tone="error" title="Administrator access required" />;
  }

  function renderPage() {
    switch (path) {
      case "/dashboard":
        return <DashboardPage token={token} user={user} />;
      case "/regulations":
        return isAdmin ? <StoredRegulationsPage token={token} /> : <RegulationsPage token={token} user={user} />;
      case "/impact-twin":
        return isAdmin ? <Notice tone="error" title="The Academic Impact Twin is for student and staff cohorts" /> : <ImpactTwinPage token={token} />;
      case "/updates":
        return isAdmin ? <Notice tone="error" title="This page is for student and staff cohort updates" /> : <UpdatesPage token={token} />;
      case "/admin/upload":
        return adminOnly(<UploadRegulationsPage token={token} />);
      case "/admin/regulations":
        return adminOnly(<StoredRegulationsPage token={token} />);
      case "/admin/change-radar":
        return adminOnly(<AdminChangeRadarPage token={token} initialNewId={params.get("new") ?? ""} />);
      case "/admin/users":
        return adminOnly(<AdminUsersPage token={token} currentUser={user} />);
      case "/admin/audit":
        return adminOnly(<AdminAuditPage token={token} />);
      default:
        return <AskWorkspace token={token} user={user} />;
    }
  }

  return (
    <HistoryProvider key={token}>
      <div className={`app${drawerOpen ? " app--drawer-open" : ""}`}>
        <a className="skip-link" href="#main-content" onClick={(event) => { event.preventDefault(); document.getElementById("main-content")?.focus(); }}>
          Skip to main content
        </a>
        <aside className="app-sidebar" aria-label="Application sidebar">
          <a
            href="#/"
            className="brand app-sidebar__brand"
            onClick={(event) => {
              event.preventDefault();
              navigate("/");
            }}
          >
            <LogoMark size={32} />
            <span className="brand__name">Cohort<span>IQ</span></span>
          </a>
          <nav className="app-nav" aria-label="Main navigation">
            {groups.map((group) => (
              <div className="app-nav__group" key={group.label}>
                <p className="app-nav__label">{group.label}</p>
                {group.items.map((item) => {
                  const active = item.path === activeItem.path;
                  return (
                    <a
                      key={item.path}
                      href={`#${item.path}`}
                      className={`app-nav__link${active ? " is-active" : ""}`}
                      aria-current={active ? "page" : undefined}
                      onClick={(event) => {
                        event.preventDefault();
                        navigate(item.path);
                      }}
                    >
                      <Icon name={item.icon} size={18} />
                      {item.label}
                    </a>
                  );
                })}
              </div>
            ))}
          </nav>
          {user.admission_batch && user.programme ? (
            <div className="app-sidebar__cohort">
              <span className="app-sidebar__cohort-label">{user.role === "staff" ? "Assigned cohort" : "Your cohort"}</span>
              <strong>Batch {user.admission_batch}</strong>
              <span>{user.programme}</span>
            </div>
          ) : null}
        </aside>
        <button type="button" className="app__scrim" aria-label="Close navigation" tabIndex={drawerOpen ? 0 : -1} onClick={() => setDrawerOpen(false)} />

        <div className="app__content">
          <header className="app-topbar">
            <button
              type="button"
              className="icon-button app-topbar__menu"
              aria-label={drawerOpen ? "Close navigation" : "Open navigation"}
              aria-expanded={drawerOpen}
              onClick={() => setDrawerOpen((value) => !value)}
            >
              <Icon name={drawerOpen ? "close" : "menu"} />
            </button>
            <p className="app-topbar__context">
              <Icon name={activeItem.icon} size={16} />
              {activeItem.label}
            </p>
            <div className="app-topbar__user">
              <ThemeToggle />
              <span className="app-topbar__avatar" aria-hidden="true" title={displayName}>
                {initialsFor(user.full_name, user.email)}
              </span>
              <span className="app-topbar__name">
                <span className="app-topbar__display">{displayName}</span>
                <span className={`role-chip role-chip--${user.role}`}>{roleLabel}</span>
              </span>
              <button type="button" className="button button--ghost button--compact" onClick={() => signOut()}>
                <Icon name="logout" size={16} />
                Sign out
              </button>
            </div>
          </header>
          <main id="main-content" className="app-main page-enter" key={path} tabIndex={-1}>
            {renderPage()}
          </main>
          <footer className="app-footer">
            Answers are generated from approved regulations and may be incomplete. Check the cited pages before relying on them.
          </footer>
        </div>
      </div>
    </HistoryProvider>
  );
}
