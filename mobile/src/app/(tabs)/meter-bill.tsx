// The bill the meter implies: units so far, the projection to month end, the slab split, the net-metering credit,
// and a check of the meter against what the household told Nidhi, with a ready-to-send letter when they disagree.
import Ionicons from "@expo/vector-icons/Ionicons";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Pressable, RefreshControl, ScrollView, Share, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { usePageWidth } from "@/components/layout";
import { Rise } from "@/components/motion";
import { Button, ErrorText } from "@/components/ui";
import { useI18n } from "@/i18n";
import { api, ApiError } from "@/lib/api";
import { shadow, space, type, useColors } from "@/theme";

const rs = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;

export default function MeterBill() {
  const { t } = useI18n();
  const c = useColors();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const page = usePageWidth(true);
  const bill = useQuery({ queryKey: ["meter-bill"], queryFn: api.meterBill, staleTime: 60_000 });
  const d = bill.data;

  return (
    <View style={{ flex: 1, backgroundColor: c.background }}>
      <ScrollView
        contentContainerStyle={[styles.page, page, { paddingTop: insets.top + space.md }]}
        refreshControl={<RefreshControl refreshing={bill.isRefetching} onRefresh={() => void bill.refetch()} />}
      >
        <View style={styles.top}>
          <Pressable accessibilityRole="button" accessibilityLabel={t("common.back")} onPress={() => (router.canGoBack() ? router.back() : router.navigate("/live"))} style={[styles.back, { borderColor: c.border, backgroundColor: c.surface }]}>
            <Ionicons name="chevron-back" size={20} color={c.text} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={[type.title, { color: c.text, fontSize: 24 }]}>{t("mbill.title")}</Text>
            <Text style={[type.small, { color: c.muted }]}>{d?.simulated ? `${t("live.sim")} · ${t("mbill.sub")}` : t("mbill.sub")}</Text>
          </View>
        </View>

        {bill.isError && <ErrorText>{bill.error instanceof ApiError && bill.error.status === 409 ? t("live.noHome") : t("mobile.serverDown")}</ErrorText>}

        {d && (
          <>
            <Rise index={0} style={[styles.card, shadow, { backgroundColor: c.surface }]}>
              <Text style={[type.eyebrow, { color: c.muted }]}>{t("mbill.projected")}</Text>
              <Text style={[type.number, { color: c.text }]}>{rs(d.projected_bill_rs)}</Text>
              <Text style={[type.small, { color: c.muted }]}>{t("mbill.units", { kwh: Math.round(d.import_kwh), proj: Math.round(d.projected_import_kwh) })}</Text>
              {d.net_metering_credit_rs > 0 && (
                <>
                  <Text style={[type.small, { color: c.greenDeep }]}>{t("mbill.credit", { credit: Math.round(d.net_metering_credit_rs) })}</Text>
                  <Text style={[type.heading, { color: c.greenDeep }]}>{t("mbill.net", { net: Math.round(d.projected_net_rs) })}</Text>
                </>
              )}
            </Rise>

            <Rise index={1} style={[styles.card, shadow, { backgroundColor: c.surface }]}>
              <Text style={[type.heading, { color: c.text }]}>{t("mbill.split")}</Text>
              <Row label={t("mbill.energy")} value={rs(d.breakdown.energy_rs)} />
              <Row label={t("mbill.fixed")} value={rs(d.breakdown.fixed_rs)} />
              <Row label={t("mbill.fppas")} value={rs(d.breakdown.fppas_rs)} />
              <Row label={t("mbill.duty")} value={rs(d.breakdown.duty_rs)} />
            </Rise>

            <Rise index={2} style={[styles.card, { backgroundColor: d.mismatch ? c.claySoft : c.greenSoft, borderColor: c.border, borderWidth: 1 }]}>
              <Text style={[type.heading, { color: c.text }]}>{t("mbill.reconcile")}</Text>
              <Text style={[type.body, { color: c.text }]}>{t("mbill.metered", { meter: Math.round(d.projected_load_kwh) })}</Text>
              <Text style={[type.body, { color: c.text }]}>{t("mbill.stated", { stated: Math.round(d.stated_kwh) })}</Text>
              <Text style={[type.small, { color: d.mismatch ? c.clay : c.greenDeep }]}>
                {d.mismatch ? t("mbill.mismatch", { diff: Math.abs(d.diff_pct) }) : t("mbill.match", { pct: Math.max(Math.abs(d.diff_pct), 1) })}
              </Text>
            </Rise>

            {d.complaint && (
              <Rise index={3} style={[styles.card, shadow, { backgroundColor: c.surface }]}>
                <Text style={[type.heading, { color: c.text }]}>{t("mbill.letter")}</Text>
                <Text style={[type.small, { color: c.muted }]}>{d.complaint.subject}</Text>
                <Text style={[type.body, { color: c.text }]} selectable>{d.complaint.body}</Text>
                <Button icon="share-social-outline" title={t("mbill.share")} onPress={() => void Share.share({ title: d.complaint!.subject, message: `${d.complaint!.subject}\n\n${d.complaint!.body}` })} />
              </Rise>
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  const c = useColors();
  return (
    <View style={styles.row}>
      <Text style={[type.body, { color: c.muted }]}>{label}</Text>
      <Text style={[type.body, { color: c.text }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { padding: space.lg, gap: space.lg, paddingBottom: 120 },
  top: { flexDirection: "row", alignItems: "center", gap: space.md },
  back: { width: 40, height: 40, borderRadius: 20, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  card: { borderRadius: 22, padding: space.lg, gap: space.sm },
  row: { flexDirection: "row", justifyContent: "space-between" },
});
