"use client";

// Outages: plan a cut for a feeder and every household on it is notified in the app; cancel one that is no
// longer needed. Auditors and the state team can see outages but not plan them.
import { useState } from "react";
import { useDiscom } from "@/components/discom/DiscomContext";
import { Button, ErrorNote, Field, Spinner, inputClass, useLoad } from "@/components/ui";
import { dateTag, useI18n } from "@/i18n";
import { api } from "@/lib/api";

/** "2026-11-30T14:00" from a datetime-local box means India time. */
const istToIso = (local: string) => new Date(`${local}:00+05:30`).toISOString();
const when = (iso: string) => new Date(iso).toLocaleString(dateTag(), { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" });

export default function OutagesPage() {
  const { t } = useI18n();
  const { discom, canEdit, refresh } = useDiscom();
  const outages = useLoad(() => api.discomOutages(discom));
  const feeders = useLoad(() => api.discomFeeders(discom));
  const [f, setF] = useState({ feeder: "", reason: "", from: "", to: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const options = feeders.data ?? [];
  const feeder = f.feeder || options[0]?.feeder || "";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.discomRaiseOutage({ feeder, reason: f.reason, starts_at: istToIso(f.from), ends_at: istToIso(f.to) });
      setF({ feeder: "", reason: "", from: "", to: "" });
      await Promise.all([outages.reload(), refresh()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.error"));
    } finally {
      setBusy(false);
    }
  }

  async function cancel(id: number) {
    setError(null);
    try {
      await api.discomCancelOutage(id);
      await Promise.all([outages.reload(), refresh()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.error"));
    }
  }

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[380px_1fr]">
      {canEdit ? (
        <form onSubmit={submit} className="space-y-4 rounded-3xl bg-surface p-5 shadow-[var(--shadow)] sm:p-6">
          <h2 className="text-lg font-bold">{t("dc.o.new")}</h2>
          <Field label={t("dc.o.feeder")}>
            <select className={inputClass} value={feeder} onChange={(e) => setF({ ...f, feeder: e.target.value })} required>
              {options.map((o) => <option key={o.feeder} value={o.feeder}>{o.feeder} ({o.meters})</option>)}
            </select>
          </Field>
          <Field label={t("dc.o.reason")}>
            <input className={inputClass} value={f.reason} maxLength={200} minLength={3} required placeholder={t("dc.o.reasonPh")}
              onChange={(e) => setF({ ...f, reason: e.target.value })} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("dc.o.from")}><input type="datetime-local" className={inputClass} value={f.from} required onChange={(e) => setF({ ...f, from: e.target.value })} /></Field>
            <Field label={t("dc.o.to")}><input type="datetime-local" className={inputClass} value={f.to} required onChange={(e) => setF({ ...f, to: e.target.value })} /></Field>
          </div>
          <ErrorNote message={error} />
          <Button type="submit" disabled={busy || !feeder} className="w-full">{t("dc.o.submit")}</Button>
        </form>
      ) : (
        <p className="rounded-3xl bg-surface p-6 text-sm text-muted shadow-[var(--shadow)]">{t("dc.o.readOnly")}</p>
      )}

      <section>
        {outages.error && <ErrorNote message={outages.error} />}
        {outages.loading && !outages.data ? <Spinner /> : !outages.data?.length ? (
          <p className="rounded-3xl bg-surface p-6 text-muted shadow-[var(--shadow)]">{t("dc.o.empty")}</p>
        ) : (
          <ul className="divide-y divide-border rounded-3xl bg-surface shadow-[var(--shadow)]">
            {outages.data.map((o) => (
              <li key={o.id} className="flex flex-wrap items-center gap-4 p-5">
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">{o.feeder} · {o.reason}</p>
                  <p className="mt-1 text-sm text-muted">{when(o.starts_at)} → {when(o.ends_at)} · {t("dc.o.homes", { n: o.households })}</p>
                </div>
                {canEdit && <Button variant="ghost" onClick={() => void cancel(o.id)}>{t("dc.o.cancel")}</Button>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
