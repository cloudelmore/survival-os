import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { type DocumentView, getDocument, getDocumentView, type LibraryDocument } from "./api";
import { markTerms } from "./highlight";

// pdf.js is large, so it loads only when a PDF is opened.
const PdfView = lazy(() => import("./PdfView"));

function route() {
  const [path, query] = window.location.hash.split("?");
  const params = new URLSearchParams(query ?? "");
  return {
    id: Number(path.split("/").pop()),
    page: Math.max(1, Number(params.get("page")) || 1),
    terms: (params.get("hl") ?? "").split(" ").filter(Boolean),
  };
}

function Flowing({ view, terms, onMarks }: {
  view: Exclude<DocumentView, { kind: "pdf" }>;
  terms: string[];
  onMarks: (marks: HTMLElement[]) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { if (box.current) onMarks(markTerms(box.current, terms)); }, [view]); // eslint-disable-line
  return view.kind === "text"
    ? <div ref={box} className="reader-text"><pre>{view.text}</pre></div>
    // Sanitised by the API (render.py), and the page's CSP forbids scripts as a second layer.
    : <div ref={box} className="reader-text" dangerouslySetInnerHTML={{ __html: view.html }} />;
}

export function Viewer({ onBack }: { onBack: () => void }) {
  const [{ id, terms }] = useState(route);
  const [page, setPage] = useState(() => route().page);
  const [doc, setDoc] = useState<LibraryDocument | null>(null);
  const [view, setView] = useState<DocumentView | null>(null);
  const [failed, setFailed] = useState(false);
  const [marks, setMarks] = useState<HTMLElement[]>([]);
  const [current, setCurrent] = useState(0);
  const body = useRef<HTMLElement>(null);

  useEffect(() => { getDocument(id).then(setDoc).catch(() => setFailed(true)); }, [id]);
  useEffect(() => {
    setView(null);
    getDocumentView(id, page).then(setView).catch(() => setFailed(true));
    body.current?.scrollTo?.(0, 0);
  }, [id, page]);
  useEffect(() => { body.current?.focus(); }, [doc]);

  const show = useCallback((list: HTMLElement[], index: number) => {
    list.forEach((mark, position) => mark.classList.toggle("current", position === index));
    list[index]?.scrollIntoView?.({ block: "center" });
    setCurrent(index);
  }, []);
  const onMarks = useCallback((list: HTMLElement[]) => {
    setMarks(list);
    show(list, 0);
  }, [show]);

  const paged = doc?.format === "pdf" || doc?.format === "epub";
  const last = doc?.pages_total ?? 1;
  const go = (next: number) => setPage(Math.min(Math.max(1, next), last));
  const step = (delta: number) =>
    marks.length && show(marks, (current + delta + marks.length) % marks.length);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight" && paged) go(page + 1);
      else if (event.key === "ArrowLeft" && paged) go(page - 1);
      else if (event.key === "n") step(1);
      else if (event.key === "b") step(-1);
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="screen reader">
      <header className="reader-bar">
        <button className="link-button" onClick={onBack}>[ESC] BACK</button>
        <h1>{doc?.title ?? "Opening"}</h1>
        {marks.length > 0 && (
          <span className="reader-group">
            <button className="link-button" aria-label="Previous match" onClick={() => step(-1)}>[B]</button>
            <span>{current + 1}/{marks.length}</span>
            <button className="link-button" aria-label="Next match" onClick={() => step(1)}>[N]</button>
          </span>
        )}
        {paged && (
          <span className="reader-group">
            <button className="link-button" aria-label="Previous page" disabled={page <= 1}
              onClick={() => go(page - 1)}>&lt;</button>
            <span>{page}/{last}</span>
            <button className="link-button" aria-label="Next page" disabled={page >= last}
              onClick={() => go(page + 1)}>&gt;</button>
          </span>
        )}
      </header>
      <main ref={body} className="reader-body" tabIndex={-1}>
        {failed && <p className="notice">THIS DOCUMENT COULD NOT BE OPENED</p>}
        {view?.kind === "pdf" && (
          <Suspense fallback={<p>Opening.</p>}>
            <PdfView id={id} page={page} terms={terms} onMarks={onMarks} onError={() => setFailed(true)} />
          </Suspense>
        )}
        {view && view.kind !== "pdf" && <Flowing view={view} terms={terms} onMarks={onMarks} />}
      </main>
    </div>
  );
}
