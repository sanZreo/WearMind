import type { Metadata } from "next";

import { UnderConstruction } from "@/components/under-construction";

export const metadata: Metadata = { title: "设置" };

export default function SettingsPage() {
  return (
    <UnderConstruction
      title="设置"
      summary="这里将管理你的个人偏好、模型选择和隐私范围。你明确表达的偏好会与系统推断的偏好分开展示，并可随时修正。"
      planned={[
        "填写身高、体型、常穿尺码与风格倾向",
        "明确写入「我不穿什么」这类硬性要求，优先级最高",
        "查看系统推断出的偏好，并逐条确认或删除",
        "切换在线模型 / 本地 Ollama 模型，选择隐私模式",
      ]}
    />
  );
}
