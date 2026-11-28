"use client";

// Solar requests: households in this company's area asking for a rooftop survey. Each is a net-metering
// connection the DISCOM can expect, with the feeder it will land on.
import { useDiscom } from "@/components/discom/DiscomContext";
import { Badge, ErrorNote, Spinner, fmt, useLoad } from "@/components/ui";
import { dateTag, useI18n } from "@/i18n";
import { api } from "@/lib/api";

export default function LeadsPage() {
  const { t } = useI18n();
  const { discom } = useDiscom();
  const leads = useLoad(() => api.discomLeads(discom));
  if (leads.error) return <ErrorNote message={leads.error} />;
  if (leads.loading && !leads.data) return <Spinner />;
  if (!leads.data?.length) return <p className="rounded-3xl bg-surface p-6 text-muted shadow-[var(--shadow)]">{t("dc.l.empty")}</p>;
  return (
    <section className="overflow-x-auto rounded-3xl bg-surface shadow-[var(--shadow)]">
      <table className="w-full min-w-[560px] text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-muted">
          <tr>{(["dc.l.kwp", "dc.l.units", "dc.l.feeder", "dc.l.status"] as const).map((k) => <th key={k} className="px-4 py-3 font-semibold">{t(k)}</th>)}<th className="px-4 py-3" /></tr>
        </thead>
        <tbody className="divide-y divide-border">
          {leads.data.map((l) => (
            <tr key={l.id}>
              <td className="num px-4 py-3 font-semibold">{l.kwp} kWp</td>
              <td className="num px-4 py-3">{fmt.int(l.monthly_kwh)} kWh</td>
              <td className="px-4 py-3">{l.feeder ?? "–"}</td>
              <td className="px-4 py-3"><Badge tone="sun">{l.status.replace("_", " ")}</Badge></td>
              <td className="px-4 py-3 text-xs text-muted">{new Date(l.created_at).toLocaleDateString(dateTag(), { dateStyle: "medium" })}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
