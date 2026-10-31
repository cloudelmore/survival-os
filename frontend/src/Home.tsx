import { useEffect, useRef } from "react";
import { Horizon, PixelIcon } from "./icons";
import { keyForIndex, SECTIONS } from "./sections";

const ROWS = 5;

export function Home({ onOpen, onPower, lastSection }: {
  onOpen: (id: string) => void;
  onPower: () => void;
  lastSection: string | null;
}) {
  const items = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    const index = SECTIONS.findIndex((section) => section.id === lastSection);
    items.current[Math.max(index, 0)]?.focus();
  }, [lastSection]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.altKey || event.metaKey) return;
      if (document.querySelector("dialog[open]")) return;
      const digit = SECTIONS.findIndex((_, index) => keyForIndex(index) === event.key);
      if (digit >= 0) {
        event.preventDefault();
        onOpen(SECTIONS[digit].id);
        return;
      }
      if (event.key.toLowerCase() === "p") {
        event.preventDefault();
        onPower();
        return;
      }
      const current = items.current.findIndex((item) => item === document.activeElement);
      if (current < 0) return;
      const move = { ArrowUp: -1, ArrowDown: 1, ArrowLeft: -ROWS, ArrowRight: ROWS }[event.key];
      if (move === undefined) return;
      event.preventDefault();
      const next = current + move;
      if (next >= 0 && next < SECTIONS.length) items.current[next]?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onOpen, onPower]);

  return (
    <div className="screen">
      <header className="masthead">
        <h1>SURVIVAL OS</h1>
        <p>OFFLINE FIELD LIBRARY</p>
      </header>
      <nav className="menu" aria-label="Sections">
        {SECTIONS.map((section, index) => (
          <button
            key={section.id}
            ref={(item) => { items.current[index] = item; }}
            className="menu-item"
            onClick={() => onOpen(section.id)}
          >
            <span className="menu-key">{keyForIndex(index)}</span>
            <PixelIcon name={section.id} />
            <span className="menu-title">{section.title}</span>
          </button>
        ))}
      </nav>
      <Horizon />
      <footer className="footer">
        <span>PRESS A NUMBER, OR ARROWS AND ENTER</span>
        <button className="link-button" onClick={onPower}>[P] POWER</button>
      </footer>
    </div>
  );
}
