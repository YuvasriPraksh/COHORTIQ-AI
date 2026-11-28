import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});

// jsdom does not implement scrolling; the public layout scrolls to top on page change.
window.scrollTo = () => {};
Element.prototype.scrollIntoView = function scrollIntoView() {};
