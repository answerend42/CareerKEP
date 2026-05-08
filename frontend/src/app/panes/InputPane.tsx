import type { DemoState, RoleOption } from '../types';

interface InputPaneProps {
  state: DemoState;
  roleOptions: RoleOption[];
  onChange: <K extends keyof DemoState>(key: K, value: DemoState[K]) => void;
  onPreset: (presetId: string) => void;
  onRun: () => void;
  isRunning: boolean;
}

export function InputPane({ state, roleOptions, onChange, onPreset, onRun, isRunning }: InputPaneProps) {
  return (
    <div className="pane-stack">
      <div className="pane-header">
        <div>
          <p className="pane-kicker">阶段 1</p>
          <h2>输入画像</h2>
        </div>
        <button className="primary-button" type="button" onClick={onRun} disabled={isRunning}>
          {isRunning ? '正在推理…' : '执行推荐'}
        </button>
      </div>

      <label className="field">
        <span>自然语言画像</span>
        <textarea
          value={state.text}
          onChange={(event) => onChange('text', event.target.value)}
          rows={6}
          placeholder="例如：我会 Python、SQL，做过前端项目，也比较擅长沟通。"
        />
      </label>

      <div className="field-grid">
        <label className="field">
          <span>目标岗位</span>
          <select value={state.targetRole} onChange={(event) => onChange('targetRole', event.target.value)}>
            {roleOptions.map((item) => (
              <option key={item.nodeId} value={item.label}>
                {item.label}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Top K</span>
          <input
            type="number"
            min={3}
            max={10}
            value={state.topK}
            onChange={(event) => onChange('topK', Number(event.target.value))}
          />
        </label>
      </div>

      <div className="preset-row">
        <span className="field-caption">快速场景</span>
        <div className="chip-row">
          <button type="button" className="chip" onClick={() => onPreset('backend')}>
            后端转向
          </button>
          <button type="button" className="chip" onClick={() => onPreset('frontend')}>
            前端优先
          </button>
          <button type="button" className="chip" onClick={() => onPreset('data')}>
            数据方向
          </button>
        </div>
      </div>

      <div className="evidence-grid">
        {state.evidence.map((item) => (
          <article key={item.nodeId} className="evidence-card">
            <div>
              <strong>{item.label}</strong>
              <p>{item.rawText}</p>
            </div>
            <span>{item.score.toFixed(2)}</span>
          </article>
        ))}
      </div>
    </div>
  );
}
