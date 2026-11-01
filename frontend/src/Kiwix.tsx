import { useEffect, useState } from "react";
import { getKiwixBooks, type KiwixBook } from "./api";
import type { Section } from "./sections";

// Archived web pages run in their own origin, away from the dashboard and its admin API.
const KIWIX_ORIGIN = `http://${window.location.hostname}:8083`;

const SECTION_CATEGORIES: Record<string, string[] | null> = {
  knowledge: null,
  medical: ["medical_survival"],
  engineering: ["engineering", "mechanical"],
  "food-water": ["medical_survival", "natural_sciences"],
  communications: ["radio"],
};

const SAFETY_SECTIONS = new Set(["medical", "food-water", "engineering"]);

const routeParams = () => new URLSearchParams(window.location.hash.split("?")[1] ?? "");

// The frame keeps its own page history, so closing goes by name, not by history.
export const closeKiwix = () => {
  window.location.hash = `/${routeParams().get("from") ?? ""}`;
};

export function KiwixList({ section }: { section: Section }) {
  const [books, setBooks] = useState<KiwixBook[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getKiwixBooks().then((data) => setBooks(data.books)).catch(() => setFailed(true));
  }, []);

  const wanted = SECTION_CATEGORIES[section.id];
  const shown = books?.filter((book) => !wanted || wanted.includes(book.category)) ?? [];

  return (
    <div className="content">
      <p>{section.summary}</p>
      {failed && <p className="notice">COULD NOT READ THE LIBRARY</p>}
      {books && !shown.length && (
        <>
          <p className="notice">NOTHING INSTALLED HERE YET</p>
          <p><a href="#/content-manager">Open the Content Manager</a> to add collections.</p>
        </>
      )}
      {shown.map((book) => (
        <a key={book.id} className="result" href={`#/kiwix?${new URLSearchParams({ book: book.name, from: section.id })}`}>
          <span className="result-title">{book.title}</span>
        </a>
      ))}
      {SAFETY_SECTIONS.has(section.id) && shown.length > 0 && (
        <p>Check medical, electrical and wild food guidance against a trusted source before acting on it.</p>
      )}
    </div>
  );
}

export function KiwixView() {
  const params = routeParams();
  const book = params.get("book");
  const query = params.get("q");
  const path = query
    ? `/search?${new URLSearchParams({ pattern: query })}`
    : book ? `/content/${encodeURIComponent(book)}` : "/";

  return (
    <div className="screen kiwix-screen">
      <header className="reader-bar">
        <button className="link-button" onClick={closeKiwix}>CLOSE</button>
        <button className="link-button" onClick={() => window.history.back()}>&lt; PREVIOUS PAGE</button>
        <h1>{query ? `Encyclopedia search: ${query}` : "Encyclopedias"}</h1>
      </header>
      <iframe className="kiwix-frame" title="Kiwix" src={`${KIWIX_ORIGIN}${path}`} />
    </div>
  );
}
