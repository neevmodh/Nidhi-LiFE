"use client";

// Overview: demand and solar right now, units today, what needs attention, and the day's curve.
import Link from "next/link";
import { DemandChart } from "@/components/discom/DemandChart";
import { useDiscom } from "@/components/discom/DiscomContext";
import { DiscomIcon, type DiscomPageId } from "@/components/discom/nav";
import { ErrorNote, Spinner, Stat, fmt, useLoad } from "@/components/ui";
import { useI18n, type MessageKey } from "@/i18n";
import { api } from "@/lib/api";

function Attention({ id, href, n, label }: { id: DiscomPageId; href: string; n: number; label: MessageKey }) {
  const { t } = useI18n();
  return (
    <Link href={href} className={`flex items-center gap-4 rounded-3xl p-5 shadow-[var(--shadow)] transition hover:-translate-y-0.5 ${n ? "bg-sun-soft" : "bg-surface"}`}>
      <span className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl ${n ? "bg-sun text-text" : "bg-surface-2 text-muted"}`}><DiscomIcon id={id} /></span>
      <span className="min-w-0 flex-1">
        <span className="num block text-2xl font-bold">{fmt.int(n)}</span>
        <span className="block text-sm text-muted">{t(label, { n: fmt.int(n) })}</span>
      </span>
      <span aria-hidden className="text-muted">→</span>
    </Link>
  );
}

const kw = (n: number) => `${n.toFixed(n < 10 ? 1 : 0)} kW`;
const kwh = (n: number) => `${Math.round(n).toLocaleString("en-IN")} kWh`;

export default function DiscomOverview() {
  const { t } = useI18n();
  const { discom, overview: o, error } = useDiscom();
  const series = useLoad(() => api.discomSeries(discom));
  if (error) return <ErrorNote message={error} />;
  if (!o) return <Spinner />;

  return (
    <div className="space-y-6" data-discom={discom}>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat tone="brand" label={t("dc.kpi.meters")} value={fmt.int(o.meters)} />
        <Stat tone="sky" label={t("dc.kpi.load")} value={kw(o.load_kw)} hint={`${t("dc.kpi.peak")}: ${kw(o.peak_kw_today)}`} />
        <Stat tone="sun" label={t("dc.kpi.pv")} value={kw(o.pv_kw)} />
        <Stat label={t("dc.kpi.grid")} value={kw(o.grid_kw)} />
        <Stat label={t("dc.kpi.import")} value={kwh(o.import_today_kwh)} />
        <Stat label={t("dc.kpi.export")} value={kwh(o.export_today_kwh)} />
        <Stat label={t("dc.kpi.co2")} value={fmt.kg(o.co2_today_kg)} />
      </div>

      <section aria-labelledby="att">
        <h2 id="att" className="mb-3 text-sm font-bold uppercase tracking-wide text-muted">{t("dc.attention")}</h2>
        <div className="grid gap-4 md:grid-cols-3">
          <Attention id="anomalies" href="/discom/anomalies" n={o.open_flags} label="dc.att.flags" />
          <Attention id="outages" href="/discom/outages" n={o.active_outages} label="dc.att.outages" />
          <Attention id="leads" href="/discom/leads" n={o.solar_leads} label="dc.att.leads" />
        </div>
      </section>

      <section className="rounded-3xl bg-surface p-5 shadow-[var(--shadow)] sm:p-6">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-lg font-bold">{t("dc.curve")}</h2>
          <button onClick={() => void series.reload()} className="rounded-full bg-surface-2 px-3 py-1 text-xs font-semibold hover:bg-border">{t("con.refresh")}</button>
        </div>
        {series.loading && !series.data ? <Spinner /> : series.error ? <ErrorNote message={series.error} /> : <DemandChart data={series.data ?? []} />}
      </section>
    </div>
  );
}
