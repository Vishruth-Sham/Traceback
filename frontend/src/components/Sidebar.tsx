"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Plus, Search } from "lucide-react";
import { CATEGORY_LABELS, CATEGORY_SLUGS } from "@/lib/traceback";
import { Logo } from "./Logo";

function NavItem({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <Link
      href={href}
      className={
        "block border-l-2 py-1 pl-3 pr-2 text-[13px] transition-colors " +
        (active
          ? "border-accent-navy font-semibold text-ink"
          : "border-transparent text-ink-muted hover:text-ink")
      }
    >
      {label}
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-[240px] flex-none flex-col bg-paper px-4 py-5">
      <div className="mb-8 px-3">
        <div className="flex items-center gap-2.5">
          <Logo size={42} />
          <span className="font-serif text-[26px] font-semibold tracking-tight text-ink">Traceback</span>
        </div>
        <div className="mt-0.5 text-[13px] text-ink-faint">personal memory index</div>
      </div>

      <Link
        href="/search"
        className="mb-5 flex items-center gap-2 px-3 py-1 text-[12.5px] text-ink-muted hover:text-ink"
      >
        <Search size={13} />
        <span>Search</span>
      </Link>

      <Link
        href="/notes/quick-add"
        className="mb-4 flex items-center gap-2 rounded bg-accent-navy px-3 py-2 text-[12.5px] font-medium text-paper hover:opacity-90"
      >
        <Plus size={13} /> Quick add note
      </Link>

      <nav className="flex flex-col gap-0.5 border-b border-hairline pb-4">
        <NavItem href="/inbox" label="Inbox" active={pathname.startsWith("/inbox")} />
        <NavItem href="/tasks" label="Tasks" active={pathname.startsWith("/tasks")} />
      </nav>

      <div className="flex flex-col gap-0.5 border-b border-hairline py-4">
        {CATEGORY_SLUGS.map((slug) => {
          const isProjects = slug === "projects";
          const href = isProjects ? "/projects" : `/category/${slug}`;
          return (
            <NavItem key={slug} href={href} label={CATEGORY_LABELS[slug]} active={pathname.startsWith(href)} />
          );
        })}
      </div>

      <div className="flex flex-col gap-0.5 py-4">
        <NavItem href="/archive" label="Archive" active={pathname.startsWith("/archive")} />
      </div>

      <div className="mt-auto flex flex-col gap-0.5 border-t border-hairline pt-4">
        <div className="flex items-center gap-2 px-3">
          <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-accent-gold text-[11px] font-semibold text-paper">
            Y
          </span>
          <span className="text-[12.5px] text-ink-muted">You</span>
        </div>
      </div>
    </aside>
  );
}
