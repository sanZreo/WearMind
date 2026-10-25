import Link from "next/link";

import { NAV_ITEMS } from "@/lib/nav";

const STATUS = [
  { label: "前端骨架", state: "已完成", tone: "done" as const },
  { label: "后端骨架", state: "已完成", tone: "done" as const },
  { label: "数据库", state: "未接入", tone: "pending" as const },
  { label: "登录与多用户", state: "未实现", tone: "idle" as const },
];

const TONE_CLASS = {
  done: "bg-emerald-500",
  pending: "bg-amber-500",
  idle: "bg-stone-300 dark:bg-stone-600",
};

export default function Home() {
  return (
    <div className="mx-auto w-full max-w-5xl px-5">
      <section className="pt-16 pb-10 sm:pt-24 sm:pb-14">
        <p className="inline-flex items-center gap-2 rounded-full border border-stone-200 bg-white px-3 py-1 text-[12px] text-stone-600 dark:border-stone-800 dark:bg-stone-900 dark:text-stone-400">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
          Phase 0 · 项目骨架
        </p>

        <h1 className="mt-6 text-4xl font-medium tracking-tight sm:text-5xl">WearMind</h1>

        <p className="mt-5 max-w-2xl text-[17px] leading-8 text-stone-600 dark:text-stone-300">
          用一张照片或一句话，把衣服放进你的数字衣柜；再结合天气、场景和你自己的偏好，
          每天早上给出一套可以直接穿出门的搭配。
        </p>

        <p className="mt-3 max-w-2xl text-[15px] leading-7 text-stone-500 dark:text-stone-400">
          它不是聊天机器人 —— 它会真正读取你的衣柜、查询天气、记住你的评价，
          并且只推荐你确实拥有的衣服。
        </p>

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <a
            href="#modules"
            className="rounded-lg bg-stone-900 px-4 py-2.5 text-[13px] font-medium text-stone-50 transition-opacity hover:opacity-85 dark:bg-stone-100 dark:text-stone-900"
          >
            浏览功能规划
          </a>
          <a
            href="http://localhost:8000/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-lg border border-stone-300 px-4 py-2.5 text-[13px] font-medium text-stone-700 transition-colors hover:bg-stone-100 dark:border-stone-700 dark:text-stone-300 dark:hover:bg-stone-900"
          >
            后端接口文档 ↗
          </a>
        </div>
      </section>

      <section
        aria-label="当前进度"
        className="rounded-xl border border-stone-200 bg-white px-5 py-4 dark:border-stone-800 dark:bg-stone-900/60"
      >
        <h2 className="text-[12px] font-medium tracking-wide text-stone-500 dark:text-stone-400">
          当前进度
        </h2>
        <ul className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2.5 sm:grid-cols-4">
          {STATUS.map((item) => (
            <li key={item.label} className="flex items-center gap-2 text-[13px]">
              <span
                aria-hidden
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${TONE_CLASS[item.tone]}`}
              />
              <span className="text-stone-700 dark:text-stone-300">{item.label}</span>
              <span className="text-stone-400 dark:text-stone-500">{item.state}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 border-t border-dashed border-stone-200 pt-3 text-[12px] leading-6 text-stone-400 dark:border-stone-800 dark:text-stone-500">
          本页不含任何演示数据或占位图表。功能未实现处如实标注，不伪造已接入的效果。
        </p>
      </section>

      <section id="modules" className="scroll-mt-20 pt-14 pb-6">
        <h2 className="text-[13px] font-medium text-stone-500 dark:text-stone-400">
          功能入口
        </h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="group flex flex-col rounded-xl border border-stone-200 bg-white p-5 transition-colors hover:border-stone-300 hover:bg-stone-50 dark:border-stone-800 dark:bg-stone-900/60 dark:hover:border-stone-700 dark:hover:bg-stone-900"
            >
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-[15px] font-medium tracking-tight">{item.label}</h3>
                <span
                  className={
                    item.ready
                      ? "shrink-0 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400"
                      : "shrink-0 rounded-full bg-stone-100 px-2 py-0.5 text-[11px] text-stone-500 dark:bg-stone-800 dark:text-stone-400"
                  }
                >
                  {item.ready ? "可用" : "开发中"}
                </span>
              </div>
              <p className="mt-2 text-[13px] leading-6 text-stone-500 dark:text-stone-400">
                {item.hint}
              </p>
              <span className="mt-4 text-[12px] text-stone-400 transition-transform group-hover:translate-x-0.5 dark:text-stone-500">
                查看 →
              </span>
            </Link>
          ))}
        </div>
      </section>

      <section className="pb-16 pt-8">
        <div className="rounded-xl border border-dashed border-stone-300 p-5 dark:border-stone-700">
          <h2 className="text-[13px] font-medium">关于当前阶段</h2>
          <p className="mt-2 max-w-2xl text-[13px] leading-6 text-stone-500 dark:text-stone-400">
            这是项目的骨架版本，目标是先把「前后端都能跑起来、契约清晰、边界正确」这件事做扎实。
            衣柜、图像解析、推荐 Agent、长期记忆、每日建议都会在后续阶段按顺序实现，
            每一步都有可复现的验收标准。
          </p>
        </div>
      </section>
    </div>
  );
}
