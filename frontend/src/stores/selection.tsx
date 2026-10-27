/** The selected record (?sel=) highlights across chat chips, tables and cards; the route holds it so it survives reloads. */
import { createContext, useContext, type ReactNode } from 'react';
import { formatHash, navigate, type Route } from '../router/routes';

export interface Selection { id: string | null; select: (id: string | null) => void }
const Context = createContext<Selection>({ id: null, select: () => {} });

export function SelectionProvider({ route, children }: { route: Route; children: ReactNode }) {
  const select = (id: string | null) => navigate(formatHash({ ...route, sel: id }));
  return <Context.Provider value={{ id: route.sel, select }}>{children}</Context.Provider>;
}
export function useSelection() { return useContext(Context); }
