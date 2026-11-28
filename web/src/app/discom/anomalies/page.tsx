"use client";

// Anomalies: meters whose register went backwards or whose bill disagrees with the meter. Households appear by
// meter number and feeder only. Engineers resolve; auditors read.
import { useState } from "react";
import { useDiscom } from "@/components/discom/DiscomContext";
import { Badge, Button, ErrorNote, Spinner, useLoad } from "@/components/ui";
import { dateTag, useI18n } from "@/i18n";
import { api, type DiscomFlag } from "@/lib/api";

const KIND = {
  register_rollback: "dc.a.kind.register_rollback",
  bill_mismatch: "dc.a.kind.bill_mismatch",
  night_spike: "dc.a.kind.night_spike",
} as const;

function List({ state }: { state: "open" | "resolved" | "all" }) {
  const { t } = useI18n();
  const { discom, canEdit, refresh } = useDiscom();
  const flags = useLoad(() => api.discomAnomalies(state, discom));
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function resolve(f: DiscomFlag) {
    setBusy(f.id);
    setError(null);
    try {
      await api.discomResolve(f.id);
      await Promise.all([flags.reload(), refresh()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setBusy(null);
    }
  }

  if (flags.error) return <ErrorNote message={flags.error} />;
  if (flags.loading && !flags.data) return <Spinner />;
  if (!flags.data?.length) return <p className="rounded-3xl bg-surface p-6 text-muted shadow-[var(--shadow)]">{t("dc.a.empty")}</p>;
  return (
    <>
      <ErrorNote message={error} />
      <ul className="divide-y divide-border rounded-3xl bg-surface shadow-[var(--shadow)]">
        {flags.data.map((f) => (
          <li key={f.id} className="flex flex-wrap items-center gap-4 p-5">
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-center gap-2 font-semibold">
                {t(KIND[f.kind])}
                <Badge tone={f.status === "open" ? "danger" : "muted"}>{t(f.status === "open" ? "dc.a.open" : "dc.a.resolved")}</Badge>
              </p>
              <p className="mt-1 text-sm text-muted">{f.detail}</p>
              <p className="mt-1 text-xs text-muted">
                {t("dc.a.meter")} {f.meter} · {f.feeder} · {t("dc.a.raised")} {new Date(f.created_at).toLocaleString(dateTag(), { dateStyle: "medium", timeStyle: "short" })}
              </p>
            </div>
            {canEdit && f.status === "open" && (
              <Button variant="ghost" disabled={busy === f.id} onClick={() => void resolve(f)}>{t("dc.a.resolve")}</Button>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

export default function AnomaliesPage() {
  const { t } = useI18n();
  const [state, setState] = useState<"open" | "resolved" | "all">("open");
  return (
    <div className="space-y-4">
      <div role="tablist" className="flex gap-1">
        {(["open", "resolved", "all"] as const).map((s) => (
          <button key={s} role="tab" aria-selected={state === s} onClick={() => setState(s)}
            className={`rounded-full px-4 py-2 text-sm font-semibold ${state === s ? "bg-navy text-[#f6f2ea]" : "bg-surface text-muted hover:bg-surface-2"}`}>
            {t(`dc.a.${s}` as const)}
          </button>
        ))}
      </div>
      <List key={state} state={state} />
    </div>
  );
}
