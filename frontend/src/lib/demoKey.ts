// Key of a recorded GET response in the static demo (shared by the recorder and the app).
export function normalizeUrl(url: string): string {
  const [path = "", query = ""] = url.split("?", 2);
  const params = new URLSearchParams(query);
  const sorted = [...params.entries()].sort(([a, x], [b, y]) =>
    a === b ? x.localeCompare(y) : a.localeCompare(b),
  );
  const q = new URLSearchParams(sorted).toString();
  return q ? `${path}?${q}` : path;
}

export function demoKey(url: string): string {
  // FNV-1a, 32 bit, twice with different seeds -> 16 hex characters.
  const text = normalizeUrl(url);
  let h1 = 0x811c9dc5;
  let h2 = 0x01000193 ^ 0x5bd1e995;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0;
    h2 = Math.imul(h2 ^ c, 0x01000193) >>> 0;
  }
  return h1.toString(16).padStart(8, "0") + h2.toString(16).padStart(8, "0");
}
