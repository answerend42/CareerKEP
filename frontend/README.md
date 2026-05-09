# Career KG 前端

这是 `Career KG` 项目的前端工作台，所有前端开发和维护都限定在 `frontend/` 目录下。

## 功能说明

- 输入自然语言画像或结构化证据。
- 通过四个阶段展示推荐过程：
  - 输入画像
  - 调整参数
  - 图谱传播
  - 结果解释
- 展示正式推荐、near miss、桥接建议、目标岗位分析和鲁棒性测试摘要。
- 支持调用后端 `/api/recommend`，后端不可用时自动回退到本地模拟结果，便于单独演示前端。

## 技术栈

- React 19
- TypeScript
- Vite

## 目录结构

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
  scripts/
    robustness-check.ts
```

## 本地运行

先进入 `frontend/` 安装依赖，再启动开发服务：

```bash
npm install
npm run dev
```

默认访问地址为 `http://127.0.0.1:5173`。

## 构建

```bash
npm run build
```

## 测试

```bash
npm test
```

该命令会先执行前端构建，再运行 `scripts/robustness-check.ts`，用于检查正常场景和极端场景下的推荐稳定性。

## 后端联调

- 前端默认向 `http://127.0.0.1:8000` 发送 `/api/recommend` 请求。
- 如果后端没有启动，页面会自动回退到本地模拟推荐结果，方便前端独立演示和调试。

## 关键交互

- 左侧输入画像和预置场景。
- 中间调整置信度、探索和惩罚容忍度。
- 右侧查看图谱传播快照和结果解释。
- 可导出或复制当前诊断快照，便于排查问题。

## 开发建议

- 新增前端状态时，优先同步更新 `src/app/types.ts`。
- 复杂展示逻辑尽量复用 `demoData.ts` 中的模拟数据构造函数，保证后端不可用时仍然可演示。
- 修改样式时只调整 `src/app/styles/global.css`，避免把布局分散到多个地方。
