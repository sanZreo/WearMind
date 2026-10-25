import type { Metadata } from "next";

import { UnderConstruction } from "@/components/under-construction";

export const metadata: Metadata = { title: "穿搭历史" };

export default function HistoryPage() {
  return (
    <UnderConstruction
      title="穿搭历史"
      summary="这里将按时间回看你收到过的推荐、实际穿过哪一套，以及你对每套搭配的评价。"
      planned={[
        "按日期浏览每天的推荐与当日天气",
        "标记「今天穿了这套」，累积真实的穿着记录",
        "查看某件衣物的历史搭配与穿着频次",
        "基于历史反馈调整之后的推荐倾向",
      ]}
    />
  );
}
