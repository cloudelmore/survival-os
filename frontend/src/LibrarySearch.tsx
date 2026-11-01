import { type FormEvent, useEffect, useRef, useState } from "react";
import {
  getLibraryStatus, type LibraryStatus, rescanLibrary, searchLibrary, type SearchResponse,
  type SearchResult,
} from "./api";

const FORMATS = ["pdf", "epub", "txt", "md", "html"];
const CATEGORY_NAMES: Record<string, string> = {
  medical_survival: "Medical & survival",
  engineering: "Engineering",
  natural_sciences: "Natural sciences",
  radio: "Radio",
  mechanical: "Mechanical",
  navigation_weather: "Navigation & weather",
  education: "Education",
  personal: "Personal",
};
const POLL_MS = 3000;

const routeParams = () => new URLSearchParams(window.location.hash.split("?")[1] ?? "");

export const viewerLink = (result: SearchResult) => {
  const params = new URLSearchParams({ page: String(result.page), hl: result.hits.join(" ") });
  return `#/viewer/${result.document_id}?${params}`;
};

function IndexerLine({ status }: { status: LibraryStatus | null }) {
  if (!status) return <p className="library-state">Reading library status.</p>;
  const { indexer, documents, pages_done, pages_total, pending } = status;
  if (!documents && indexer.state === "stopped") {
    return <p className="library-state">The library is empty and the indexer is not running.</p>;
  }
  const progress = pending ? ` Indexing: ${pages_done} of ${pages_total} locations.` : "";
  const paused = indexer.state === "paused" ? ` PAUSED: ${indexer.detail}.` : "";
  return (
    <p className="library-state" role="status">
      {documents} documents.{progress}{paused}
    </p>
  );
}

function Result({ result }: { result: SearchResult }) {
  return (
    <li>
      <a className="result" href={viewerLink(result)}>
        <span className="result-title">{result.title}</span>
        <span className="result-where">
          {result.format.toUpperCase()}
          {result.format === "pdf" || result.format === "epub" ? ` · ${result.label}` : ""}
          {` · ${CATEGORY_NAMES[result.category] ?? result.category}`}
        </span>
        <span className="result-snippet">
          {result.snippet.map((part, index) =>
            part.hit ? <mark key={index}>{part.text}</mark> : <span key={index}>{part.text}</span>)}
        </span>
      </a>
    </li>
  );
}

export function LibrarySearch() {
  const start = routeParams();
  const [text, setText] = useState(start.get("q") ?? "");
  const [format, setFormat] = useState(start.get("format") ?? "");
  const [category, setCategory] = useState(start.get("category") ?? "");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [error, setError] = useState(false);
  const [status, setStatus] = useState<LibraryStatus | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { input.current?.focus(); }, []);

  useEffect(() => {
    let live = true;
    const refresh = () => getLibraryStatus().then((next) => { if (live) setStatus(next); })
      .catch(() => undefined);
    refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    return () => { live = false; window.clearInterval(timer); };
  }, []);

  const run = (query: string, offset: number) => {
    if (!query.trim()) { setResponse(null); return; }
    setError(false);
    searchLibrary(query, format, category, offset).then((next) => setResponse(
      offset && response ? { ...next, results: [...response.results, ...next.results] } : next,
    )).catch(() => setError(true));
  };

  useEffect(() => { run(text, 0); }, [format, category]); // eslint-disable-line

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const params = new URLSearchParams({ q: text });
    if (format) params.set("format", format);
    if (category) params.set("category", category);
    window.history.replaceState(null, "", `#/library-search?${params}`);
    run(text, 0);
  };

  return (
    <div className="library">
      <form className="search-form" role="search" onSubmit={submit}>
        <input ref={input} aria-label="Search the library" type="search" value={text}
          placeholder="Search the library" onChange={(event) => setText(event.target.value)} />
        <select aria-label="Format" value={format}
          onChange={(event) => setFormat(event.target.value)}>
          <option value="">All formats</option>
          {FORMATS.map((item) => <option key={item} value={item}>{item.toUpperCase()}</option>)}
        </select>
        <select aria-label="Category" value={category}
          onChange={(event) => setCategory(event.target.value)}>
          <option value="">All subjects</option>
          {Object.entries(CATEGORY_NAMES).map(([key, name]) =>
            <option key={key} value={key}>{name}</option>)}
        </select>
        <button type="submit" className="link-button">SEARCH</button>
      </form>
      <IndexerLine status={status} />
      <p className="library-scope">
        Searches the document library only. Encyclopedias have their own search.{" "}
        {text.trim() && <a href={`#/kiwix?${new URLSearchParams({ q: text, from: "library-search" })}`}>Search them for this</a>}
      </p>
      {error && <p className="notice">SEARCH FAILED. TRY AGAIN.</p>}
      {response && !response.total && <p className="notice">NO MATCHES</p>}
      {response && response.total > 0 && (
        <>
          <p className="library-state">{response.total} {response.total === 1 ? "place" : "places"} found</p>
          <ol className="results">
            {response.results.map((result) => (
              <Result key={`${result.document_id}-${result.page}`} result={result} />))}
          </ol>
          {response.more && (
            <button className="link-button"
              onClick={() => run(text, response.results.length)}>MORE RESULTS</button>
          )}
        </>
      )}
      {status && status.failed.length > 0 && (
        <details>
          <summary>{status.failed.length} files could not be indexed</summary>
          <ul>{status.failed.map((item) => <li key={item.path}>{item.path}: {item.error}</li>)}</ul>
        </details>
      )}
      {status && status.no_text.length > 0 && (
        <details>
          <summary>{status.no_text.length} files have scanned pages that cannot be searched</summary>
          <ul>{status.no_text.map((item) => (
            <li key={item.path}>{item.path}: {item.pages_no_text} pages</li>))}</ul>
        </details>
      )}
      <button className="link-button" onClick={() => void rescanLibrary()}>CHECK FOR NEW FILES</button>
    </div>
  );
}
