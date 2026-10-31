import { useEffect, useRef, useState } from "react";
import { getAdminState, runAction, setPin, type Action, type AdminState } from "./api";

const ACTIONS: { id: Action; label: string; done: string }[] = [
  { id: "shutdown", label: "Shut down", done: "Shutting down." },
  { id: "reboot", label: "Reboot", done: "Rebooting." },
  { id: "maintenance", label: "Maintenance mode", done: "Leaving the dashboard for the console." },
];

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "Clear", "0", "Del"];
const MIN_PIN = 4;
const MAX_PIN = 8;

export function PowerDialog({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [admin, setAdmin] = useState<AdminState | null>(null);
  const [action, setAction] = useState<(typeof ACTIONS)[number] | null>(null);
  const [pin, setPinValue] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    dialog.current?.showModal();
    getAdminState().then(setAdmin).catch(() => setError("Backend unavailable"));
  }, []);

  const press = (key: string) => {
    setError("");
    if (key === "Clear") setPinValue("");
    else if (key === "Del") setPinValue(pin.slice(0, -1));
    else if (pin.length < MAX_PIN) setPinValue(pin + key);
  };

  const submit = async () => {
    if (!action || !admin || pin.length < MIN_PIN || busy) return;
    setBusy(true);
    try {
      if (!admin.pin_set) {
        await setPin(pin);
        setAdmin({ ...admin, pin_set: true });
      }
      await runAction(action.id, pin);
      setDone(action.done);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Request failed");
      setPinValue("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <dialog ref={dialog} className="power-dialog" onClose={onClose} aria-label="Power and maintenance">
      {done && <p role="status">{done}</p>}
      {!done && !action && (
        <>
          <h2>Power and maintenance</h2>
          {ACTIONS.map((item) => (
            <button key={item.id} className="big-button" onClick={() => setAction(item)}>
              {item.label}
            </button>
          ))}
        </>
      )}
      {!done && action && admin && (
        <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
          <h2>{action.label}</h2>
          <label htmlFor="pin">
            {admin.pin_set ? "Enter admin PIN" : "Choose an admin PIN, 4 to 8 digits. Write it down."}
          </label>
          <input
            id="pin"
            className="pin-input"
            type="password"
            inputMode="numeric"
            autoComplete="off"
            autoFocus
            value={pin}
            maxLength={MAX_PIN}
            onChange={(event) => setPinValue(event.target.value.replace(/\D/g, ""))}
          />
          <div className="keypad">
            {KEYS.map((key) => (
              <button type="button" key={key} onClick={() => press(key)}>{key}</button>
            ))}
          </div>
          <button className="big-button" type="submit" disabled={pin.length < MIN_PIN || busy}>
            Confirm
          </button>
        </form>
      )}
      {error && <p role="alert" className="warn">{error}</p>}
      {!done && (
        <button className="link-button" onClick={() => dialog.current?.close()}>[ESC] CANCEL</button>
      )}
    </dialog>
  );
}
