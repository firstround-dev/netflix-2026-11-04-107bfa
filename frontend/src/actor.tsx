// Who is using the desk. There is no auth yet: the name is self-reported, kept in localStorage,
// and sent with every change so the server can record who did what.

import { createContext, useContext, useState, type ReactNode } from "react";

const STORAGE_KEY = "tld.actor";

interface ActorContextValue {
  actor: string; // trimmed; empty means "not set"
  rawActor: string;
  setActor: (value: string) => void;
}

const ActorContext = createContext<ActorContextValue>({ actor: "", rawActor: "", setActor: () => {} });

export function ActorProvider({ children }: { children: ReactNode }) {
  const [rawActor, setRawActor] = useState(() => localStorage.getItem(STORAGE_KEY) ?? "");
  const setActor = (value: string) => {
    setRawActor(value);
    localStorage.setItem(STORAGE_KEY, value);
  };
  return <ActorContext.Provider value={{ actor: rawActor.trim(), rawActor, setActor }}>{children}</ActorContext.Provider>;
}

export function useActor(): ActorContextValue {
  return useContext(ActorContext);
}

export function NameBar() {
  const { rawActor, setActor, actor } = useActor();
  return (
    <label className={`namebar ${actor ? "" : "namebar-empty"}`}>
      <span>Working as</span>
      <input
        value={rawActor}
        onChange={(event) => setActor(event.target.value)}
        placeholder="Your name (required to make changes)"
        maxLength={80}
      />
    </label>
  );
}
