import { useSession } from "./auth/session";
import { AskWorkspace } from "./components/AskWorkspace";
import { SignIn } from "./components/SignIn";

export function App() {
  const { session, signOut } = useSession();

  if (session.status === "restoring") {
    return (
      <div className="splash" role="status">
        <span className="brand__mark brand__mark--pulse" aria-hidden="true" />
        <span className="visually-hidden">Loading CohortIQ…</span>
      </div>
    );
  }

  if (session.status === "signed_out") {
    return <SignIn notice={session.notice} />;
  }

  const { user, token } = session;
  return (
    <div className="shell">
      <header className="topbar">
        <p className="brand">
          <span className="brand__mark" aria-hidden="true" />
          CohortIQ
        </p>
        <div className="topbar__user">
          <span className="topbar__name">
            {user.full_name || user.email}
            {user.role === "administrator" ? <span className="chip chip--small">Administrator</span> : null}
          </span>
          <button type="button" className="button button--ghost" onClick={() => signOut()}>
            Sign out
          </button>
        </div>
      </header>
      <main className="main">
        <AskWorkspace token={token} user={user} />
      </main>
      <footer className="footer">
        Answers are generated from approved regulations and may be incomplete. Check the cited pages before relying on
        them.
      </footer>
    </div>
  );
}
