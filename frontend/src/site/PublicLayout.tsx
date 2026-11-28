import { useEffect, useState, type ReactNode } from "react";

import { useTheme } from "../theme";
import { Icon, LogoMark } from "../components/icons";

const LINKS = [
  { path: "/", label: "Home" },
  { path: "/features", label: "Features" },
  { path: "/how-it-works", label: "How It Works" },
  { path: "/about", label: "About" },
];

export function ThemeToggle({ className = "" }: { className?: string }) {
  const [theme, toggle] = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className={`icon-button theme-toggle ${className}`}
      onClick={toggle}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
    >
      <Icon name={theme === "dark" ? "sun" : "moon"} />
    </button>
  );
}

export function Brand({ href = "#/" }: { href?: string }) {
  return (
    <a className="brand" href={href} aria-label="CohortIQ home">
      <LogoMark size={34} />
      <span className="brand__name">
        Cohort<span>IQ</span>
      </span>
    </a>
  );
}

function SiteNav({ path }: { path: string }) {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => setOpen(false), [path]);

  return (
    <header className={`site-nav${scrolled ? " site-nav--scrolled" : ""}${open ? " site-nav--open" : ""}`}>
      <div className="site-nav__inner">
        <Brand />
        <nav className="site-nav__links" aria-label="Primary">
          {LINKS.map((link) => {
            const active = path === link.path;
            return (
              <a key={link.path} href={`#${link.path}`} className={`site-nav__link${active ? " is-active" : ""}`} aria-current={active ? "page" : undefined}>
                {link.label}
              </a>
            );
          })}
        </nav>
        <div className="site-nav__actions">
          <ThemeToggle />
          <a className="button button--ghost button--compact site-nav__signin" href="#/signin">
            Sign In
          </a>
          <a className="button button--primary button--compact site-nav__cta" href="#/signup">
            Get Started
          </a>
          <button
            type="button"
            className="icon-button site-nav__menu"
            aria-expanded={open}
            aria-controls="mobile-menu"
            aria-label={open ? "Close menu" : "Open menu"}
            onClick={() => setOpen((value) => !value)}
          >
            <Icon name={open ? "close" : "menu"} />
          </button>
        </div>
      </div>
      <div id="mobile-menu" className="site-nav__mobile" hidden={!open}>
        {LINKS.map((link) => (
          <a key={link.path} href={`#${link.path}`} className={`site-nav__mobile-link${path === link.path ? " is-active" : ""}`}>
            {link.label}
          </a>
        ))}
        <div className="site-nav__mobile-actions">
          <a className="button button--ghost" href="#/signin">Sign In</a>
          <a className="button button--primary" href="#/signup">Get Started</a>
        </div>
      </div>
    </header>
  );
}

function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer__inner">
        <div className="site-footer__brand">
          <Brand />
          <p>Cohort-aware answers to academic regulation questions, with the evidence on the page.</p>
        </div>
        <nav className="site-footer__cols" aria-label="Footer">
          <div>
            <h3>Product</h3>
            <a href="#/features">Features</a>
            <a href="#/how-it-works">How It Works</a>
          </div>
          <div>
            <h3>Project</h3>
            <a href="#/about">About CohortIQ</a>
          </div>
          <div>
            <h3>Account</h3>
            <a href="#/signin">Sign In</a>
            <a href="#/signup">Create a student account</a>
          </div>
        </nav>
      </div>
      <div className="site-footer__base">
        <span>© {new Date().getFullYear()} CohortIQ</span>
        <span>Answers come from approved regulations only. Always check the cited page.</span>
      </div>
    </footer>
  );
}

export function PublicLayout({ path, children }: { path: string; children: ReactNode }) {
  useEffect(() => {
    window.scrollTo?.({ top: 0 });
  }, [path]);

  return (
    <div className="site">
      <a className="skip-link" href="#site-main" onClick={(event) => { event.preventDefault(); document.getElementById("site-main")?.focus(); }}>
        Skip to content
      </a>
      <SiteNav path={path} />
      <main id="site-main" className="site-main page-enter" key={path} tabIndex={-1}>
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
