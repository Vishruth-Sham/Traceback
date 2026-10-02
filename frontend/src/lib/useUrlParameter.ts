"use client";

import { usePathname, useSearchParams } from "next/navigation";

/** Keep view state in the current history entry so Back restores the page as it was. */
export function useUrlParameter(name: string, fallback = ""): [string, (value: string) => void] {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const value = searchParams.get(name) ?? fallback;

  function setValue(next: string) {
    const params = new URLSearchParams(window.location.search);
    if (next && next !== fallback) params.set(name, next);
    else params.delete(name);
    const query = params.toString();
    window.history.replaceState(null, "", query ? `${pathname}?${query}` : pathname);
  }

  return [value, setValue];
}
