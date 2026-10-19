import { isDemo } from "./api/source";
import { DemoBanner } from "./components/Notices";
import { DocumentPage } from "./pages/DocumentPage";
import { PrintPage } from "./pages/PrintPage";
import { UploadPage, linkClick } from "./pages/UploadPage";
import { href, useRoute } from "./router";

export function App() {
  const route = useRoute();
  const printing = route.name === "print";
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      {!printing && (
        <header className="masthead">
          <a className="wordmark" href={href("/")} onClick={(e) => linkClick(e, "/")}>
            PaperTrail
          </a>
          <span className="masthead__tagline">Letters into checklists. Every item cited.</span>
        </header>
      )}
      {isDemo && !printing && <DemoBanner />}
      <main id="main" tabIndex={-1}>
        {route.name === "home" && <UploadPage />}
        {route.name === "document" && <DocumentPage id={route.id} />}
        {route.name === "print" && <PrintPage id={route.id} />}
        {route.name === "not_found" && <p>That page doesn't exist.</p>}
      </main>
      {!printing && (
        <footer className="site-footer">
          PaperTrail lists what a letter says; it isn't legal, medical or financial advice. An AI
          model (Claude) suggests the items and plain code checks each one against the letter.
        </footer>
      )}
    </>
  );
}
