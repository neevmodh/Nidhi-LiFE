"use client";

// Demand and rooftop solar over the last day, every 15 minutes, in India time.
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { dateTag, useI18n } from "@/i18n";
import type { DiscomSeriesPoint } from "@/lib/api";

const SAGE = "#4e7d5e";
const SAFFRON = "#c9873e";
const GRID = "#e7e0d3";
const tick = { fill: "#5f6b63", fontSize: 11 };
const hhmm = (iso: string) => new Date(iso).toLocaleTimeString(dateTag(), { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" });

export function DemandChart({ data, height = 260 }: { data: DiscomSeriesPoint[]; height?: number }) {
  const { t } = useI18n();
  return (
    <div style={{ height }} role="img" aria-label={t("dc.curve")}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="ts" tickFormatter={hhmm} tick={tick} minTickGap={48} axisLine={false} tickLine={false} />
          <YAxis tick={tick} axisLine={false} tickLine={false} unit=" kW" width={64} />
          <Tooltip labelFormatter={(l) => hhmm(String(l))} formatter={(v) => `${Number(v).toFixed(1)} kW`} />
          <Area type="monotone" dataKey="load_kw" name={t("dc.kpi.load")} stroke={SAGE} fill={SAGE} fillOpacity={0.18} strokeWidth={2} dot={false} />
          <Area type="monotone" dataKey="pv_kw" name={t("dc.kpi.pv")} stroke={SAFFRON} fill={SAFFRON} fillOpacity={0.2} strokeWidth={2} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
