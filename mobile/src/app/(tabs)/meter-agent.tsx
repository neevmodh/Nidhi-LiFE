// The energy agent: what it read from the meter and the tariff, its plan ranked by rupees then CO₂, and, for an
// action the meter itself can confirm, a button that logs it as verified with no photo. Its summary may be
// written by AI, but only from the numbers shown here (the server drops it otherwise).
import Ionicons from "@expo/vector-icons/Ionicons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Celebration } from "@/components/celebration";
import { usePageWidth } from "@/components/layout";
import { Rise } from "@/components/motion";
import { Button, ErrorText } from "@/components/ui";
import { useI18n } from "@/i18n";
import { api, ApiError, type MeterRecommendation } from "@/lib/api";
import { shadow, space, type, useColors } from "@/theme";
import { useState } from "react";
import type { CelebrationInfo } from "@/components/celebration";

export default function MeterAgentScreen() {
  const { t } = useI18n();
  const c = useColors();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const page = usePageWidth(true);
  const qc = useQueryClient();
  const agent = useQuery({ queryKey: ["meter-agent"], queryFn: api.meterAgent, staleTime: 60_000 });
  const [celebration, setCelebration] = useState<CelebrationInfo | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const confirm = useMutation({
    mutationFn: () => api.meterConfirm("shift_heavy_load"),
    onSuccess: (log) => {
      setMessage(null);
      setCelebration({ points: log.points_awarded, title: t("agent.confirmed", { points: log.points_awarded }), body: log.action.title, badge: t("celebrate.badgeLogged") });
      void qc.invalidateQueries();
    },
    onError: (e) => {
      // 409: nothing on the meter yet. 429: already counted today. 422: not for this home.
      setMessage(e instanceof ApiError && e.status === 409 ? t("agent.notYet") : e instanceof ApiError && e.status !== 0 ? e.message : t("mobile.serverDown"));
    },
  });

  const d = agent.data;
  return (
    <View style={{ flex: 1, backgroundColor: c.background }}>
      <ScrollView
        contentContainerStyle={[styles.page, page, { paddingTop: insets.top + space.md }]}
        refreshControl={<RefreshControl refreshing={agent.isRefetching} onRefresh={() => void agent.refetch()} />}
      >
        <View style={styles.top}>
          <Pressable accessibilityRole="button" accessibilityLabel={t("common.back")} onPress={() => (router.canGoBack() ? router.back() : router.navigate("/live"))} style={[styles.back, { borderColor: c.border, backgroundColor: c.surface }]}>
            <Ionicons name="chevron-back" size={20} color={c.text} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={[type.title, { color: c.text, fontSize: 24 }]}>{t("agent.title")}</Text>
            <Text style={[type.small, { color: c.muted }]}>{t("agent.sub")}</Text>
          </View>
        </View>

        {agent.isError && <ErrorText>{agent.error instanceof ApiError && agent.error.status === 409 ? t("live.noHome") : t("mobile.serverDown")}</ErrorText>}

        {d && (
          <>
            <Rise index={0} style={[styles.card, { backgroundColor: c.greenSoft, borderColor: c.border }]}>
              <Text style={[type.body, { color: c.text }]}>{d.summary}</Text>
              {d.written_by_ai && <Text style={[type.small, { color: c.muted }]}>{t("agent.ai")}</Text>}
            </Rise>

            <Text style={[type.heading, { color: c.text }]}>{t("agent.recs")}</Text>
            {d.recommendations.length === 0 && <Text style={[type.body, { color: c.muted }]}>{t("agent.empty")}</Text>}
            {d.recommendations.map((r, i) => (
              <Rise key={r.key} index={i + 1}>
                <Recommendation r={r} busy={confirm.isPending} onConfirm={() => confirm.mutate()} />
              </Rise>
            ))}
            {message && <ErrorText>{message}</ErrorText>}

            <Text style={[type.heading, { color: c.text }]}>{t("agent.steps")}</Text>
            <View style={[styles.card, shadow, { backgroundColor: c.surface, borderColor: "transparent" }]}>
              {d.steps.map((s, i) => (
                <View key={s.tool} style={styles.step}>
                  <View style={[styles.num, { backgroundColor: c.greenSoft }]}><Text style={[type.small, { color: c.greenDeep }]}>{i + 1}</Text></View>
                  <Text style={[type.small, { color: c.text, flex: 1 }]}>{s.text}</Text>
                </View>
              ))}
            </View>
          </>
        )}
      </ScrollView>
      <Celebration info={celebration} onClose={() => setCelebration(null)} />
    </View>
  );
}

function Recommendation({ r, busy, onConfirm }: { r: MeterRecommendation; busy: boolean; onConfirm: () => void }) {
  const { t } = useI18n();
  const c = useColors();
  return (
    <View style={[styles.card, shadow, { backgroundColor: c.surface, borderColor: "transparent" }]}>
      <Text style={[type.heading, { color: c.text }]}>{r.title}</Text>
      <Text style={[type.body, { color: c.text }]}>{r.body}</Text>
      <Text style={[type.small, { color: c.greenDeep }]}>
        {r.rs_month > 0 ? t("agent.perMonth", { rs: Math.round(r.rs_month), co2: r.co2_kg_month }) : t("agent.co2only", { co2: r.co2_kg_month })}
      </Text>
      {r.meter_confirmable && (
        <>
          <Text style={[type.small, { color: c.muted }]}>{t("agent.meterOnly")}</Text>
          <Button icon="hardware-chip-outline" title={t("agent.confirm")} busy={busy} onPress={onConfirm} />
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  page: { padding: space.lg, gap: space.lg, paddingBottom: 120 },
  top: { flexDirection: "row", alignItems: "center", gap: space.md },
  back: { width: 40, height: 40, borderRadius: 20, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  card: { borderRadius: 22, borderWidth: 1, padding: space.lg, gap: space.sm },
  step: { flexDirection: "row", alignItems: "flex-start", gap: space.md },
  num: { width: 24, height: 24, borderRadius: 12, alignItems: "center", justifyContent: "center" },
});
