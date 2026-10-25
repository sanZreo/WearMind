import type { Metadata } from "next";

import { UnderConstruction } from "@/components/under-construction";

export const metadata: Metadata = { title: "AI 穿搭顾问" };

export default function AdvisorPage() {
  return (
    <UnderConstruction
      title="AI 穿搭顾问"
      summary="这里将根据当天的天气、你要去的场合和你的个人偏好，从你真实拥有的衣物中挑出一套搭配，并说明这样搭的理由。"
      planned={[
        "按天气与场景生成整套搭配，而不是零散的单品罗列",
        "每一件推荐都带编号，可跳回衣柜中的真实衣物",
        "对推荐结果点赞/点踩，评价会影响之后的推荐",
        "支持切换在线模型与本地模型，并显示当前使用的模型",
      ]}
    />
  );
}
