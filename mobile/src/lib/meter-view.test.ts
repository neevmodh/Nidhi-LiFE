import { describe, expect, it } from "vitest";

import { chartGeometry, flow, istClock, istHour, istStamp, kw, kwh } from "./meter-view";

describe("India time", () => {
  it("reads UTC timestamps as IST", () => {
    expect(istHour("2026-11-28T06:30:00Z")).toBe(12);
    expect(istClock("2026-11-28T06:30:00Z")).toBe("12:00 PM");
    expect(istClock("2026-11-28T13:00:00Z")).toBe("6:30 PM");
    expect(istClock("2026-11-28T18:30:00Z")).toBe("12:00 AM");
  });
});

describe("formatting", () => {
  it("keeps small numbers precise and large ones short", () => {
    expect(kw(0.456)).toBe("0.46 kW");
    expect(kw(12.34)).toBe("12.3 kW");
    expect(kwh(4.25)).toBe("4.3 kWh");
    expect(kwh(1234)).toBe("1,234 kWh");
  });
});

describe("flow", () => {
  it("says which way power moves", () => {
    expect(flow(1.2, 0)).toBe("importing");
    expect(flow(0.4, 2)).toBe("exporting");
    expect(flow(1, 1.01)).toBe("balanced");
  });
});

describe("chartGeometry", () => {
  const day = Array.from({ length: 96 }, (_, i) => ({
    ts: new Date(Date.UTC(2026, 10, 27, 7, 0) + i * 900_000).toISOString(),
    load_kw: 0.5 + (i % 8) * 0.1,
    pv_kw: i > 20 && i < 50 ? 2 : 0,
  }));

  it("needs two points", () => {
    expect(chartGeometry(day.slice(0, 1), 300, 100, [18, 22], [9, 17]).load).toBe("");
  });

  it("draws both series inside the box and scales to the largest value", () => {
    const g = chartGeometry(day, 300, 100, [18, 22], [9, 17]);
    expect(g.load.startsWith("M0.0")).toBe(true);
    expect(g.max).toBeGreaterThanOrEqual(2);
    const ys = [...g.pv.matchAll(/ (\d+\.\d)/g)].map((m) => Number(m[1]));
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...ys)).toBeLessThanOrEqual(100);
  });

  it("shades the evening peak and the sun hours once each, in 0-1 of the width", () => {
    const g = chartGeometry(day, 300, 100, [18, 22], [9, 17]);
    for (const band of [g.peak, g.sun]) {
      expect(band).not.toBeNull();
      expect(band![0]).toBeGreaterThanOrEqual(0);
      expect(band![1]).toBeLessThanOrEqual(1);
      expect(band![1]).toBeGreaterThan(band![0]);
    }
    expect(g.hours.length).toBeGreaterThan(2);
  });
});

describe("istStamp", () => {
  const now = new Date("2026-11-28T06:30:00Z"); // 12:00 noon in India
  it("shows only the time for today", () => {
    expect(istStamp("2026-11-28T13:00:00Z", now)).toBe("6:30 PM");
  });
  it("adds the day for another day, in India time", () => {
    expect(istStamp("2026-11-29T06:49:00Z", now)).toMatch(/^Sun,? 29 Nov,? 12:19 PM$/);
    // 11 PM in India on the 28th is still the 28th; 1 AM on the 29th is the next day.
    expect(istStamp("2026-11-28T17:30:00Z", now)).toBe("11:00 PM");
    expect(istStamp("2026-11-28T19:30:00Z", now)).toMatch(/29 Nov, 1:00 AM$/);
  });
});
