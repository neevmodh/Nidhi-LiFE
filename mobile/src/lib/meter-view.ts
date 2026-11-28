// Pure helpers for the live-meter screens: formatting, India-time hours, chart geometry. No React, so they are tested.
import type { MeterPoint } from "@/lib/api";

const IST_MS = 5.5 * 3_600_000;

/** Hour of day (0-23.99) in India time for an ISO timestamp. */
export function istHour(iso: string): number {
  const d = new Date(new Date(iso).getTime() + IST_MS);
  return d.getUTCHours() + d.getUTCMinutes() / 60;
}

/** "6:30 PM" in India time. */
export function istClock(iso: string): string {
  const d = new Date(new Date(iso).getTime() + IST_MS);
  const h = d.getUTCHours();
  const m = d.getUTCMinutes();
  return `${h % 12 === 0 ? 12 : h % 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

export const kw = (n: number): string => `${Math.abs(n) < 10 ? n.toFixed(2) : n.toFixed(1)} kW`;
export const kwh = (n: number): string => `${n < 10 ? n.toFixed(1) : Math.round(n).toLocaleString("en-IN")} kWh`;

/** Where the home is drawing power from right now. */
export function flow(loadKw: number, pvKw: number): "importing" | "exporting" | "balanced" {
  const net = loadKw - pvKw;
  if (Math.abs(net) < 0.02) return "balanced";
  return net > 0 ? "importing" : "exporting";
}

export interface ChartGeometry {
  load: string; // SVG path
  pv: string;
  max: number; // kW at the top of the chart
  peak: [number, number] | null; // x range (0-1) of the evening peak that falls inside the data
  sun: [number, number] | null;
  hours: { x: number; label: string }[]; // x positions (0-1) for axis labels
}

/** Paths for two series over the same time span, scaled to width x height, plus the shaded hour bands. */
export function chartGeometry(points: MeterPoint[], width: number, height: number, peak: [number, number], sun: [number, number]): ChartGeometry {
  if (points.length < 2) return { load: "", pv: "", max: 1, peak: null, sun: null, hours: [] };
  const t0 = new Date(points[0].ts).getTime();
  const t1 = new Date(points[points.length - 1].ts).getTime();
  const span = Math.max(t1 - t0, 1);
  const peakValue = Math.max(...points.map((p) => Math.max(p.load_kw, p.pv_kw)), 0.5);
  const max = Math.ceil(peakValue * 1.15 * 2) / 2;
  const x = (ts: string) => ((new Date(ts).getTime() - t0) / span) * width;
  const y = (v: number) => height - (v / max) * height;
  const path = (pick: (p: MeterPoint) => number) =>
    points.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.ts).toFixed(1)} ${y(pick(p)).toFixed(1)}`).join(" ");

  // Shade an hour band wherever it falls within the span (the span is 24 h, so it falls once or twice).
  const band = (from: number, to: number): [number, number] | null => {
    const first = new Date(t0 + IST_MS);
    const dayStart = Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), first.getUTCDate()) - IST_MS;
    for (const day of [dayStart, dayStart + 86_400_000]) {
      const a = day + from * 3_600_000;
      const b = day + to * 3_600_000;
      if (b > t0 && a < t1) return [Math.max(a - t0, 0) / span, Math.min(b - t0, span) / span];
    }
    return null;
  };

  const hours: { x: number; label: string }[] = [];
  for (let h = 0; h < 48; h += 6) {
    const first = new Date(t0 + IST_MS);
    const ts = Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), first.getUTCDate()) - IST_MS + h * 3_600_000;
    if (ts > t0 && ts < t1) hours.push({ x: (ts - t0) / span, label: `${h % 24}:00` });
  }
  return { load: path((p) => p.load_kw), pv: path((p) => p.pv_kw), max, peak: band(peak[0], peak[1]), sun: band(sun[0], sun[1]), hours };
}
