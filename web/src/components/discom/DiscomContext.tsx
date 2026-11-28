"use client";

// What every DISCOM page shares: which distribution company is on screen (a DISCOM account sees its own;
// the GEDA state team picks one), the headline figures refreshed every minute, and whether this account
// may change things (raise outages, resolve flags) or only read.
import { createContext, useContext, useEffect, useState } from "react";
import { useLoad } from "@/components/ui";
import { api, type DiscomOverview } from "@/lib/api";
import { useAuth } from "@/lib/auth";

interface DiscomState {
  discom: string;
  setDiscom: (code: string) => void;
  /** Only the state team picks a company; a DISCOM account is fixed to its own. */
  canPick: boolean;
  canEdit: boolean;
  overview: DiscomOverview | null;
  error: string | null;
  updated: Date;
  auto: boolean;
  setAuto: (on: boolean) => void;
  refresh: () => Promise<void>;
}

const Ctx = createContext<DiscomState | null>(null);

export function DiscomProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const own = user?.discom ?? null;
  const [picked, setPicked] = useState("ugvcl");
  const discom = own ?? picked;
  // Keyed by company, so choosing another one remounts everything below with fresh data.
  return <Inner key={discom} discom={discom} setDiscom={setPicked} canPick={!own}>{children}</Inner>;
}

function Inner({ discom, setDiscom, canPick, children }: {
  discom: string; setDiscom: (code: string) => void; canPick: boolean; children: React.ReactNode;
}) {
  const { user } = useAuth();
  const overview = useLoad(() => api.discomOverview(discom));
  const [updated, setUpdated] = useState<Date>(() => new Date());
  const [auto, setAuto] = useState(true);
  const refresh = async () => { await overview.reload(); setUpdated(new Date()); };

  useEffect(() => {
    if (!auto) return;
    const h = setInterval(() => { void overview.reload().then(() => setUpdated(new Date())); }, 60_000);
    return () => clearInterval(h);
  }, [auto, overview]);

  return (
    <Ctx.Provider value={{
      discom, setDiscom, canPick,
      canEdit: user?.role === "discom_admin" || user?.role === "discom_engineer",
      overview: overview.data, error: overview.error, updated, auto, setAuto, refresh,
    }}>
      {children}
    </Ctx.Provider>
  );
}

export function useDiscom(): DiscomState {
  const c = useContext(Ctx);
  if (!c) throw new Error("useDiscom outside DiscomProvider");
  return c;
}
