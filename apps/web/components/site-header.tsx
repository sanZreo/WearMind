"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS } from "@/lib/nav";

export function SiteHeader() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-10 border-b border-stone-200/80 bg-stone-50/85 backdrop-blur-sm dark:border-stone-800 dark:bg-stone-950/85">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-5 py-3">
        <Link href="/" className="flex shrink-0 items-center gap-2.5">
          <span
            aria-hidden
            className="grid h-8 w-8 place-items-center rounded-lg bg-stone-900 text-[13px] font-medium text-stone-50 dark:bg-stone-100 dark:text-stone-900"
          >
            W
          </span>
          <span className="flex flex-col leading-none">
            <span className="text-[15px] font-medium tracking-tight">WearMind</span>
            <span className="mt-1 text-[11px] text-stone-500 dark:text-stone-400">
              AI 穿搭顾问
            </span>
          </span>
        </Link>

        <nav aria-label="主导航" className="flex items-center gap-0.5 overflow-x-auto">
          {NAV_ITEMS.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={[
                  "whitespace-nowrap rounded-lg px-3 py-1.5 text-[13px] transition-colors",
                  active
                    ? "bg-stone-900 text-stone-50 dark:bg-stone-100 dark:text-stone-900"
                    : "text-stone-600 hover:bg-stone-200/60 dark:text-stone-400 dark:hover:bg-stone-800",
                ].join(" ")}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
