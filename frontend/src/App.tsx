import { useCallback, useEffect, useRef, useState } from "react";
import { Home } from "./Home";
import { ContentManager } from "./ContentManager";
import { closeKiwix, KiwixList, KiwixView } from "./Kiwix";
import { LibrarySearch } from "./LibrarySearch";
import { Page } from "./Page";
import { PowerDialog } from "./PowerDialog";
import { SECTIONS } from "./sections";
import { StatusPage } from "./StatusPage";
import { Viewer } from "./Viewer";

const sectionFromHash = () =>
  window.location.hash.replace(/^#\/?/, "").split("?")[0].split("/")[0] || null;

export function App() {
  const [current, setCurrent] = useState(sectionFromHash);
  const [power, setPower] = useState(false);
  const last = useRef<string | null>(null);

  useEffect(() => {
    const onHash = () => setCurrent(sectionFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const open = useCallback((id: string) => {
    last.current = id;
    window.location.hash = `/${id}`;
  }, []);
  const back = useCallback(() => { window.location.hash = "/"; }, []);
  // A viewer may be reached from any search, so return to it with the results intact.
  const closeViewer = useCallback(() => {
    if (window.history.length > 1) window.history.back();
    else window.location.hash = "/library-search";
  }, []);
  const openPower = useCallback(() => setPower(true), []);
  const closePower = useCallback(() => setPower(false), []);

  useEffect(() => {
    if (!current) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || document.querySelector("dialog[open]")) return;
      if (current === "kiwix") closeKiwix();
      else if (current === "viewer") closeViewer();
      else back();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, back, closeViewer]);

  const section = SECTIONS.find((item) => item.id === current);

  return (
    <>
      {current === "kiwix" ? (
        <KiwixView key={window.location.hash} />
      ) : current === "viewer" ? (
        <Viewer key={window.location.hash} onBack={closeViewer} />
      ) : section ? (
        <Page id={section.id} title={section.title} onBack={back}>
          {section.phase === undefined ? (
            <StatusPage onPower={openPower} />
          ) : section.id === "library-search" ? (
            <LibrarySearch />
          ) : section.id === "content-manager" ? (
            <ContentManager />
          ) : section.phase === 5 ? (
            <KiwixList section={section} />
          ) : (
            <>
              <p>{section.summary}</p>
              <p className="notice">NOT INSTALLED YET</p>
              <p>This section arrives in development phase {section.phase}.</p>
            </>
          )}
        </Page>
      ) : (
        <Home onOpen={open} onPower={openPower} lastSection={last.current} />
      )}
      {power && <PowerDialog onClose={closePower} />}
    </>
  );
}
