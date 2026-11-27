import { useState, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { useSession } from "../auth/session";
import { Notice } from "./Notice";

export function SignIn({ notice }: { notice: string | null }) {
  const { signIn } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
    } catch (caught) {
      // The API returns the same message for every failed sign-in; we show it as is.
      setError(caught instanceof ApiError ? caught.message : "Sign-in failed. Please try again.");
      setSubmitting(false);
    }
  }

  return (
    <main className="signin">
      <section className="signin__intro" aria-hidden="true">
        <p className="brand brand--large">
          <span className="brand__mark" />
          CohortIQ
        </p>
        <p className="signin__tagline">Every rule. Every cohort. The right answer.</p>
        <ul className="signin__points">
          <li>Answers from the regulations that apply to your batch</li>
          <li>Every answer shows the pages it relies on</li>
          <li>Says so plainly when the regulations don't cover it</li>
        </ul>
      </section>

      <section className="panel signin__card" aria-labelledby="signin-heading">
        <h1 id="signin-heading" className="signin__title">
          Sign in
        </h1>
        <p className="signin__subtitle">Use the account your college gave you.</p>
        {notice ? <Notice title={notice} /> : null}
        {error ? <Notice tone="error" title={error} /> : null}
        <form onSubmit={onSubmit} className="form" noValidate>
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
          <label className="field">
            <span>Password</span>
            <span className="field__password">
              <input
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                maxLength={256}
              />
              <button
                type="button"
                className="field__toggle"
                onClick={() => setShowPassword((value) => !value)}
                aria-pressed={showPassword}
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </span>
          </label>
          <button type="submit" className="button button--primary button--wide" disabled={submitting}>
            {submitting ? <span className="spinner" aria-hidden="true" /> : null}
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}
