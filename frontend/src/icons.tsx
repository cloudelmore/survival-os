// Original 12x12 pixel icons. Each character is one pixel: "." is empty, a letter picks a color.
const COLORS: Record<string, string> = {
  g: "var(--green)",
  o: "var(--orange)",
  p: "var(--purple)",
  b: "var(--blue)",
  w: "var(--white)",
};

const ICONS: Record<string, string[]> = {
  knowledge: [
    "............", ".oooooooooo.", ".owwwwwwwwo.", ".owgggwwwwo.", ".owwwwwwwwo.", ".owggggggwo.",
    ".owwwwwwwwo.", ".owggggggwo.", ".owwwwwwwwo.", ".oooooooooo.", "..oooooooo..", "............",
  ],
  medical: [
    "............", "....oooo....", "....owwo....", "....owwo....", ".ooooooooo..", ".owwwwwwwo..",
    ".owwwwwwwo..", ".ooooooooo..", "....owwo....", "....owwo....", "....oooo....", "............",
  ],
  navigation: [
    "............", "....wwww....", "..ww....ww..", ".w...oo...w.", ".w...oo...w.", "w....oo....w",
    "w...bbbb...w", ".w...bb...w.", ".w...bb...w.", "..ww....ww..", "....wwww....", "............",
  ],
  engineering: [
    "............", "......oo....", ".....oo.....", "....oo......", "...oooooo...", "..oooooo....",
    ".....oo.....", "....oo......", "...oo.......", "..oo........", "..o.........", "............",
  ],
  "food-water": [
    "............", ".....b......", ".....b......", "....bbb.....", "....bbb.....", "...bbbbb....",
    "..bbbwbbb...", "..bbwbbbb...", "..bbwbbbb...", "...bbbbb....", "....bbb.....", "............",
  ],
  communications: [
    "............", "..p......p..", ".p...gg...p.", ".p..g..g..p.", ".p...gg...p.", "..p..gg..p..",
    ".....gg.....", ".....gg.....", "....gggg....", "...gggggg...", "..gggggggg..", "............",
  ],
  "offline-ai": [
    "............", "...gggggg...", "..g......g..", ".g.pp..pp.g.", ".g.pp..pp.g.", ".g........g.",
    ".g..gggg..g.", "..g......g..", "...gggggg...", ".....gg.....", "...gggggg...", "............",
  ],
  "library-search": [
    "............", "...wwww.....", "..w....w....", ".w......w...", ".w......w...", ".w......w...",
    "..w....w....", "...wwwwoo...", "........oo..", ".........oo.", "..........o.", "............",
  ],
  "content-manager": [
    "............", "..pppppppp..", "..pwwwwwwp..", "..pppppppp..", "..pwwwwwwp..", "..pppppppp..",
    "..pwwwwwwp..", "..pppppppp..", ".....gg.....", "...gggggg...", ".....gg.....", "............",
  ],
  "system-status": [
    "............", ".gggggggggg.", ".g........g.", ".g.g......g.", ".g.g..g...g.", ".g.g..g.g.g.",
    ".g.g..g.g.g.", ".g........g.", ".gggggggggg.", ".....gg.....", "...gggggg...", "............",
  ],
};

export function PixelIcon({ name, size = 48 }: { name: string; size?: number }) {
  const rows = ICONS[name];
  return (
    <svg
      className="pixel-icon"
      width={size}
      height={size}
      viewBox="0 0 12 12"
      shapeRendering="crispEdges"
      aria-hidden="true"
    >
      {rows.flatMap((row, y) =>
        [...row].map((cell, x) =>
          cell === "." ? null : (
            <rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" fill={COLORS[cell]} />
          ),
        ),
      )}
    </svg>
  );
}

// An original horizon: hills, pines and a sun, drawn on a 128x10 grid.
export function Horizon() {
  const hills = [2, 3, 4, 5, 5, 4, 3, 2, 2, 3, 3, 4, 6, 7, 7, 6, 5, 4, 3, 3, 2, 2, 3, 4, 4, 5, 6, 5, 4, 3, 2, 2];
  const pines = [14, 15, 52, 88, 90, 118];
  return (
    <svg className="horizon" viewBox="0 0 128 10" preserveAspectRatio="none" aria-hidden="true">
      <g shapeRendering="crispEdges">
        <rect x="104" y="1" width="4" height="4" fill="var(--orange)" />
        {hills.map((height, i) => (
          <rect key={i} x={i * 4} y={10 - height} width="4" height={height} fill="var(--purple-dim)" />
        ))}
        {pines.map((x) => (
          <g key={x} fill="var(--green)">
            <rect x={x} y="4" width="1" height="6" />
            <rect x={x - 1} y="6" width="3" height="3" />
          </g>
        ))}
        <rect x="0" y="9" width="128" height="1" fill="var(--green)" />
      </g>
    </svg>
  );
}
