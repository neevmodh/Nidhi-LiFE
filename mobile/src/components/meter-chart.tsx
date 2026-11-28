// The last 24 hours of a home's (or a society's) power: demand in green, rooftop solar in saffron,
// with the evening peak and the sun hours shaded behind. Drawn with react-native-svg from lib/meter-view.
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import Svg, { Line, Path, Rect, Text as SvgText } from "react-native-svg";

import { useI18n } from "@/i18n";
import type { MeterPoint } from "@/lib/api";
import { chartGeometry, kw } from "@/lib/meter-view";
import { fonts, space, useColors } from "@/theme";

const HEIGHT = 150;
const AXIS = 18;

export function MeterChart({ points, peak, sun }: { points: MeterPoint[]; peak: [number, number]; sun: [number, number] }) {
  const { t } = useI18n();
  const c = useColors();
  const [width, setWidth] = useState(0);
  const g = width ? chartGeometry(points, width, HEIGHT, peak, sun) : null;

  return (
    <View accessibilityRole="image" accessibilityLabel={t("live.chart")}>
      <View onLayout={(e) => setWidth(Math.floor(e.nativeEvent.layout.width))} style={{ width: "100%", height: HEIGHT + AXIS }}>
        {g && g.load !== "" && (
          <Svg width={width} height={HEIGHT + AXIS}>
            {g.sun && <Rect x={g.sun[0] * width} y={0} width={(g.sun[1] - g.sun[0]) * width} height={HEIGHT} fill={c.saffronSoft} />}
            {g.peak && <Rect x={g.peak[0] * width} y={0} width={(g.peak[1] - g.peak[0]) * width} height={HEIGHT} fill={c.claySoft} />}
            <Line x1={0} y1={HEIGHT} x2={width} y2={HEIGHT} stroke={c.border} strokeWidth={1} />
            <Path d={g.pv} stroke={c.saffron} strokeWidth={2} fill="none" />
            <Path d={g.load} stroke={c.green} strokeWidth={2.4} fill="none" />
            <SvgText x={2} y={11} fontSize={10} fill={c.muted} fontFamily={fonts.bodyMedium}>{kw(g.max)}</SvgText>
            {g.hours.map((h) => (
              <SvgText key={h.label} x={Math.min(Math.max(h.x * width, 12), width - 14)} y={HEIGHT + 13} fontSize={10} fill={c.muted} textAnchor="middle" fontFamily={fonts.bodyMedium}>
                {h.label}
              </SvgText>
            ))}
          </Svg>
        )}
      </View>
      <View style={styles.legend}>
        <Key color={c.green} label={t("live.legendLoad")} />
        <Key color={c.saffron} label={t("live.legendPv")} />
        <Key color={c.saffronSoft} label={t("live.sun")} box />
        <Key color={c.claySoft} label={t("live.peak")} box />
      </View>
    </View>
  );
}

function Key({ color, label, box }: { color: string; label: string; box?: boolean }) {
  const c = useColors();
  return (
    <View style={styles.key}>
      <View style={[box ? styles.box : styles.dash, { backgroundColor: color }]} />
      <Text style={{ color: c.muted, fontFamily: fonts.bodyMedium, fontSize: 12 }}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  legend: { flexDirection: "row", flexWrap: "wrap", gap: space.md, marginTop: space.xs },
  key: { flexDirection: "row", alignItems: "center", gap: 6 },
  dash: { width: 14, height: 3, borderRadius: 2 },
  box: { width: 12, height: 12, borderRadius: 3 },
});
