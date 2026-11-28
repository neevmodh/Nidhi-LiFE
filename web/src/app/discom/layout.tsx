"use client";

// The DISCOM console's frame, the same shape as GEDA's: a sidebar of pages (a scrolling tab bar on
// phones), the company, language, refresh, print and sign out. DISCOM staff see their own company;
// the GEDA state team and auditors can look at any, read-only. Households never get past it.
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useDiscom, DiscomProvider } from "@/components/discom/DiscomContext";
import { DISCOM_PAGES, DiscomIcon, type DiscomPageId } from "@/components/discom/nav";
import { GedaStrip, LanguageSwitcher, Logo } from "@/components/Shell";
import { Spinner, useLoad } from "@/components/ui";
import { dateTag, useI18n } from "@/i18n";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const ALLOWED = ["discom_admin", "discom_engineer", "discom_auditor", "admin", "auditor"];

function currentPage(pathname: string) {
  return DISCOM_PAGES.find((p) => (p.href === "/discom" ? pathname === "/discom" : pathname.startsWith(p.href))) ?? DISCOM_PAGES[0];
}

function Frame({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  const pathname = usePathname();
  const router = useRouter();
  const { signOut } = useAuth();
  const { discom, setDiscom, canPick, overview, updated, auto, setAuto, refresh } = useDiscom();
  const config = useLoad(api.config);
  const page = currentPage(pathname);
  const badges: Partial<Record<DiscomPageId, number>> = {
    anomalies: overview?.open_flags ?? 0,
    outages: overview?.active_outages ?? 0,
    leads: overview?.solar_leads ?? 0,
  };

  return (
    <div className="flex min-h-screen flex-1 flex-col bg-bg">
      <GedaStrip />
      <header className="no-print border-b border-border bg-surface">
        <div className="flex items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <Logo size={40} />
            <div className="hidden leading-tight sm:block">
              <p className="text-sm font-bold">{overview?.name ?? t("dc.title")}</p>
              <p className="text-xs text-muted">{t("dc.kicker")}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2 text-sm">
            {canPick && (
              <select aria-label={t("dc.pick")} value={discom} onChange={(e) => setDiscom(e.target.value)}
                className="rounded-full border border-border bg-surface px-3 py-1.5 font-semibold">
                {(config.data?.discoms ?? [{ code: "ugvcl", name: "UGVCL" }]).map((d) => <option key={d.code} value={d.code}>{d.code.toUpperCase()}</option>)}
              </select>
            )}
            <span className="hidden text-muted md:inline">{t("con.updated", { time: updated.toLocaleTimeString(dateTag(), { hour: "2-digit", minute: "2-digit" }) })}</span>
            <label className="hidden items-center gap-2 rounded-full bg-surface-2 px-3 py-1.5 md:flex">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} className="accent-[#c9873e]" />
              {t("con.auto")}
            </label>
            <button onClick={() => void refresh()} className="rounded-full bg-surface-2 px-3 py-1.5 font-semibold hover:bg-border">{t("con.refresh")}</button>
            <button onClick={() => window.print()} className="rounded-full bg-navy px-3 py-1.5 font-semibold text-[#f6f2ea] hover:bg-abyss">{t("con.print")}</button>
            <LanguageSwitcher />
            <button onClick={() => { signOut(); router.replace("/"); }} className="px-2 text-muted hover:text-text">{t("nav.signOut2")}</button>
          </div>
        </div>
        <nav aria-label={t("con.menu")} className="flex gap-1 overflow-x-auto px-3 pb-2 lg:hidden">
          {DISCOM_PAGES.map((p) => (
            <Link key={p.id} href={p.href} aria-current={p.id === page.id ? "page" : undefined}
              className={`flex shrink-0 items-center gap-2 rounded-full px-3.5 py-2 text-sm font-semibold ${p.id === page.id ? "bg-navy text-[#f6f2ea]" : "text-muted hover:bg-surface-2"}`}>
              <DiscomIcon id={p.id} className="h-4 w-4" />{t(p.label)}
              {!!badges[p.id] && <span className="rounded-full bg-sun px-1.5 text-xs text-text">{badges[p.id]}</span>}
            </Link>
          ))}
        </nav>
      </header>

      <div className="flex flex-1">
        <aside className="no-print sticky top-0 hidden h-screen w-64 shrink-0 border-r border-border bg-surface lg:block">
          <nav aria-label={t("con.menu")} className="flex flex-col gap-1 p-3">
            {DISCOM_PAGES.map((p) => (
              <Link key={p.id} href={p.href} aria-current={p.id === page.id ? "page" : undefined}
                className={`flex items-center gap-3 rounded-2xl px-3.5 py-2.5 text-sm font-semibold ${p.id === page.id ? "bg-navy text-[#f6f2ea]" : "text-muted hover:bg-surface-2 hover:text-text"}`}>
                <DiscomIcon id={p.id} />
                <span className="flex-1">{t(p.label)}</span>
                {!!badges[p.id] && <span className={`rounded-full px-2 py-0.5 text-xs ${p.id === page.id ? "bg-[#f6f2ea] text-text" : "bg-sun-soft text-text"}`}>{badges[p.id]}</span>}
              </Link>
            ))}
          </nav>
        </aside>
        <main className="min-w-0 flex-1 px-4 pb-16 pt-6 sm:px-8">
          <div className="mx-auto w-full max-w-6xl space-y-6">
            <div>
              <h1 className="font-display text-3xl font-bold sm:text-4xl">{t(page.label)}</h1>
              <p className="mt-1 max-w-3xl text-muted">{t(page.desc)}</p>
            </div>
            {overview && overview.simulated_meters > 0 && (
              <p className="rounded-2xl bg-sun-soft px-5 py-3 text-sm">{t("dc.simBanner", { n: overview.simulated_meters, total: overview.meters })}</p>
            )}
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}

export default function DiscomLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const allowed = !!user && ALLOWED.includes(user.role);

  useEffect(() => {
    if (loading) return;
    if (!user) router.replace("/login");
    else if (!allowed) router.replace(user.role === "citizen" ? "/" : "/geda");
  }, [loading, user, allowed, router]);

  if (loading || !allowed) return <div className="mx-auto w-full max-w-5xl px-4 pt-10"><Spinner /></div>;
  return <DiscomProvider><Frame>{children}</Frame></DiscomProvider>;
}
