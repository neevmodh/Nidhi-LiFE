// GEDA staff (admin, officer, reviewer, auditor) and DISCOM staff use their web consoles; the phone app is for households.
import * as WebBrowser from "expo-web-browser";

import { Body, Button, Screen, Title } from "@/components/ui";
import { useI18n } from "@/i18n";
import { useSession } from "@/lib/session";

const CONSOLE_URL = process.env.EXPO_PUBLIC_CONSOLE_URL ?? "http://localhost:3000/geda";
const DISCOM_URL = process.env.EXPO_PUBLIC_DISCOM_CONSOLE_URL ?? "http://localhost:3000/discom";

export default function Staff() {
  const { t } = useI18n();
  const { user, signOut } = useSession();
  const discom = !!user?.role.startsWith("discom_");
  return (
    <Screen>
      <Title>{t(discom ? "mobile.staffDiscomTitle" : "mobile.staffTitle")}</Title>
      <Body muted>{t(discom ? "mobile.staffDiscomBody" : "mobile.staffBody")}</Body>
      <Button title={t(discom ? "mobile.openDiscomConsole" : "mobile.openConsole")} onPress={() => WebBrowser.openBrowserAsync(discom ? DISCOM_URL : CONSOLE_URL)} />
      <Button variant="plain" title={t("nav.signOut")} onPress={signOut} />
    </Screen>
  );
}
