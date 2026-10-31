import { useEffect, useState } from "react";

type Health = { status: string; version: string };

// Foundation placeholder only. The dashboard and its visual design arrive in Phase 3.
export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetch("/api/health")
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then(setHealth)
      .catch(() => setFailed(true));
  }, []);

  return (
    <main style={{ fontFamily: "monospace", padding: "2rem" }}>
      <h1>SURVIVAL OS</h1>
      {failed && <p role="alert">Backend unavailable</p>}
      {health && (
        <p>
          Backend {health.status}, version {health.version}
        </p>
      )}
      {!failed && !health && <p>Checking backend</p>}
    </main>
  );
}
