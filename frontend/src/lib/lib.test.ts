import { describe, expect, it } from "vitest";
import { query } from "./api";
import { demoKey, normalizeUrl } from "./demoKey";
import { formatNumber, formatRule, unitLabel } from "./i18n";

describe("demo keys", () => {
  it("ignores query parameter order", () => {
    expect(normalizeUrl("/api/v1/results?b=2&a=1")).toBe("/api/v1/results?a=1&b=2");
    expect(demoKey("/api/v1/results?b=2&a=1")).toBe(demoKey("/api/v1/results?a=1&b=2"));
    expect(demoKey("/api/v1/results?a=1")).not.toBe(demoKey("/api/v1/results?a=2"));
    expect(demoKey("/x")).toMatch(/^[0-9a-f]{16}$/);
  });
});

describe("formatting", () => {
  it("formats numbers in Polish and scales", () => {
    expect(formatNumber(2857664)).toBe("2 857 664".replace(/ /g, " "));
    expect(formatNumber(87.7232)).toBe("87,7232");
    expect(formatNumber(431507264, "Mb")).toBe("431,51");
    expect(formatNumber(95966, "kb")).toBe("95,97");
    expect(formatNumber(null)).toBe("–");
  });
  it("renders rules and units", () => {
    expect(formatRule({ min: 80, warn_min: 85 })).toBe("min 80 · warn_min 85");
    expect(unitLabel("percent")).toBe("%");
    expect(unitLabel("bp", "Mb")).toBe("Mb");
  });
  it("builds query strings without empty values", () => {
    expect(query({ run: "R1", verdict: ["PASS", "none"], q: "", page: 2 })).toBe("?run=R1&verdict=PASS&verdict=none&page=2");
  });
});
