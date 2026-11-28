// Society energy: the society's smart meters added together. Totals only; nothing shows until enough homes have
// meters that no single home can be picked out of the numbers.
import Ionicons from "@expo/vector-icons/Ionicons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { usePageWidth } from "@/components/layout";
import { MeterChart } from "@/components/meter-chart";
import { Rise } from "@/components/motion";
import { ErrorText } from "@/components/ui";
import { useI18n } from "@/i18n";
import { api, ApiError } from "@/lib/api";
import { kw, kwh } from "@/lib/meter-view";
import { shadow, space, type, useColors } from "@/theme";

export default function SocietyEnergy() {
  const { t } = useI18n();
  const c = useColors();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const page = usePageWidth(true);
  const q = useQuery({ queryKey: ["society-energy"], queryFn: api.societyEnergy, refetchInterval: 60_000 });
  const d = q.data;
  const noSociety = q.error instanceof ApiError && q.error.status === 404;

  return (
    <View style={{ flex: 1, backgroundColor: c.background }}>
      <ScrollView
        contentContainerStyle={[styles.page, page, { paddingTop: insets.top + space.md }]}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => void q.refetch()} />}
      >
        <View style={styles.top}>
          <Pressable accessibilityRole="button" accessibilityLabel={t("common.back")} onPress={() => (router.canGoBack() ? router.back() : router.navigate("/live"))} style={[styles.back, { borderColor: c.border, backgroundColor: c.surface }]}>
            <Ionicons name="chevron-back" size={20} color={c.text} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={[type.title, { color: c.text, fontSize: 24 }]}>{t("senergy.title")}</Text>
            <Text style={[type.small, { color: c.muted }]}>{t("senergy.sub")}</Text>
          </View>
        </View>

        {noSociety && <Text style={[type.body, { color: c.muted }]}>{t("senergy.none")}</Text>}
        {q.isError && !noSociety && <ErrorText>{t("mobile.serverDown")}</ErrorText>}

        {d && !d.visible && (
          <View style={[styles.card, { backgroundColor: c.saffronSoft }]}>
            <Text style={[type.body, { color: c.saffronInk }]}>{t("senergy.hidden", { need: d.min_group_size, have: d.homes })}</Text>
          </View>
        )}

        {d?.visible && (
          <>
            <Rise index={0} style={[styles.card, shadow, { backgroundColor: c.surface }]}>
              <Text style={[type.eyebrow, { color: c.muted }]}>{t("senergy.homes", { n: d.homes })}</Text>
              <Text style={[type.number, { color: c.text }]}>{kw(d.load_kw)}</Text>
              <Text style={[type.small, { color: c.muted }]}>{t("senergy.withSolar", { n: d.homes_with_solar })}</Text>
              <View style={styles.split}>
                <View style={[styles.flow, { backgroundColor: c.saffronSoft }]}>
                  <Text style={[type.small, { color: c.saffronInk }]}>{t("live.solar")}</Text>
                  <Text style={[type.heading, { color: c.saffronInk }]}>{kw(d.pv_kw)}</Text>
                </View>
                <View style={[styles.flow, { backgroundColor: c.greenSoft }]}>
                  <Text style={[type.small, { color: c.greenDeep }]}>{t("senergy.spare")}</Text>
                  <Text style={[type.heading, { color: c.greenDeep }]}>{kw(d.spare_solar_kw)}</Text>
                </View>
              </View>
            </Rise>

            <Rise index={1} style={[styles.card, shadow, { backgroundColor: c.surface }]}>
              <Text style={[type.heading, { color: c.text }]}>{t("live.today")}</Text>
              <View style={styles.grid}>
                <Cell label={t("live.imported")} value={kwh(d.import_today_kwh)} />
                <Cell label={t("live.exported")} value={kwh(d.export_today_kwh)} />
                <Cell label={t("live.solarShare")} value={`${d.solar_share_pct}%`} />
                <Cell label={t("live.co2")} value={`${d.co2_today_kg} kg`} />
              </View>
            </Rise>

            <Rise index={2} style={[styles.card, shadow, { backgroundColor: c.surface }]}>
              <Text style={[type.heading, { color: c.text }]}>{t("live.chart")}</Text>
              <MeterChart points={d.series} peak={[18, 22]} sun={[9, 17]} />
            </Rise>
          </>
        )}
      </ScrollView>
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

const styles = StyleSheet.create({
  page: { padding: space.lg, gap: space.lg, paddingBottom: 120 },
  top: { flexDirection: "row", alignItems: "center", gap: space.md },
  back: { width: 40, height: 40, borderRadius: 20, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  card: { borderRadius: 22, padding: space.lg, gap: space.sm },
  split: { flexDirection: "row", gap: space.sm, marginTop: space.xs },
  flow: { flex: 1, borderRadius: 16, padding: space.md, gap: 2 },
  grid: { flexDirection: "row", flexWrap: "wrap", rowGap: space.md },
  cell: { width: "50%", gap: 2 },
});
