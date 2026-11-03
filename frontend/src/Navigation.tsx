import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { addWaypoint, deleteRoute, deleteWaypoint, exportGpxToUsb, getGpxFiles, getMaps,
  getNavigation, getUsb, importGpx, usbAction, type MapInfo, type NavigationData } from "./api";
import { createMap, type Center, type MapHandle, type Overlays } from "./mapEngine";
import { PinPrompt } from "./PinPrompt";

type Prompt = { title: string; run: (pin: string) => Promise<void> };

const place = (lat: number, lon: number) =>
  `${Math.abs(lat).toFixed(5)}°${lat >= 0 ? "N" : "S"} ${Math.abs(lon).toFixed(5)}°${lon >= 0 ? "E" : "W"}`;

function MapCanvas({ info, overlays, data, handle, onMove }: {
  info: MapInfo;
  overlays: Overlays;
  data: NavigationData;
  handle: React.RefObject<MapHandle | null>;
  onMove: (center: Center) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!box.current) return;
    try {
      handle.current = createMap(box.current, info, overlays, onMove, () => setFailed(true));
    } catch {
      setFailed(true);
    }
    return () => {
      handle.current?.destroy();
      handle.current = null;
    };
  }, [info, overlays, handle, onMove]);

  useEffect(() => { handle.current?.setData(data); }, [data, handle]);

  return (
    <div className="map-frame">
      <div ref={box} className="map-canvas" role="application" aria-label={`Map: ${info.title}`} />
      <span className="map-crosshair" aria-hidden="true">+</span>
      {failed && <p className="notice map-failed">THE MAP COULD NOT BE DRAWN</p>}
    </div>
  );
}

function Gpx({ onChanged }: { onChanged: () => void }) {
  const [mounted, setMounted] = useState(false);
  const [files, setFiles] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [prompt, setPrompt] = useState<Prompt | null>(null);

  const refresh = useCallback(async () => {
    const usb = await getUsb();
    setMounted(usb.mounted);
    setFiles(usb.mounted ? (await getGpxFiles()).files : []);
  }, []);
  useEffect(() => { refresh().catch(() => setMounted(false)); }, [refresh]);

  const load = async (path: string) => {
    try {
      const added = await importGpx(path);
      setMessage(`Added ${added.waypoints} waypoints and ${added.routes} routes.`);
      onChanged();
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : "Import failed");
    }
  };

  return (
    <section aria-label="GPX">
      <h2>GPX</h2>
      {!mounted && (
        <button className="link-button" onClick={() => setPrompt({
          title: "Read USB drive", run: (pin) => usbAction("mount", pin) })}>USB DRIVE</button>
      )}
      {mounted && (
        <>
          {files.map((path) => (
            <div className="nav-item" key={path}>
              <span>{path}</span>
              <button className="link-button" onClick={() => { void load(path); }}>IMPORT</button>
            </div>
          ))}
          {!files.length && <p>No GPX files on this drive.</p>}
          <button className="link-button" onClick={() => setPrompt({
            title: "Save GPX to USB drive",
            run: async (pin) => {
              await exportGpxToUsb(pin);
              setMessage("Saved survival-os-navigation.gpx to the drive.");
            } })}>SAVE TO USB</button>
          <button className="link-button" onClick={() => setPrompt({
            title: "Release USB drive", run: (pin) => usbAction("unmount", pin) })}>RELEASE DRIVE</button>
        </>
      )}
      {message && <p role="status">{message}</p>}
      {prompt && (
        <PinPrompt title={prompt.title} onClose={() => setPrompt(null)}
          onSubmit={async (pin) => { await prompt.run(pin); await refresh(); }} />
      )}
    </section>
  );
}

export default function Navigation() {
  const [maps, setMaps] = useState<MapInfo[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [chosen, setChosen] = useState<string | null>(null);
  const [data, setData] = useState<NavigationData>({ waypoints: [], routes: [] });
  const [center, setCenter] = useState<Center | null>(null);
  const [name, setName] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [shown, setShown] = useState({ terrain: false, imagery: false });
  const handle = useRef<MapHandle | null>(null);
  const overlays = useMemo<Overlays>(() => ({
    terrain: maps?.find((item) => item.kind === "terrain"),
    imagery: maps?.find((item) => item.kind === "imagery"),
  }), [maps]);

  const reload = useCallback(() => {
    getNavigation().then(setData).catch(() => setFailed(true));
  }, []);
  useEffect(() => {
    getMaps().then((found) => setMaps(found.maps)).catch(() => setFailed(true));
    reload();
  }, [reload]);

  if (failed) return <p className="notice">COULD NOT READ THE MAPS</p>;
  if (!maps) return <p>Reading the maps.</p>;
  const regions = maps.filter((item) => item.kind === "base");
  if (!regions.length) {
    return (
      <div className="content">
        <p className="notice">NO MAP INSTALLED YET</p>
        <p><a href="#/content-manager">Open the Content Manager</a> to add a map.</p>
      </div>
    );
  }
  const info = regions.find((item) => item.id === chosen) ?? regions[0];

  const toggle = (overlay: "terrain" | "imagery") => {
    const visible = !shown[overlay];
    setShown({ ...shown, [overlay]: visible });
    handle.current?.show(overlay, visible);
  };

  const add = async () => {
    const here = handle.current?.center();
    if (!here) return;
    await addWaypoint(name.trim() || `Waypoint ${data.waypoints.length + 1}`, here.lat, here.lon);
    setName("");
    reload();
  };

  // A touch screen makes a stray tap easy, so the first press only arms the delete.
  const remove = async (key: string, run: () => Promise<void>) => {
    if (confirming !== key) {
      setConfirming(key);
      return;
    }
    setConfirming(null);
    await run();
    reload();
  };

  return (
    <div className="nav-layout">
      <MapCanvas key={info.id} info={info} overlays={overlays} data={data} handle={handle}
        onMove={setCenter} />
      <aside className="nav-panel">
        {regions.length > 1 && (
          <select aria-label="Map region" value={info.id} onChange={(event) => {
            setChosen(event.target.value);
            setShown({ terrain: false, imagery: false });
          }}>
            {regions.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
          </select>
        )}
        {(overlays.terrain || overlays.imagery) && (
          <div className="catalog-actions">
            {overlays.terrain && (
              <button className="link-button" aria-pressed={shown.terrain} onClick={() => toggle("terrain")}>
                {shown.terrain ? "[X]" : "[ ]"} CONTOURS
              </button>
            )}
            {overlays.imagery && (
              <button className="link-button" aria-pressed={shown.imagery} onClick={() => toggle("imagery")}>
                {shown.imagery ? "[X]" : "[ ]"} PHOTOS
              </button>
            )}
          </div>
        )}
        <p className="nav-position">{center ? place(center.lat, center.lon) : "--"}</p>
        <section aria-label="New waypoint">
          <input aria-label="Waypoint name" placeholder={`Waypoint ${data.waypoints.length + 1}`}
            maxLength={120} value={name} onChange={(event) => setName(event.target.value)} />
          <button className="link-button" onClick={() => { void add(); }}>MARK CENTER</button>
        </section>
        <section aria-label="Waypoints">
          <h2>Waypoints</h2>
          {!data.waypoints.length && <p>None yet.</p>}
          {data.waypoints.map((item) => (
            <div className="nav-item" key={item.id}>
              <button className="link-button" onClick={() => handle.current?.flyTo(item.lon, item.lat)}>{item.name}</button>
              <button className="link-button" onClick={() => { void remove(`w${item.id}`, () => deleteWaypoint(item.id)); }}>
                {confirming === `w${item.id}` ? "SURE?" : "X"}
              </button>
            </div>
          ))}
        </section>
        {data.routes.length > 0 && (
          <section aria-label="Routes">
            <h2>Routes</h2>
            {data.routes.map((item) => (
              <div className="nav-item" key={item.id}>
                <button className="link-button" onClick={() => handle.current?.flyTo(item.points[0][0], item.points[0][1])}>{item.name}</button>
                <button className="link-button" onClick={() => { void remove(`r${item.id}`, () => deleteRoute(item.id)); }}>
                  {confirming === `r${item.id}` ? "SURE?" : "X"}
                </button>
              </div>
            ))}
          </section>
        )}
        <Gpx onChanged={reload} />
      </aside>
    </div>
  );
}
