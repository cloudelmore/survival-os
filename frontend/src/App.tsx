import { useCallback, useEffect, useRef, useState } from "react";
import { Home } from "./Home";
import { Page } from "./Page";
import { PowerDialog } from "./PowerDialog";
import { SECTIONS } from "./sections";
import { StatusPage } from "./StatusPage";

const sectionFromHash = () => window.location.hash.replace(/^#\/?/, "") || null;

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
  const openPower = useCallback(() => setPower(true), []);
  const closePower = useCallback(() => setPower(false), []);

  useEffect(() => {
    if (!current) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector("dialog[open]")) back();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, back]);

  const section = SECTIONS.find((item) => item.id === current);

  return (
    <>
      {section ? (
        <Page id={section.id} title={section.title} onBack={back}>
          {section.phase === undefined ? (
            <StatusPage onPower={openPower} />
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
