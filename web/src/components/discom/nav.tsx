// The DISCOM console's pages, in sidebar order, with a line icon each (drawn here, no icon library).
import type { MessageKey } from "@/i18n";

export type DiscomPageId = "overview" | "feeders" | "anomalies" | "outages" | "leads";

export const DISCOM_PAGES: { id: DiscomPageId; href: string; label: MessageKey; desc: MessageKey }[] = [
  { id: "overview", href: "/discom", label: "dc.nav.overview", desc: "dc.desc.overview" },
  { id: "feeders", href: "/discom/feeders", label: "dc.nav.feeders", desc: "dc.desc.feeders" },
  { id: "anomalies", href: "/discom/anomalies", label: "dc.nav.anomalies", desc: "dc.desc.anomalies" },
  { id: "outages", href: "/discom/outages", label: "dc.nav.outages", desc: "dc.desc.outages" },
  { id: "leads", href: "/discom/leads", label: "dc.nav.leads", desc: "dc.desc.leads" },
];

const PATHS: Record<DiscomPageId, React.ReactNode> = {
  overview: <><rect x="3" y="3" width="7.5" height="7.5" rx="2" /><rect x="13.5" y="3" width="7.5" height="7.5" rx="2" /><rect x="3" y="13.5" width="7.5" height="7.5" rx="2" /><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2" /></>,
  feeders: <><path d="M13 2L4 14h7l-1 8 9-12h-7z" /></>,
  anomalies: <><path d="M12 3l10 18H2z" /><path d="M12 10v5M12 18v.01" /></>,
  outages: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  leads: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
};

export function DiscomIcon({ id, className = "h-5 w-5" }: { id: DiscomPageId; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      {PATHS[id]}
    </svg>
  );
}
