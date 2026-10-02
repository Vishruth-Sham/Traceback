"use client";

import { useLayoutEffect, useRef } from "react";
import { usePathname } from "next/navigation";

export function MainScrollArea({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const mainRef = useRef<HTMLElement>(null);
  const positions = useRef(new Map<string, number>());
  const activePath = useRef(pathname);
  const restoring = useRef(false);

  useLayoutEffect(() => {
    const main = mainRef.current;
    if (!main) return;
    activePath.current = pathname;
    const target = positions.current.get(pathname) ?? 0;
    restoring.current = true;

    const observer = new MutationObserver(() => restore());
    function restore() {
      if (!main || !restoring.current) return;
      main.scrollTop = target;
      if (Math.abs(main.scrollTop - target) < 1) {
        restoring.current = false;
        observer.disconnect();
      }
    }
    observer.observe(main, { childList: true, subtree: true });
    restore();
    return () => observer.disconnect();
  }, [pathname]);

  return (
    <main
      ref={mainRef}
      onScroll={(event) => {
        if (!restoring.current) positions.current.set(activePath.current, event.currentTarget.scrollTop);
      }}
      onWheel={() => { restoring.current = false; }}
      onTouchMove={() => { restoring.current = false; }}
      className="relative flex-1 overflow-y-auto pb-20"
    >
      {children}
    </main>
  );
}
