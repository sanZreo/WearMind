import type { Metadata } from "next";

import { SiteHeader } from "@/components/site-header";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "WearMind · AI 个人穿搭顾问",
    template: "%s · WearMind",
  },
  description:
    "用照片或文字建立数字衣柜，结合天气、场景与个人偏好，生成可以直接穿出门的穿搭建议。",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-stone-50 font-sans text-stone-900 selection:bg-amber-200/60 dark:bg-stone-950 dark:text-stone-100 dark:selection:bg-amber-500/30">
        <SiteHeader />
        <main className="flex flex-1 flex-col">{children}</main>
        <footer className="border-t border-stone-200/80 dark:border-stone-800">
          <div className="mx-auto flex max-w-5xl flex-col gap-1.5 px-5 py-6 text-[12px] text-stone-500 sm:flex-row sm:items-center sm:justify-between dark:text-stone-500">
            <span>WearMind · Phase 0 项目骨架</span>
            <span>
              后端接口文档位于{" "}
              <a
                href="http://localhost:8000/docs"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-4 hover:text-stone-800 dark:hover:text-stone-300"
              >
                localhost:8000/docs
              </a>
              （需先启动后端）
            </span>
          </div>
        </footer>
      </body>
    </html>
  );
}
