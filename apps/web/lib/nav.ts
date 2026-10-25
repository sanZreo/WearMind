/**
 * 导航配置的唯一来源。
 *
 * href 使用字面量联合类型，配合 Next.js 16 的类型化路由，
 * 写错路径会在编译期报错，而不是运行时 404。
 */

export type NavHref = "/wardrobe" | "/advisor" | "/history" | "/settings";

export type NavItem = {
  href: NavHref;
  label: string;
  hint: string;
  /** 是否已实现。Phase 0 全部为 false。 */
  ready: boolean;
};

export const NAV_ITEMS: readonly NavItem[] = [
  {
    href: "/wardrobe",
    label: "衣柜",
    hint: "拍照或文字添加衣物，管理你的数字衣柜",
    ready: false,
  },
  {
    href: "/advisor",
    label: "AI 穿搭顾问",
    hint: "结合天气、场景与偏好生成穿搭建议",
    ready: false,
  },
  {
    href: "/history",
    label: "穿搭历史",
    hint: "回看每天的推荐与你的评价",
    ready: false,
  },
  {
    href: "/settings",
    label: "设置",
    hint: "个人偏好、模型选择与隐私模式",
    ready: false,
  },
] as const;
