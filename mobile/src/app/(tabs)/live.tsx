// Live energy: the household's smart meter right now. Power in use, from the panels and from the grid, today's
// units and CO₂, the last 24 hours, any power cut planned on the feeder, and (on a simulated meter) buttons to
// tell the meter what just ran. Refreshes every 30 seconds. Links to the agent, the meter bill and the society.
import Ionicons from "@expo/vector-icons/Ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { usePageWidth } from "@/components/layout";
import { MeterChart } from "@/components/meter-chart";
import { Rise, tap } from "@/components/motion";
import { Button, ErrorText } from "@/components/ui";
import { useI18n, type MessageKey } from "@/i18n";
import { api, ApiError } from "@/lib/api";
import { flow, istClock, istStamp, kw, kwh } from "@/lib/meter-view";
import { fonts, shadow, space, type, useColors } from "@/theme";

const APPLIANCES = ["washing_machine", "geyser", "ev_charger"] as const;

export default function Live() {
  const { t } = useI18n();
  const c = useColors();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const page = usePageWidth(true);
  const qc = useQueryClient();
  const live = useQuery({ queryKey: ["meter-live"], queryFn: api.meterLive, refetchInterval: 30_000 });
  const ran = useMutation({
    mutationFn: api.meterRan,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["meter-live"] }),
  });
  const d = live.data;
  const direction = d ? flow(d.load_kw, d.pv_kw) : "balanced";
  const gridLabel: MessageKey = direction === "exporting" ? "live.export" : direction === "importing" ? "live.grid" : "live.balanced";

  return (
    <View style={{ flex: 1, backgroundColor: c.background }}>
      <ScrollView
        contentContainerStyle={[styles.page, page, { paddingTop: insets.top + space.md }]}
        refreshControl={<RefreshControl refreshing={live.isRefetching} onRefresh={() => void live.refetch()} />}
      >
        <View style={styles.top}>
          <Pressable accessibilityRole="button" accessibilityLabel={t("common.back")} onPress={() => (router.canGoBack() ? router.back() : router.navigate("/"))} style={[styles.back, { borderColor: c.border, backgroundColor: c.surface }]}>
            <Ionicons name="chevron-back" size={20} color={c.text} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={[type.title, { color: c.text, fontSize: 24 }]}>{t("live.title")}</Text>
            <Text style={[type.small, { color: c.muted }]}>{d?.ts ? `${t("live.sub")} · ${istClock(d.ts)}` : t("live.sub")}</Text>
          </View>
        </View>

        {live.isError && (
          <View style={{ gap: space.sm }}>
            <ErrorText>{live.error instanceof ApiError && live.error.status === 409 ? t("live.noHome") : t("mobile.serverDown")}</ErrorText>
            <Button variant="plain" title={t("live.retry")} onPress={() => void live.refetch()} />
          </View>
        )}

        {d && (
          <>
            <View style={[styles.badge, { backgroundColor: d.meter.simulated ? c.saffronSoft : c.greenSoft }]}>
              <Ionicons name={d.meter.simulated ? "flask-outline" : "hardware-chip-outline"} size={16} color={d.meter.simulated ? c.saffronInk : c.greenDeep} />
              <Text style={[type.small, { color: d.meter.simulated ? c.saffronInk : c.greenDeep, flex: 1 }]}>
                {d.meter.simulated ? `${t("live.sim")}. ${t("live.simHint")}` : t("live.real", { serial: d.meter.serial })}
              </Text>
            </View>

            {d.outages.map((o) => (
              <View key={o.id} style={[styles.badge, { backgroundColor: c.claySoft }]} accessibilityRole="alert">
                <Ionicons name="flash-off-outline" size={16} color={c.clay} />
                <Text style={[type.small, { color: c.clay, flex: 1 }]}>{t("live.outage", { reason: o.reason, from: istStamp(o.starts_at), to: istStamp(o.ends_at) })}</Text>
              </View>
            ))}

            <Rise index={0} style={[styles.hero, shadow, { backgroundColor: c.surface }]}>
              <Text style={[type.eyebrow, { color: c.muted }]}>{t("live.now")}</Text>
              <Text style={[type.number, { color: c.text }]} accessibilityLabel={kw(d.load_kw)}>{kw(d.load_kw)}</Text>
              <View style={styles.split}>
                <Flow icon="sunny-outline" tone={c.saffronInk} bg={c.saffronSoft} label={t("live.solar")} value={kw(d.pv_kw)} />
                <Flow icon="flash-outline" tone={direction === "exporting" ? c.greenDeep : c.sky} bg={direction === "exporting" ? c.greenSoft : c.skySoft} label={t(gridLabel)} value={kw(Math.abs(d.grid_kw))} />
              </View>
            </Rise>

            <Rise index={1} style={[styles.card, shadow, { backgroundColor: c.surface }]}>
              <Text style={[type.heading, { color: c.text }]}>{t("live.today")}</Text>
              <View style={styles.grid}>
                <Cell label={t("live.imported")} value={kwh(d.today.import_kwh)} />
                <Cell label={t("live.exported")} value={kwh(d.today.export_kwh)} />
                <Cell label={t("live.solarShare")} value={`${d.today.solar_share_pct}%`} />
                <Cell label={t("live.co2")} value={`${d.today.co2_kg} kg`} />
              </View>
            </Rise>

            <Rise index={2} style={[styles.card, shadow, { backgroundColor: c.surface }]}>
              <Text style={[type.heading, { color: c.text }]}>{t("live.chart")}</Text>
              <MeterChart points={d.series} peak={d.peak_hours} sun={d.solar_hours} />
            </Rise>

            {d.meter.simulated && (
              <Rise index={3} style={[styles.card, shadow, { backgroundColor: c.surface }]}>
                <Text style={[type.heading, { color: c.text }]}>{t("live.ran")}</Text>
                <Text style={[type.small, { color: c.muted }]}>{t("live.ranHint")}</Text>
                <View style={styles.row}>
                  {APPLIANCES.map((a) => (
                    <Pressable
                      key={a}
                      accessibilityRole="button"
                      disabled={ran.isPending}
                      onPress={() => { tap(); ran.mutate(a); }}
                      style={({ pressed }) => [styles.chip, { borderColor: c.border, backgroundColor: pressed ? c.surfaceAlt : c.surface, opacity: ran.isPending ? 0.5 : 1 }]}
                    >
                      <Text style={[type.small, { color: c.text }]}>{t(`live.app.${a}` as MessageKey)}</Text>
                    </Pressable>
                  ))}
                </View>
                {ran.isSuccess && <Text style={[type.small, { color: c.greenDeep }]}>{t("live.ranOk", { kw: ran.data.kw, min: ran.data.minutes })}</Text>}
                {ran.isError && <ErrorText>{ran.error instanceof ApiError && ran.error.status !== 0 ? ran.error.message : t("mobile.serverDown")}</ErrorText>}
              </Rise>
            )}

            <Rise index={4} style={[styles.links, shadow, { backgroundColor: c.surface }]}>
              <LinkRow icon="sparkles-outline" color={c.greenDeep} label={t("live.agentLink")} onPress={() => router.push("/meter-agent")} />
              <View style={[styles.rule, { backgroundColor: c.border }]} />
              <LinkRow icon="receipt-outline" color={c.saffronInk} label={t("live.billLink")} onPress={() => router.push("/meter-bill")} />
              <View style={[styles.rule, { backgroundColor: c.border }]} />
              <LinkRow icon="people-outline" color={c.sky} label={t("live.societyLink")} onPress={() => router.push("/society-energy")} />
            </Rise>
          </>
        )}
      </ScrollView>
    </View>
  );
}

function Flow({ icon, tone, bg, label, value }: { icon: React.ComponentProps<typeof Ionicons>["name"]; tone: string; bg: string; label: string; value: string }) {
  return (
    <View style={[styles.flow, { backgroundColor: bg }]}>
      <Ionicons name={icon} size={18} color={tone} />
      <Text style={[type.small, { color: tone }]}>{label}</Text>
      <Text style={[type.heading, { color: tone }]}>{value}</Text>
    </View>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  const c = useColors();
  return (
    <View style={styles.cell}>
      <Text style={[type.heading, { color: c.text }]}>{value}</Text>
      <Text style={[type.small, { color: c.muted }]}>{label}</Text>
    </View>
  );
}

function LinkRow({ icon, color, label, onPress }: { icon: React.ComponentProps<typeof Ionicons>["name"]; color: string; label: string; onPress: () => void }) {
  const c = useColors();
  return (
    <Pressable accessibilityRole="link" onPress={onPress} style={({ pressed }) => [styles.link, { opacity: pressed ? 0.7 : 1 }]}>
      <Ionicons name={icon} size={20} color={color} />
      <Text style={[styles.linkText, { color: c.text }]}>{label}</Text>
      <Ionicons name="chevron-forward" size={18} color={c.muted} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  page: { padding: space.lg, gap: space.lg, paddingBottom: 120 },
  top: { flexDirection: "row", alignItems: "center", gap: space.md },
  back: { width: 40, height: 40, borderRadius: 20, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  badge: { flexDirection: "row", alignItems: "center", gap: space.sm, borderRadius: 16, padding: space.md },
  hero: { borderRadius: 22, padding: space.lg, gap: space.sm },
  split: { flexDirection: "row", gap: space.sm, marginTop: space.xs },
  flow: { flex: 1, borderRadius: 16, padding: space.md, gap: 2 },
  card: { borderRadius: 22, padding: space.lg, gap: space.md },
  grid: { flexDirection: "row", flexWrap: "wrap", rowGap: space.md },
  cell: { width: "50%", gap: 2 },
  row: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  chip: { borderWidth: 1, borderRadius: 999, paddingHorizontal: space.md + 2, paddingVertical: space.sm, minHeight: 40, justifyContent: "center" },
  links: { borderRadius: 22, overflow: "hidden" },
  link: { flexDirection: "row", alignItems: "center", gap: space.md, padding: space.lg },
  linkText: { flex: 1, fontFamily: fonts.bodyMedium, fontSize: 15 },
  rule: { height: StyleSheet.hairlineWidth },
});
