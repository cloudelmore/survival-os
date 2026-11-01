import { useCallback, useEffect, useState } from "react";
import {
  cancelJob, checkUpdates, contentAction, type ContentAction, type ContentEntry, type ContentJob,
  type ContentOverview, getContent, getUsb, importFile, type UsbFile, usbAction,
} from "./api";
import { PinPrompt } from "./PinPrompt";

const POLL_MS = 2000;
const GB = 1e9;
const IMPORT_CATEGORIES = [
  "medical_survival", "engineering", "natural_sciences", "radio", "mechanical",
  "navigation_weather", "education", "personal",
];

const size = (bytes: number | null) => {
  if (bytes === null) return "size unknown";
  return bytes >= GB ? `${(bytes / GB).toFixed(2)} GB` : `${(bytes / 1e6).toFixed(0)} MB`;
};

const LABELS: Record<ContentAction, string> = {
  install: "Install", update: "Update", remove: "Remove", validate: "Check",
};

type Prompt = { title: string; run: (pin: string) => Promise<void> };

function Storage({ data }: { data: ContentOverview["storage"] }) {
  return (
    <section aria-label="Storage">
      <h2>Storage</h2>
      <p>{size(data.headroom)} can still be installed. The last {size(data.floor)} stays free.</p>
      {data.warning && <p className="notice">STORAGE IS NEARLY AT THE FREE SPACE FLOOR</p>}
      {data.categories.filter((item) => item.used_bytes > 0).map((item) => {
        const percent = Math.min(100, (item.used_bytes / item.cap_bytes) * 100);
        return (
          <div className="meter-row" key={item.id}>
            <span>{item.name}</span>
            <span>{size(item.used_bytes)} of {size(item.cap_bytes)}</span>
            <div className="meter"><span className={percent > 80 ? "high" : ""} style={{ width: `${percent}%` }} /></div>
          </div>
        );
      })}
    </section>
  );
}

function Job({ job, onCancel }: { job: ContentJob; onCancel: () => void }) {
  const active = job.state === "queued" || job.state === "running" || job.state === "cancelling";
  const percent = job.bytes_total ? Math.floor((job.bytes_done / job.bytes_total) * 100) : null;
  return (
    <li>
      {job.action} {job.action === "import" ? "" : job.target}: {job.phase || job.state}
      {active && percent !== null && ` ${percent}%`}
      {job.error && <span className="unverified"> {job.error}</span>}
      {" "}
      {active && job.action !== "remove" && (
        <button className="link-button" onClick={onCancel}>CANCEL</button>
      )}
    </li>
  );
}

function Entry({ entry, busy, onAction }: {
  entry: ContentEntry;
  busy: boolean;
  onAction: (action: ContentAction) => void;
}) {
  const { installed, update } = entry;
  return (
    <article className="catalog-item">
      <h3>{entry.title}</h3>
      <p>{entry.summary}</p>
      <p>
        {size(entry.bytes)} · {entry.publisher}{entry.date ? ` · ${entry.date}` : ""}
        {entry.checksum_status !== "verified" && <span className="unverified"> · no checksum</span>}
      </p>
      <div className="catalog-actions">
        {!installed && <button className="link-button" disabled={busy} onClick={() => onAction("install")}>INSTALL</button>}
        {update && <button className="link-button" disabled={busy} onClick={() => onAction("update")}>UPDATE TO {update.version}</button>}
        {installed && <button className="link-button" disabled={busy} onClick={() => onAction("validate")}>CHECK</button>}
        {installed && <button className="link-button" disabled={busy} onClick={() => onAction("remove")}>REMOVE</button>}
      </div>
    </article>
  );
}

function Removable({ onPrompt }: { onPrompt: (prompt: Prompt) => void }) {
  const [usb, setUsb] = useState<{ mounted: boolean; files: UsbFile[] } | null>(null);
  const [category, setCategory] = useState("personal");
  const refresh = useCallback(() => { getUsb().then(setUsb).catch(() => setUsb(null)); }, []);
  useEffect(refresh, [refresh]);
  const prompt = (title: string, run: (pin: string) => Promise<void>) =>
    onPrompt({ title, run: async (pin) => { await run(pin); refresh(); } });

  return (
    <section aria-label="USB import">
      <h2>USB drive</h2>
      {!usb?.mounted && <button className="link-button" onClick={() => prompt("Read USB drive", (pin) => usbAction("mount", pin))}>READ USB DRIVE</button>}
      {usb?.mounted && (
        <>
          <p>Files already installed are skipped, so nothing is stored twice.</p>
          <select aria-label="Subject for imported files" value={category}
            onChange={(event) => setCategory(event.target.value)}>
            {IMPORT_CATEGORIES.map((item) => <option key={item} value={item}>{item.replace("_", " ")}</option>)}
          </select>
          {usb.files.map((file) => (
            <div className="catalog-actions" key={file.path}>
              <span>{file.path} ({size(file.bytes)})</span>
              <button className="link-button" onClick={() => prompt(`Import ${file.path}`, (pin) => importFile(file.path, category, pin))}>IMPORT</button>
            </div>
          ))}
          {!usb.files.length && <p>No supported files on this drive.</p>}
          <button className="link-button" onClick={() => prompt("Release USB drive", (pin) => usbAction("unmount", pin))}>RELEASE DRIVE</button>
        </>
      )}
    </section>
  );
}

export function ContentManager() {
  const [data, setData] = useState<ContentOverview | null>(null);
  const [failed, setFailed] = useState(false);
  const [prompt, setPrompt] = useState<Prompt | null>(null);

  const refresh = useCallback(() => {
    getContent().then((next) => { setData(next); setFailed(false); }).catch(() => setFailed(true));
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  if (failed && !data) return <p className="notice">COULD NOT READ THE CATALOG</p>;
  if (!data) return <p>Reading the catalog.</p>;
  const running = new Set(data.jobs
    .filter((job) => job.state === "queued" || job.state === "running")
    .map((job) => job.target));

  return (
    <div className="content">
      <Storage data={data.storage} />
      {data.jobs.length > 0 && (
        <section aria-label="Activity">
          <h2>Activity</h2>
          <ul>{data.jobs.slice(0, 5).map((job) => (
            <Job key={job.id} job={job} onCancel={() => { void cancelJob(job.id).then(refresh); }} />))}
          </ul>
        </section>
      )}
      <Removable onPrompt={setPrompt} />
      <section aria-label="Catalog">
        <h2>Collections</h2>
        <p>Installing goes online only for that download. An offline Pi can still import from USB.</p>
        <button className="link-button" onClick={() => setPrompt({ title: "Check for updates", run: checkUpdates })}>CHECK FOR UPDATES</button>
        {data.entries.map((entry) => (
          <Entry key={entry.id} entry={entry} busy={running.has(entry.id)}
            onAction={(action) => setPrompt({
              title: `${LABELS[action]} ${entry.title}`,
              run: (pin) => contentAction(action, entry.id, pin),
            })} />
        ))}
      </section>
      {data.imported.length > 0 && (
        <section aria-label="Imported">
          <h2>Imported from USB</h2>
          <ul>{data.imported.map((item) => <li key={item.id}>{item.title} ({size(item.bytes)})</li>)}</ul>
        </section>
      )}
      {prompt && (
        <PinPrompt title={prompt.title} onClose={() => setPrompt(null)}
          onSubmit={async (pin) => { await prompt.run(pin); refresh(); }} />
      )}
    </div>
  );
}
