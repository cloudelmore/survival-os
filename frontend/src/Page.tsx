import type { ReactNode } from "react";
import { PixelIcon } from "./icons";

export function Page({ id, title, onBack, children }: {
  id: string;
  title: string;
  onBack: () => void;
  children: ReactNode;
}) {
  return (
    <div className="screen">
      <header className="page-header">
        <PixelIcon name={id} size={36} />
        <h1>{title}</h1>
        <button className="link-button" onClick={onBack} autoFocus>[ESC] BACK</button>
      </header>
      <main className="page-body">{children}</main>
    </div>
  );
}
