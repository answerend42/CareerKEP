# Career KG 前端

这是 `Career KG` 项目的前端工作台，所有前端开发和维护都限制在 `frontend/` 目录内。

## 功能说明

- 输入自然语言画像或直接调整结构化证据。
- 按四个阶段展示推荐流程：
  - 输入画像
  - 调整参数
  - 图谱传播
  - 结果解释
- 展示正式推荐、near miss、桥接建议、目标岗位分析和鲁棒性摘要。
- 支持调用后端 `/api/recommend`。
- 如果后端不可用，页面会自动回退到本地模拟结果，方便独立演示和调试。

## 技术栈

- React 19
- TypeScript
- Vite

## 本地运行

先进入 `frontend/` 目录，再安装依赖并启动开发服务：

```bash
npm install
npm run dev
```

默认访问地址：

```text
http://127.0.0.1:5173
```

## 构建

```bash
npm run build
```

## 测试

```bash
npm test
```

该命令会先执行前端构建，再运行 `scripts/robustness-check.ts`，用于检查正常场景和极端场景下的推荐稳定性。

## 当前前端结构

```text
frontend/
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
  scripts/
    robustness-check.ts
```

## 说明

- 现在输入面板里的证据卡片可以直接编辑权重和原始文本，页面会即时重算结果。
- 调整参数时建议先看图谱传播，再对照结果解释和鲁棒性摘要。
