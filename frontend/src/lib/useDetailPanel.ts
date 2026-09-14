"use client";

import { useRouter, useSearchParams, usePathname } from "next/navigation";

export function useDetailPanel() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const openId = searchParams.get("open");

  function open(id: string) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("open", id);
    router.push(`${pathname}?${params.toString()}`);
  }

  function close() {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("open");
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname);
  }

  return { openId, open, close };
}
