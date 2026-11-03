# 前端代码组织

本项目使用 React、React Router 和 Vite。启动入口依次是 `index.html`、
`src/main.jsx`、`src/App.jsx`。页面路由在 `App.jsx`，公共导航在 `MainLayout`。

## 目录

```text
src/
├─ components/
│  └─ DeviceStatusCard/
│     ├─ DeviceStatusCard.jsx
│     └─ DeviceStatusCard.module.css
├─ pages/
│  ├─ DeviceManagement/
│  │  ├─ DeviceManagement.jsx
│  │  └─ DeviceManagement.module.css
│  └─ shared/Patrol.module.css    # 多个巡检页面共用的布局、表单等
├─ layouts/MainLayout/           # 公共导航及其局部样式
├─ styles/SubpageTheme.module.css # 业务页面共用主题
├─ utils/bindStyles.js           # 动态类名与 CSS Modules 的绑定
└─ index.css                    # 全局 reset、基础变量、第三方地图的全局规则
```

页面和组件的专用样式就近存放。巡检页面共用 `pages/shared/Patrol.module.css`；
室内地图和导航的专用规则仍放在各自页面目录。共享组件自己的 CSS 不再依赖某个页面
顺带导入，因此可以独立复用。

## 编写组件样式

```jsx
import styles from './DeviceCard.module.css'
import themeStyles from '../../styles/SubpageTheme.module.css'
import { bindStyles } from '../../utils/bindStyles.js'

const cx = bindStyles(styles, themeStyles)

export default function DeviceCard({ online, className = '' }) {
  return <div className={cx(`card ${online ? 'online' : ''} ${className}`)} />
}
```

`cx` 将语义类名转换为局部类名，并保留共享主题类及父组件传入的类名。
同名的局部类不会因为其他页面导入 CSS 而相互覆盖。新增组件如果不使用公共业务主题，
可以直接使用 `styles.card`，或只绑定自己的 `styles`。

样式模块的规则放在 `@layer components { ... }` 中。全局入口声明层次顺序：

```css
@layer reset, vendor, components, theme;
```

它保证第三方库的延迟加载不会改变组件与主题的覆盖关系。自绘下拉框及公共业务主题
属于 `theme` 层；MapLibre、xterm 的原始 CSS 通过相邻的 `*.vendor.css` 放入
`vendor` 层。不要将第三方库自动生成的类名当成局部类，覆盖它们时使用
`:global(.maplibregl-canvas)` 等显式选择器。

少数页面需要调整共享组件的内部布局，此时使用 CSS Modules 的显式导入：

```css
@value cockpit-panel from "../../components/CockpitSensorFeed/CockpitSensorFeed.module.css";

@layer components {
  .sensor-area .cockpit-panel { min-height: 200px; }
}
```

优先通过组件的 `className`、props 和 CSS 变量进行定制；确需内部选择器时再导入。
`NavLink` 的激活态必须在回调中传给 `cx`，不能依赖它自动添加的全局 `active` 类。
地图 SDK 生成的 HTML 字符串和 DOM 标记也需要使用绑定后的类名。

## 静态资源

新写的页面图片、图标默认通过 `src/assets/` 导入；需要固定 URL 的站点文件可以放
`public/`。已有 `public/video-analysis/` 的资源在本次样式迁移中保持原位置。
动态切换图片不需要使用 `public/`：导入多张图片后按状态选择即可。

## 常用检查

```bash
npm ci
npm run dev
npm run build
npm test
npm run lint
```

`npm test` 验证动态状态、共享主题和跨组件类名传递。
当前仓库迁移前已有 ESLint 问题；全量 lint 需要与既有基线比较，不能将构建成功当作
lint 已通过。涉及真实车辆的控制和媒体功能仍需在对应设备环境验证。
