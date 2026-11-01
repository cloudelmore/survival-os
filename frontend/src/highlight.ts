const escape = (term: string) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// Marks text nodes in place, so a sanitised document is never rebuilt from strings.
export function markTerms(root: HTMLElement, terms: string[]): HTMLElement[] {
  const words = terms.filter(Boolean).map(escape);
  if (!words.length) return [];
  const pattern = new RegExp(`(?<![\\p{L}\\p{N}])(?:${words.join("|")})(?![\\p{L}\\p{N}])`, "giu");
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);

  const marks: HTMLElement[] = [];
  for (const node of nodes) {
    const text = node.data;
    const matches = [...text.matchAll(pattern)];
    if (!matches.length) continue;
    const fragment = document.createDocumentFragment();
    let position = 0;
    for (const match of matches) {
      fragment.append(text.slice(position, match.index));
      const mark = document.createElement("mark");
      mark.textContent = match[0];
      fragment.append(mark);
      marks.push(mark);
      position = match.index + match[0].length;
    }
    fragment.append(text.slice(position));
    node.replaceWith(fragment);
  }
  return marks;
}
