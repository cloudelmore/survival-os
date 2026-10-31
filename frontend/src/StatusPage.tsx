import { useEffect, useState } from "react";
import { getStatus, type Status } from "./api";

const UNKNOWN = "Not available";
const GB = 1e9;
const FLAG_NAMES: Record<string, string> = {
  under_voltage: "Under-voltage",
  frequency_capped: "Frequency capped",
  throttled: "Throttled",
  soft_temperature_limit: "Temperature limit",
};

const flags = (values: string[]) =>
  values.length ? values.map((value) => FLAG_NAMES[value] ?? value).join(", ") : "None";

function uptime(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  return `${hours} h ${Math.floor((seconds % 3600) / 60)} min`;
}

function Row({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="status-row">
      <dt>{label}</dt>
      <dd className={warn ? "warn" : undefined}>{value}</dd>
    </div>
  );
}

function Report({ status }: { status: Status }) {
  const { memory, storage, power } = status;
  const throttling = power.throttling;
  const lowSpace = storage !== null && storage.available_bytes < storage.floor_bytes;
  return (
    <div className="status-columns">
      <dl>
        <Row label="CPU" value={status.cpu_percent === null ? UNKNOWN : `${status.cpu_percent}%`} />
        <Row
          label="Temperature"
          value={status.temperature_c === null ? UNKNOWN : `${status.temperature_c} C`}
          warn={status.temperature_c !== null && status.temperature_c >= 80}
        />
        <Row
          label="Memory free"
          value={memory
            ? `${(memory.available_bytes / GB).toFixed(1)} of ${(memory.total_bytes / GB).toFixed(1)} GB`
            : UNKNOWN}
        />
        <Row
          label="Storage free"
          value={storage
            ? `${Math.round(storage.available_bytes / GB)} of ${Math.round(storage.usable_bytes / GB)} GB`
            : UNKNOWN}
          warn={lowSpace}
        />
        <Row
          label="Keep free"
          value={storage ? `${Math.round(storage.floor_bytes / GB)} GB` : UNKNOWN}
        />
        <Row label="Uptime" value={status.uptime_seconds === null ? UNKNOWN : uptime(status.uptime_seconds)} />
      </dl>
      <dl>
        <Row label="Input" value={power.input_volts === null ? UNKNOWN : `${power.input_volts} V`} />
        <Row
          label="Supply limit"
          value={power.supply_current_ma === null ? UNKNOWN : `${power.supply_current_ma / 1000} A`}
        />
        <Row
          label="Power problems"
          value={throttling ? flags(throttling.now) : UNKNOWN}
          warn={Boolean(throttling?.now.length)}
        />
        <Row
          label="Since boot"
          value={throttling ? flags(throttling.since_boot) : UNKNOWN}
          warn={Boolean(throttling?.since_boot.length)}
        />
        {Object.entries(status.services).map(([name, state]) => (
          <Row
            key={name}
            label={name.replace("survival-", "").toUpperCase()}
            value={state}
            warn={state !== "active"}
          />
        ))}
      </dl>
    </div>
  );
}

export function StatusPage({ onPower }: { onPower: () => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    const refresh = () =>
      getStatus()
        .then((next) => { if (active) { setStatus(next); setFailed(false); } })
        .catch(() => { if (active) setFailed(true); });
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => { active = false; clearInterval(timer); };
  }, []);

  return (
    <>
      {failed && <p role="alert" className="warn">Backend unavailable. Retrying.</p>}
      {status ? <Report status={status} /> : !failed && <p>Reading system status</p>}
      <button className="big-button" onClick={onPower}>Power and maintenance</button>
    </>
  );
}
