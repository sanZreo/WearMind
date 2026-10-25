import Link from "next/link";

type Props = {
  title: string;
  summary: string;
  planned: string[];
};

/**
 * 未实现页面的统一占位。
 *
 * 刻意不渲染任何伪造的衣物、推荐或统计数据 —— 只说明"这里将来有什么"，
 * 避免让人误以为功能已经接入。
 */
export function UnderConstruction({ title, summary, planned }: Props) {
  return (
    <div className="mx-auto w-full max-w-3xl px-5 py-14 sm:py-20">
      <p className="inline-flex items-center gap-2 rounded-full border border-amber-300/70 bg-amber-50 px-3 py-1 text-[12px] font-medium text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
        <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden />
        开发中
      </p>

      <h1 className="mt-5 text-2xl font-medium tracking-tight sm:text-3xl">{title}</h1>
      <p className="mt-3 max-w-xl text-[15px] leading-7 text-stone-600 dark:text-stone-400">
        {summary}
      </p>

      <section className="mt-9 rounded-xl border border-stone-200 bg-white p-5 dark:border-stone-800 dark:bg-stone-900/60">
        <h2 className="text-[13px] font-medium text-stone-500 dark:text-stone-400">
          本页计划包含
        </h2>
        <ul className="mt-3 space-y-2.5">
          {planned.map((item) => (
            <li
              key={item}
              className="flex gap-2.5 text-[14px] leading-6 text-stone-700 dark:text-stone-300"
            >
              <span
                aria-hidden
                className="mt-2 h-1 w-1 shrink-0 rounded-full bg-stone-400 dark:bg-stone-600"
              />
              {item}
            </li>
          ))}
        </ul>
        <p className="mt-4 border-t border-dashed border-stone-200 pt-3 text-[12px] text-stone-400 dark:border-stone-800 dark:text-stone-500">
          以上均为计划内容，当前版本尚未实现任何一项。
        </p>
      </section>

      <Link
        href="/"
        className="mt-8 inline-block text-[13px] text-stone-500 underline underline-offset-4 transition-colors hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
      >
        ← 返回首页
      </Link>
    </div>
  );
}
