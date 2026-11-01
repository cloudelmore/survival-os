import { useEffect, useRef, useState } from "react";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "Clear", "0", "Del"];
const MIN_PIN = 4;
const MAX_PIN = 8;

// Content changes reuse the admin PIN. It is set from the power dialog, on first use.
export function PinPrompt({ title, onSubmit, onClose }: {
  title: string;
  onSubmit: (pin: string) => Promise<void>;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { dialog.current?.showModal(); }, []);

  const press = (key: string) => {
    setError("");
    if (key === "Clear") setPin("");
    else if (key === "Del") setPin(pin.slice(0, -1));
    else if (pin.length < MAX_PIN) setPin(pin + key);
  };

  const submit = async () => {
    if (pin.length < MIN_PIN || busy) return;
    setBusy(true);
    try {
      await onSubmit(pin);
      onClose();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Request failed");
      setPin("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <dialog ref={dialog} className="power-dialog" onClose={onClose} aria-label={title}>
      <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <h2>{title}</h2>
        <label htmlFor="content-pin">Enter admin PIN</label>
        <input id="content-pin" className="pin-input" type="password" inputMode="numeric"
          autoComplete="off" maxLength={MAX_PIN} value={pin} autoFocus
          onChange={(event) => setPin(event.target.value.replace(/\D/g, ""))} />
        <div className="keypad">
          {KEYS.map((key) => (
            <button key={key} type="button" onClick={() => press(key)}>{key}</button>
          ))}
        </div>
        {error && <p className="notice" role="alert">{error}</p>}
        <div className="catalog-actions">
          <button type="submit" className="link-button" disabled={pin.length < MIN_PIN || busy}>OK</button>
          <button type="button" className="link-button" onClick={onClose}>CANCEL</button>
        </div>
      </form>
    </dialog>
  );
}
