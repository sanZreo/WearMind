# apps/web

WearMind 前端（Next.js 16 App Router + TypeScript + Tailwind CSS v4）。

完整的项目说明、启动步骤与阶段规划见仓库根目录的 [`README.md`](../../README.md)。

## 本目录约定

- 路由：`app/` 下按功能分目录（`wardrobe` / `advisor` / `history` / `settings`）。
- 导航配置：`lib/nav.ts` 是唯一来源，`href` 使用字面量联合类型，配合 Next.js 类型化路由在编译期校验路径。
- 不直连数据库，也不接触任何模型密钥；所有数据经后端 `http://localhost:8000`。
- 未实现的页面统一使用 `components/under-construction.tsx`，**禁止**填充伪造数据。

## 常用命令

```bash
npm install        # 首次
npm run dev        # http://localhost:3000
npm run build      # 生产构建
npm run lint       # ESLint
```

## 已知环境适配

已移除 `next/font/google`（原本用于加载 Geist）。原因有两条：

1. 它在**构建期**需要访问 Google Fonts 下载字体文件，
   当前网络环境下 `next build` 会直接失败（`Module not found: .../font/google/font`）。
2. Geist 不含中文字形，中文界面最终仍会回落到系统字体。

现统一使用系统字体栈（含 PingFang SC / 微软雅黑 / Noto Sans SC），见 `app/globals.css`。
副作用是构建不再依赖外网，离线也能构建。
