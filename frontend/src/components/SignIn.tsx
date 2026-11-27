import { useId, useState, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { register } from "../api/cohortiq";
import {
  ADMINISTRATOR_EMAIL_DOMAIN,
  STAFF_EMAIL_DOMAIN,
  STUDENT_EMAIL_DOMAIN,
  type AccountRole,
} from "../api/types";
import { useSession } from "../auth/session";
import { navigate } from "../nav/router";
import { CohortPicker, useCohorts } from "./CohortPicker";
import { Notice } from "./Notice";

type Mode = "signin" | "register";

const PASSWORD_RULE =
  "At least 12 characters using three of: lowercase, uppercase, digits, symbols (or a 20+ character passphrase).";

function PasswordField({
  value,
  onChange,
  autoComplete,
  describedBy,
}: {
  value: string;
  onChange: (value: string) => void;
  autoComplete: "current-password" | "new-password";
  describedBy?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <label className="field">
      <span>Password</span>
      <span className="field__password">
        <input
          type={show ? "text" : "password"}
          autoComplete={autoComplete}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required
          maxLength={256}
          aria-describedby={describedBy}
        />
        <button type="button" className="field__toggle" onClick={() => setShow((v) => !v)} aria-pressed={show}>
          {show ? "Hide" : "Show"}
        </button>
      </span>
    </label>
  );
}

const roleTitles: Record<AccountRole, string> = {
  student: "Student",
  staff: "Staff / Teacher",
  administrator: "Administrator",
};

export function SignIn({
  initialRole,
  initialMode = "signin",
  notice,
}: {
  initialRole: AccountRole | null;
  initialMode?: Mode;
  notice: string | null;
}) {
  const { signIn } = useSession();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [selectedRole, setSelectedRole] = useState<AccountRole | null>(initialRole);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [batch, setBatch] = useState("");
  const [programme, setProgramme] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState(false);
  const ruleId = useId();
  const emailHintId = useId();

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setDuplicate(false);
    setPassword("");
  }

  function chooseRole(next: AccountRole) {
    setSelectedRole(next);
    switchMode("signin");
  }

  async function onSignIn(event: FormEvent) {
    event.preventDefault();
    if (!selectedRole) {
      setError("Choose your account type before signing in.");
      return;
    }
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await signIn(email.trim(), password, selectedRole);
      navigate("/");
    } catch (caught) {
      // The API returns the same message for every failed sign-in; we show it as is.
      setError(caught instanceof ApiError ? caught.message : "Sign-in failed. Please try again.");
      setSubmitting(false);
    }
  }

  async function onRegister(event: FormEvent) {
    event.preventDefault();
    if (selectedRole !== "student") {
      setError("Public registration is available for students only.");
      return;
    }
    const address = email.trim().toLowerCase();
    if (!address || !password || !batch.trim() || !programme.trim()) {
      setError("Enter your college email, a password, your admission batch and your programme.");
      return;
    }
    if (address.split("@")[1] !== STUDENT_EMAIL_DOMAIN) {
      setError(`Use your student email address ending in @${STUDENT_EMAIL_DOMAIN}.`);
      return;
    }
    setSubmitting(true);
    setError(null);
    setDuplicate(false);
    try {
      await register({
        email: address,
        password,
        admission_batch: batch.trim(),
        programme: programme.trim(),
        ...(fullName.trim() ? { full_name: fullName.trim() } : {}),
      });
    } catch (caught) {
      setDuplicate(caught instanceof ApiError && caught.status === 409);
      setError(caught instanceof ApiError ? caught.message : "Registration failed. Please try again.");
      setSubmitting(false);
      return;
    }
    try {
      await signIn(address, password, "student");
      navigate("/");
    } catch (caught) {
      // The account exists; only the automatic sign-in failed.
      setMode("signin");
      setPassword("");
      setError(
        `Your account was created, but signing in failed: ${
          caught instanceof ApiError ? caught.message : "please try again."
        }`,
      );
      setSubmitting(false);
    }
  }

  const registering = mode === "register" && selectedRole === "student";
  const cohortResource = useCohorts(registering);

  return (
    <main className="signin">
      <section className="signin__intro">
        <a className="brand brand--large brand--link" href="#/" onClick={(event) => { event.preventDefault(); navigate("/"); }}>
          <span className="brand__mark" aria-hidden="true" />
          CohortIQ
        </a>
        <p className="signin__tagline">Academic guidance grounded in the regulations that apply to you.</p>
        <ul className="signin__points">
          <li>Answers from the regulations that apply to your batch</li>
          <li>Every answer shows the pages it relies on</li>
          <li>Says so plainly when the regulations don't cover it</li>
        </ul>
      </section>

      <section className="panel signin__card" aria-labelledby="signin-heading">
        <h1 id="signin-heading" className="signin__title">
          {registering ? "Create student account" : "Sign in"}
        </h1>
        <p className="signin__subtitle">
          {registering
            ? `Register with your institutional student email (@${STUDENT_EMAIL_DOMAIN}).`
            : selectedRole
              ? `Continue as ${roleTitles[selectedRole]}. Sign in with your registered account${
                  selectedRole === "student" ? "." : ` (@${selectedRole === "staff" ? STAFF_EMAIL_DOMAIN : ADMINISTRATOR_EMAIL_DOMAIN}).`
                }`
              : "Choose the account type associated with your registered account."}
        </p>
        {selectedRole ? (
          <div className={`selected-role selected-role--${selectedRole}`}>
            <span className="selected-role__label">Selected role</span>
            <strong>{roleTitles[selectedRole]}</strong>
            <button type="button" className="link-button" onClick={() => navigate("/")}>Change role</button>
          </div>
        ) : (
          <fieldset className="role-picker">
            <legend>Choose your account type</legend>
            {(["student", "staff", "administrator"] as const).map((role) => (
              <label key={role}>
                <input type="radio" name="account-role" value={role} checked={selectedRole === role} onChange={() => chooseRole(role)} />
                {roleTitles[role]}
              </label>
            ))}
          </fieldset>
        )}
        {notice && !registering ? <Notice title={notice} /> : null}
        {selectedRole && selectedRole !== "student" ? (
          <Notice
            tone="info"
            title={selectedRole === "staff" ? `Staff accounts (@${STAFF_EMAIL_DOMAIN}) are provisioned by an administrator.` : `Administrator accounts (@${ADMINISTRATOR_EMAIL_DOMAIN}) are securely provisioned; public sign-up is unavailable.`}
          />
        ) : null}
        {error ? (
          <Notice
            tone="error"
            title={error}
            action={
              duplicate ? (
                <button type="button" className="button button--ghost" onClick={() => switchMode("signin")}>
                  Go to sign in
                </button>
              ) : undefined
            }
          />
        ) : null}

        {registering ? (
          <form onSubmit={onRegister} className="form" noValidate>
            <label className="field">
              <span>Full name (optional)</span>
              <input autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={200} />
            </label>
            <label className="field">
              <span>Student email</span>
              <input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={`name@${STUDENT_EMAIL_DOMAIN}`}
                required
                maxLength={254}
                aria-describedby={emailHintId}
              />
            </label>
            <p id={emailHintId} className="field__hint">
              Must end in @{STUDENT_EMAIL_DOMAIN}.
            </p>
            <PasswordField value={password} onChange={setPassword} autoComplete="new-password" describedBy={ruleId} />
            <p id={ruleId} className="field__hint">
              {PASSWORD_RULE}
            </p>
            <CohortPicker
              cohorts={cohortResource.cohorts}
              loading={cohortResource.loading}
              error={cohortResource.error}
              onRetry={cohortResource.reload}
              batch={batch}
              programme={programme}
              onChange={(nextBatch, nextProgramme) => {
                setBatch(nextBatch);
                setProgramme(nextProgramme);
              }}
            />
            <p className="field__hint">
              Enter your batch and programme exactly as your college lists them; they decide which regulations apply.
            </p>
            <button type="submit" className="button button--primary button--wide" disabled={submitting}>
              {submitting ? <span className="spinner" aria-hidden="true" /> : null}
              {submitting ? "Creating account…" : "Create account"}
            </button>
          </form>
        ) : (
          <form onSubmit={onSignIn} className="form" noValidate>
            <label className="field">
              <span>Email</span>
              <input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                maxLength={254}
              />
            </label>
            <PasswordField value={password} onChange={setPassword} autoComplete="current-password" />
            <button type="submit" className="button button--primary button--wide" disabled={submitting}>
              {submitting ? <span className="spinner" aria-hidden="true" /> : null}
              {submitting ? "Signing in…" : "Sign in"}
            </button>
          </form>
        )}

        {selectedRole === "student" ? (
          <p className="signin__switch">
            {registering ? "Already have an account?" : "New to CohortIQ?"}{" "}
            <button type="button" className="link-button" onClick={() => switchMode(registering ? "signin" : "register")}>
              {registering ? "Sign in" : "Create an account"}
            </button>
          </p>
        ) : null}
        <p className="signin__switch"><a href="#/" onClick={(event) => { event.preventDefault(); navigate("/"); }}>Back to role selection</a></p>
      </section>
    </main>
  );
}
