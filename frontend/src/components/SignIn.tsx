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
import { Brand, ThemeToggle } from "../site/PublicLayout";
import { CohortPicker, useCohorts } from "./CohortPicker";
import { Icon, type IconName } from "./icons";
import { Notice } from "./Notice";

type Mode = "signin" | "register";
type RegisterTab = "student" | "staff";

const PASSWORD_RULE =
  "At least 12 characters using three of: lowercase, uppercase, digits, symbols (or a 20+ character passphrase).";

const ROLES: { role: AccountRole; title: string; icon: IconName; domain: string }[] = [
  { role: "student", title: "Student", icon: "graduation", domain: STUDENT_EMAIL_DOMAIN },
  { role: "staff", title: "Staff / Teacher", icon: "userCheck", domain: STAFF_EMAIL_DOMAIN },
  { role: "administrator", title: "Administrator", icon: "shield", domain: ADMINISTRATOR_EMAIL_DOMAIN },
];

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

const ASIDE: Record<Mode, { title: string; points: { icon: IconName; text: string }[] }> = {
  signin: {
    title: "Welcome back.",
    points: [
      { icon: "target", text: "Your workspace opens with the cohort stored on your account." },
      { icon: "shield", text: "Your account's role — not this form — decides what you can open." },
      { icon: "clock", text: "Sessions end automatically when your sign-in expires." },
    ],
  },
  register: {
    title: "Start asking in a minute.",
    points: [
      { icon: "graduation", text: "Register with your institutional student email." },
      { icon: "layers", text: "Choose the batch and programme your college lists for you." },
      { icon: "pages", text: "Ask a question and check the cited page." },
    ],
  },
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
  const [registerTab, setRegisterTab] = useState<RegisterTab>("student");
  const [selectedRole, setSelectedRole] = useState<AccountRole>(initialRole ?? "student");
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

  function switchMode(next: Mode, role?: AccountRole) {
    setMode(next);
    if (role) setSelectedRole(role);
    setError(null);
    setDuplicate(false);
    setPassword("");
  }

  async function onSignIn(event: FormEvent) {
    event.preventDefault();
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
      setSelectedRole("student");
      setPassword("");
      setError(
        `Your account was created, but signing in failed: ${
          caught instanceof ApiError ? caught.message : "please try again."
        }`,
      );
      setSubmitting(false);
    }
  }

  const registeringStudent = mode === "register" && registerTab === "student";
  const cohortResource = useCohorts(registeringStudent);
  const aside = ASIDE[mode];
  const roleInfo = ROLES.find((item) => item.role === selectedRole)!;

  return (
    <div className="auth">
      <header className="auth__top">
        <Brand />
        <div className="auth__top-actions">
          <ThemeToggle />
          <a className="button button--ghost button--compact" href="#/">
            Back to home
          </a>
        </div>
      </header>

      <div className="auth__layout">
        <aside className="auth__aside" aria-hidden="true">
          <div className="auth__aside-glow" />
          <p className="eyebrow eyebrow--light">CohortIQ</p>
          <h2>{aside.title}</h2>
          <ul>
            {aside.points.map((point) => (
              <li key={point.text}>
                <span><Icon name={point.icon} size={18} /></span>
                {point.text}
              </li>
            ))}
          </ul>
          <div className="auth__aside-card">
            <span className="pill pill--good"><Icon name="checkCircle" size={13} /> Grounded answer</span>
            <p>“Attendance of 95% and above earns the full 5 marks.”</p>
            <small>R2023 · Page 15</small>
          </div>
        </aside>

        <main className="auth__card panel" aria-labelledby="auth-heading">
          {mode === "register" ? (
            <>
              <h1 id="auth-heading" className="auth__title">
                {registeringStudent ? "Create student account" : "Staff / Teacher accounts"}
              </h1>
              <div className="segmented" role="tablist" aria-label="Account type to register">
                {(["student", "staff"] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    role="tab"
                    aria-selected={registerTab === tab}
                    className={`segmented__option${registerTab === tab ? " is-active" : ""}`}
                    onClick={() => {
                      setRegisterTab(tab);
                      setError(null);
                    }}
                  >
                    <Icon name={tab === "student" ? "graduation" : "userCheck"} size={16} />
                    {tab === "student" ? "Student" : "Staff / Teacher"}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <>
              <h1 id="auth-heading" className="auth__title">Sign in</h1>
              <p className="auth__subtitle">Choose your account type, then sign in with your registered email.</p>
              <fieldset className="role-select">
                <legend className="visually-hidden">Account type</legend>
                {ROLES.map((item) => (
                  <label key={item.role} className={`role-select__option${selectedRole === item.role ? " is-active" : ""}`}>
                    <input
                      type="radio"
                      name="account-role"
                      value={item.role}
                      checked={selectedRole === item.role}
                      onChange={() => {
                        setSelectedRole(item.role);
                        setError(null);
                      }}
                    />
                    <Icon name={item.icon} size={18} />
                    <span>{item.title}</span>
                  </label>
                ))}
              </fieldset>
            </>
          )}

          {notice && mode === "signin" ? <Notice title={notice} /> : null}
          {error ? (
            <Notice
              tone="error"
              title={error}
              action={
                duplicate ? (
                  <button type="button" className="button button--ghost" onClick={() => switchMode("signin", "student")}>
                    Go to sign in
                  </button>
                ) : undefined
              }
            />
          ) : null}

          {mode === "register" && registerTab === "staff" ? (
            <div className="staff-info">
              <p>
                Staff and teacher accounts are created by a CohortIQ administrator and assigned to the batch and programme you teach. This keeps
                staff access tied to verified assignments.
              </p>
              <ol className="staff-info__steps">
                <li><span>1</span> Ask your department's CohortIQ administrator for an account.</li>
                <li><span>2</span> They create it with your @{STAFF_EMAIL_DOMAIN} address and assigned cohort.</li>
                <li><span>3</span> Sign in as Staff / Teacher with the credentials they provide.</li>
              </ol>
              <button type="button" className="button button--primary button--wide" onClick={() => switchMode("signin", "staff")}>
                I have a staff account — sign in
              </button>
              <p className="auth__fine"><Icon name="lock" size={13} /> Administrator accounts are provisioned securely and cannot be registered publicly.</p>
            </div>
          ) : null}

          {registeringStudent ? (
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
              <p id={emailHintId} className="field__hint">Must end in @{STUDENT_EMAIL_DOMAIN}.</p>
              <PasswordField value={password} onChange={setPassword} autoComplete="new-password" describedBy={ruleId} />
              <p id={ruleId} className="field__hint">{PASSWORD_RULE}</p>
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
              <p className="field__hint">Enter your batch and programme exactly as your college lists them; they decide which regulations apply.</p>
              <button type="submit" className="button button--primary button--wide" disabled={submitting}>
                {submitting ? <span className="spinner" aria-hidden="true" /> : null}
                {submitting ? "Creating account…" : "Create account"}
              </button>
            </form>
          ) : null}

          {mode === "signin" ? (
            <form onSubmit={onSignIn} className="form" noValidate>
              <label className="field">
                <span>Email</span>
                <input
                  type="email"
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder={`name@${roleInfo.domain}`}
                  required
                  maxLength={254}
                />
              </label>
              <PasswordField value={password} onChange={setPassword} autoComplete="current-password" />
              {selectedRole !== "student" ? (
                <p className="auth__fine">
                  <Icon name="info" size={13} />
                  {selectedRole === "staff"
                    ? ` Staff accounts (@${STAFF_EMAIL_DOMAIN}) are provisioned by an administrator.`
                    : ` Administrator accounts (@${ADMINISTRATOR_EMAIL_DOMAIN}) are securely provisioned; public sign-up is unavailable.`}
                </p>
              ) : null}
              <button type="submit" className="button button--primary button--wide" disabled={submitting}>
                {submitting ? <span className="spinner" aria-hidden="true" /> : null}
                {submitting ? "Signing in…" : "Sign in"}
              </button>
            </form>
          ) : null}

          <p className="auth__switch">
            {mode === "register" ? "Already have an account?" : "New student?"}{" "}
            <button type="button" className="link-button" onClick={() => switchMode(mode === "register" ? "signin" : "register")}>
              {mode === "register" ? "Sign in" : "Create an account"}
            </button>
          </p>
        </main>
      </div>
    </div>
  );
}
