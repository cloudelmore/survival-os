import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  type AiEvent, type AiMode, type AiSource, type AiStatus, askLibrary, getAiStatus, startAi, stopAi,
} from "./api";
import { PinPrompt } from "./PinPrompt";

const POLL_MS = 3000;
const MODE_NOTICE: Partial<Record<AiMode, string>> = {
  restricted: "MEDICAL, WILD FOOD OR ELECTRICAL TOPIC. THE AI DOES NOT ANSWER THESE. READ THE SOURCES.",
  off: "THE AI IS OFF. THESE ARE THE CLOSEST PASSAGES.",
  empty: "NOTHING IN THE LIBRARY MATCHES THAT QUESTION.",
};
const WITHHELD = {
  restricted: "ANSWER WITHHELD: IT TURNED TO A MEDICAL, WILD FOOD OR ELECTRICAL TOPIC. READ THE SOURCES.",
  uncited: "ANSWER WITHHELD: IT COULD NOT BE TRACED TO THE SOURCES. READ THEM INSTEAD.",
};

const sourceLink = (source: AiSource) =>
  `#/viewer/${source.document_id}?${new URLSearchParams({ page: String(source.page), hl: "" })}`;

function Answer({ text, sources }: { text: string; sources: AiSource[] }) {
  return (
    <p className="ai-answer">
      {text.split(/(\[\d+\])/).map((part, index) => {
        const source = sources.find((item) => `[${item.number}]` === part);
        return source ? <a key={index} href={sourceLink(source)}>{part}</a> : part;
      })}
    </p>
  );
}

export function OfflineAi() {
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<AiMode | null>(null);
  const [sources, setSources] = useState<AiSource[]>([]);
  const [answer, setAnswer] = useState("");
  const [withheld, setWithheld] = useState<keyof typeof WITHHELD | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [prompt, setPrompt] = useState<"start" | "stop" | null>(null);
  const request = useRef<AbortController | null>(null);

  const refresh = useCallback(() => {
    getAiStatus().then(setStatus).catch(() => setStatus(null));
  }, []);
  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    return () => {
      window.clearInterval(timer);
      request.current?.abort();
    };
  }, [refresh]);

  const onEvent = (event: AiEvent) => {
    if (event.type === "sources") {
      setMode(event.mode);
      setSources(event.sources);
    } else if (event.type === "text") {
      setAnswer((text) => text + event.text);
    } else if (event.type === "withheld") {
      setAnswer("");
      setWithheld(event.reason);
    } else if (event.type === "failed") {
      setFailed(true);
    }
  };

  const ask = async (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim() || busy) return;
    setMode(null);
    setSources([]);
    setAnswer("");
    setWithheld(null);
    setFailed(false);
    setBusy(true);
    const controller = new AbortController();
    request.current = controller;
    try {
      await askLibrary(question, onEvent, controller.signal);
    } catch {
      if (!controller.signal.aborted) setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const ready = status?.runtime_installed && status.model_installed;
  return (
    <div className="content">
      <p className="notice">THE AI CAN BE WRONG. CHECK ITS CITED SOURCES. IT NEVER ANSWERS MEDICAL, WILD FOOD OR ELECTRICAL QUESTIONS.</p>
      {status && !ready && (
        <p>The AI is optional and not installed. <a href="#/content-manager">Open the Content Manager</a> to add the AI runtime and model.</p>
      )}
      {ready && !status.ready && (
        <button className="link-button" onClick={() => setPrompt("start")}>START AI</button>
      )}
      {ready && status.ready && (
        <button className="link-button" onClick={() => setPrompt("stop")}>STOP AI</button>
      )}
      <form className="ai-form" onSubmit={ask}>
        <input aria-label="Question" maxLength={500} placeholder="Ask the library" value={question}
          onChange={(event) => setQuestion(event.target.value)} />
        <button className="link-button" disabled={busy}>{busy ? "WORKING" : "ASK"}</button>
      </form>
      {busy && mode === "answer" && !answer && <p>Reading the passages. This can take a minute or more.</p>}
      {mode && MODE_NOTICE[mode] && <p className="notice">{MODE_NOTICE[mode]}</p>}
      {withheld && <p className="notice">{WITHHELD[withheld]}</p>}
      {failed && <p className="notice">THE AI STOPPED. READ THE SOURCES.</p>}
      {answer && <Answer text={answer} sources={sources} />}
      {sources.length > 0 && <h2>Sources</h2>}
      {sources.map((source) => (
        <a className="result" key={source.number} href={sourceLink(source)}>
          <strong>[{source.number}] {source.title}</strong>
          <span> {source.label ?? `Page ${source.page}`}</span>
          <p>{source.text}</p>
        </a>
      ))}
      {prompt && (
        <PinPrompt title={prompt === "start" ? "Start the AI" : "Stop the AI"}
          onClose={() => setPrompt(null)}
          onSubmit={async (pin) => {
            await (prompt === "start" ? startAi : stopAi)(pin);
            setPrompt(null);
            refresh();
          }} />
      )}
    </div>
  );
}
