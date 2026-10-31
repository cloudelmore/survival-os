export type Section = {
  id: string;
  title: string;
  summary: string;
  phase?: number;
};

// Menu order sets the number keys: 1 to 9, then 0 for the tenth section.
export const SECTIONS: Section[] = [
  { id: "knowledge", title: "Knowledge", summary: "Encyclopedias and reference archives.", phase: 5 },
  { id: "medical", title: "Medical", summary: "First aid, medicine and sanitation references.", phase: 5 },
  { id: "navigation", title: "Navigation", summary: "Offline maps, waypoints and GPX routes.", phase: 6 },
  { id: "engineering", title: "Engineering", summary: "Electrical, solar, battery and repair references.", phase: 5 },
  { id: "food-water", title: "Food & Water", summary: "Agriculture, water treatment and food safety.", phase: 5 },
  { id: "communications", title: "Communications", summary: "Ham radio, emergency communications and LAN sharing.", phase: 5 },
  { id: "offline-ai", title: "Offline AI", summary: "Optional local answers with cited sources.", phase: 7 },
  { id: "library-search", title: "Library Search", summary: "Full-text search across your documents.", phase: 4 },
  { id: "content-manager", title: "Content Manager", summary: "Install, update and remove collections.", phase: 5 },
  { id: "system-status", title: "System Status", summary: "Temperature, memory, storage and services." },
];

export const keyForIndex = (index: number) => String((index + 1) % 10);
