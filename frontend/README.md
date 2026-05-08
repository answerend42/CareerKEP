# Career KG 前端

这是 `Career KG` 的前端工作台，只在 `frontend/` 目录内维护。

## 目标

- 输入自然语言画像和结构化证据。
- 调整信心、探索、负向容忍度等演示参数。
- 查看图谱传播快照。
- 解释正式推荐、near miss、桥接建议和目标岗位缺口。

## 技术栈

- React 19
- TypeScript
- Vite

## 目录

```text
frontend/
  index.html
  package.json
  vite.config.ts
  tsconfig.json
  tsconfig.node.json
  src/
    main.tsx
    app/
      AppShell.tsx
      demoData.ts
      types.ts
      panes/
        InputPane.tsx
        TunePane.tsx
        GraphPane.tsx
        ResultPane.tsx
      styles/
        global.css
```

## 本地运行

先进入 `frontend/` 目录安装依赖，再启动开发服务。

```bash
npm install
npm run dev
```

默认会启动在 `http://127.0.0.1:5173`。

## 构建

```bash
npm run build
```

## 后端联调

前端默认会把 `/api/recommend` 代理到 `http://127.0.0.1:8000`。

如果后端没有启动，页面会自动回退到本地模拟推理结果，方便单独演示。
