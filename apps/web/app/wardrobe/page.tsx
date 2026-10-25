import type { Metadata } from "next";

import { UnderConstruction } from "@/components/under-construction";

export const metadata: Metadata = { title: "衣柜" };

export default function WardrobePage() {
  return (
    <UnderConstruction
      title="数字衣柜"
      summary="这里将展示你所有的衣物，支持按品类、颜色、季节和场景筛选。衣物可以来自单件照片、全身照或一句文字描述。"
      planned={[
        "上传单品/全身照片，自动生成衣物草稿并交给你确认",
        "按品类、颜色、材质、季节、场景浏览与筛选",
        "编辑与删除衣物，同一件衣物支持多张图片",
        "衣物详情：搭配建议、穿着次数、最近一次穿的时间",
      ]}
    />
  );
}
