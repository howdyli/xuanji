# 前端样式约定（Frontend Style Convention）

> 目标：收敛 `内联 style` / Tailwind / App.css 组件类三者混用的现状，统一后续写法，
> 并为存量迁移提供一条**低风险、可验证**的路线。

## 1. 现状：三层样式体系

当前前端样式由三层叠加而成（`frontend/src`）：

| 层 | 位置 | 规模 | 用途 |
| --- | --- | --- | --- |
| ① 设计令牌 | `App.css` 的 `:root {}` | ~578 处 `var(--…)` 引用 | 颜色 / 间距 / 圆角 / 阴影 / 字号等 Token |
| ② 语义组件类 | `App.css`（`.topbar` / `.card` / `.tab-button` / `.btn-press` …） | 数十个类 | 复用型组件外观 |
| ③ Tailwind 工具类 | 各 `.tsx` 的 `className` | ~1263 处 | 布局 / 一次性样式 |
| ④ 内联样式 | 各 `.tsx` 的 `style={{}}` | **~377 处 / 30+ 文件** | 令牌覆盖 / 动态样式 / 精确像素值 |

内联样式最集中的文件：`LoginView.tsx`(80)、`Sidebar.tsx`(37)、`market/PublishSkillView.tsx`(31)、
`DashboardHome.tsx`(26)、`market/SkillDetailPage.tsx`(21)、`GlobalSearchView.tsx`(21)。

## 2. 两个必须知道的迁移陷阱（有实据）

在把内联样式机械改写成 Tailwind 前，务必注意以下两点，否则会引入**视觉回归**：

### 陷阱 A：Tailwind 工具类被非分层 CSS 反压

`App.css` 里 `@import "tailwindcss"` 之后直接写的 `.topbar { border-bottom: 1px … }` 属于
**非 layer 规则**，其优先级**高于** Tailwind 的 `utilities` layer。

- 现状：`DashboardTopBar.tsx` 用 `style={{ borderBottom: 'none' }}` 覆盖 `.topbar` 的边框（内联样式永远赢）。
- 若改成 `className="border-b-0"`：由于 `.topbar`（非分层）> `border-b-0`（分层 utilities），
  **边框会重新出现** → 回归。

> 结论：凡是「组件类 + 内联覆盖」的文件（`DashboardTopBar`/`DashboardHome`/`Sidebar` 等），
> 不能只把内联覆盖换成工具类；必须**同时处理对应的 App.css 组件类**，或给覆盖加 `!` 重要级修饰。

### 陷阱 B：交互式 / 条件式内联样式无法机械平移

`LoginView.tsx` 是纯内联（0 className），但大量样式是**命令式或条件式**的：

- `onMouseEnter/Leave/Focus/Blur` 直接改 `e.currentTarget.style.*`（卡片悬浮、按钮悬浮、输入框聚焦）；
- 基于 state 的条件样式：`activeTab === …`、`fieldErrors.x ? '#dc2626' : …`、`loading ? …`；
- `<style>` 内的 `@media (max-width…) { aside { display:none !important } }` 与 `@keyframes`。

这些迁到 Tailwind 需改用 `hover: / focus: / lg: / @theme 动画`，属于**行为改写而非平移**，
且当前**没有视觉回归测试**，只能靠人工/截图核对。

## 3. 约定（新代码一律遵守）

1. **优先 Tailwind 工具类**表达布局与一次性样式（flex/grid/间距/字号/颜色）。
2. **设计令牌统一走 Tailwind 任意值**：`bg-[var(--bg-primary)]`、`text-[var(--text-primary)]`、
   `rounded-[var(--radius-lg)]`、`shadow-[var(--shadow-sm)]`。禁止再用 `style={{ color:'var(--…)' }}`。
   - 值与 Tailwind 原生刻度精确相等时用原生类（`--space-4`=1rem→`p-4`；`--radius-md`=8px→`rounded-lg`）。
3. **`style={{}}` 仅用于真正动态的值**：运行时计算的宽高/百分比/transform、来自 props 的颜色等。
   静态样式一律不用内联。
4. **交互态用伪类**：`hover:` / `focus:` / `active:` / `disabled:`，不要用 JS 改 `element.style`。
5. **响应式用断点前缀**：`lg:hidden`、`md:flex-1`，不要在 `<style>` 里写 `@media + 元素选择器`。
6. **新增可复用外观**：优先组合 Tailwind；确需语义类时放进 `App.css` 并**写进 `@layer components`**，
   避免再制造陷阱 A 的非分层规则。

## 4. 存量统一路线图（分级、可回退、需验证）

按「风险从低到高」推进，每一步都应在浏览器里对比改前/改后：

1. **[基础]** 把 `App.css` 里 `@import` 之后的裸组件类（`.topbar` 等）包进 `@layer components`，
   消除陷阱 A 的优先级反压。这是后续所有转换的前提。
2. **[低风险]** 迁移**纯静态、无 onMouse/无组件类竞争**的内联样式文件（先易后难）。
3. **[中风险]** 迁移含组件类的文件（配合步骤 1 后再动）。
4. **[高风险]** 迁移 `LoginView` 这类重交互文件：需逐一将命令式 hover/focus、条件样式、
   `@media`、`@keyframes` 改写为 Tailwind 等价物，并用截图逐屏核对（建议 Playwright）。

> 注意：`:root` 令牌未接入 Tailwind `@theme`，因此目前只能用 `[var(--…)]` 任意值引用。
> 若未来希望使用 `bg-brand-500` 这类语义工具类，可在 `@theme` 中**增量新增**
> （`--color-brand-500: #4F6EF7` 等），该操作是追加式的、不影响现有 className。

## 5. 验证前提

任何存量样式迁移都缺少自动化护栏，合并前至少要：

- `npm run build` 通过（类型 + 构建）；
- 关键页面（登录、工作台、会话、侧边栏展开/收起、响应式断点）人工或截图核对无回归。
