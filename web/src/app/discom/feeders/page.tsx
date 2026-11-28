"use client";

// Feeders: load against rating for each 11 kV feeder; pick one to see its day. "Above 90th percentile" is how
// far the worst quarter-hour of the week sits over a normal peak, which is what moving heavy loads could trim.
import { useState } from "react";
import { DemandChart } from "@/components/discom/DemandChart";
import { useDiscom } from "@/components/discom/DiscomContext";
import { Badge, ErrorNote, ProgressBar, Spinner, fmt, useLoad } from "@/components/ui";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";

// Keyed by feeder where it is used, so choosing another one loads that feeder's day.
function FeederDay({ feeder, discom }: { feeder: string; discom: string }) {
  const series = useLoad(() => api.discomFeederSeries(feeder, discom));
  if (series.loading && !series.data) return <Spinner />;
  if (series.error) return <ErrorNote message={series.error} />;
  return <DemandChart data={series.data ?? []} />;
}

export default function FeedersPage() {
  const { t } = useI18n();
  const { discom } = useDiscom();
  const feeders = useLoad(() => api.discomFeeders(discom));
  const [picked, setPicked] = useState<string | null>(null);
  const rows = feeders.data ?? [];
  const feeder = picked ?? rows[0]?.feeder ?? null;
  const select = (f: string) => setPicked(f);

  if (feeders.error) return <ErrorNote message={feeders.error} />;
  if (feeders.loading && !feeders.data) return <Spinner />;
  if (!rows.length) return <p className="rounded-3xl bg-surface p-6 text-muted shadow-[var(--shadow)]">{t("dc.f.empty")}</p>;

  return (
    <div className="space-y-6">
      <section className="overflow-x-auto rounded-3xl bg-surface shadow-[var(--shadow)]">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-muted">
            <tr>
              {(["dc.f.feeder", "dc.f.homes", "dc.f.rated", "dc.f.load", "dc.f.util", "dc.f.peak", "dc.f.shave", "dc.f.peakHour"] as const).map((k) => (
                <th key={k} className="px-4 py-3 font-semibold">{t(k)}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((r) => (
              <tr key={r.feeder} aria-selected={r.feeder === feeder}
                className={`cursor-pointer hover:bg-bg ${r.feeder === feeder ? "bg-brand-soft/40" : ""}`} onClick={() => select(r.feeder)}>
                <td className="px-4 py-3 font-semibold">
                  <button className="text-left" onClick={() => select(r.feeder)}>{r.feeder}</button>
                </td>
                <td className="num px-4 py-3">{fmt.int(r.meters)}</td>
                <td className="num px-4 py-3">{r.rated_kw} kW</td>
                <td className="num px-4 py-3">{r.load_kw} kW</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="w-20"><ProgressBar value={r.utilisation_pct} tone={r.hot ? "sun" : "brand"} /></div>
                    <span className="num">{r.utilisation_pct}%</span>
                    <Badge tone={r.hot ? "danger" : "muted"}>{t(r.hot ? "dc.f.hot" : "dc.f.ok")}</Badge>
                  </div>
                </td>
                <td className="num px-4 py-3">{r.peak_kw_week} kW</td>
                <td className="num px-4 py-3">{r.peak_over_p90_kw} kW</td>
                <td className="num px-4 py-3">{r.peak_hour === null ? "–" : `${String(r.peak_hour).padStart(2, "0")}:00`}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="px-4 pb-4 text-xs text-muted">{t("dc.f.shaveNote")}</p>
      </section>

      <section className="rounded-3xl bg-surface p-5 shadow-[var(--shadow)] sm:p-6">
        <h2 className="mb-3 text-lg font-bold">{feeder ? `${feeder} · ${t("dc.f.chart")}` : t("dc.f.pick")}</h2>
        {feeder && <FeederDay key={feeder} feeder={feeder} discom={discom} />}
      </section>
    </div>
  );
}
