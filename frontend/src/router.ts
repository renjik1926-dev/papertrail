// A tiny router. The real app uses normal paths; the demo build uses hash routes
// (/#/documents/:id) because GitHub Pages can't route app paths (BUILD_PLAN §10).
import { useEffect, useState } from "react";

export type Route =
  | { name: "home" }
  | { name: "document"; id: string }
  | { name: "print"; id: string }
  | { name: "not_found" };

const useHash = import.meta.env.VITE_DEMO === "1";

export function currentPath(): string {
  if (useHash) return window.location.hash.replace(/^#/, "") || "/";
  return window.location.pathname;
}

export function parseRoute(path: string): Route {
  if (path === "/" || path === "") return { name: "home" };
  const print = /^\/documents\/([^/]+)\/print\/?$/.exec(path);
  if (print?.[1]) return { name: "print", id: decodeURIComponent(print[1]) };
  const doc = /^\/documents\/([^/]+)\/?$/.exec(path);
  if (doc?.[1]) return { name: "document", id: decodeURIComponent(doc[1]) };
  return { name: "not_found" };
}

export function href(path: string): string {
  return useHash ? `#${path}` : path;
}

export function navigate(path: string): void {
  if (useHash) {
    window.location.hash = path;
    return;
  }
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function useRoute(): Route {
  const [path, setPath] = useState(currentPath);
  useEffect(() => {
    const update = () => setPath(currentPath());
    window.addEventListener("popstate", update);
    window.addEventListener("hashchange", update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener("hashchange", update);
    };
  }, []);
  return parseRoute(path);
}
