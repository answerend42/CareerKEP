import type { DemoState, RoleOption, ScenarioPreset } from '../types';

interface InputPaneProps {
  state: DemoState;
  roleOptions: RoleOption[];
  presets: ScenarioPreset[];
  stressPresets: ScenarioPreset[];
  onChange: <K extends keyof DemoState>(key: K, value: DemoState[K]) => void;
  onPreset: (presetId: string) => void;
  onRun: () => void;
  onReset: () => void;
  isRunning: boolean;
}

export function InputPane({
  state,
  roleOptions,
  presets,
  stressPresets,
  onChange,
  onPreset,
  onRun,
  onReset,
  isRunning
}: InputPaneProps) {
  return (
    <div className="pane-stack">
      <div className="pane-header">
        <div>
          <p className="pane-kicker">阶段 1</p>
          <h2>输入画像</h2>
        </div>
        <div className="button-row">
          <button className="ghost-button" type="button" onClick={onReset} disabled={isRunning}>
            重置默认
          </button>
          <button className="primary-button" type="button" onClick={onRun} disabled={isRunning}>
            {isRunning ? '正在推荐...' : '执行推荐'}
          </button>
        </div>
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
          {presets.map((preset) => (
            <button key={preset.id} type="button" className="chip" onClick={() => onPreset(preset.id)}>
              {preset.label}
            </button>
          ))}
        </div>
      </div>

      <div className="preset-row">
        <span className="field-caption">极端测试</span>
        <div className="chip-row">
          {stressPresets.map((preset) => (
            <button key={preset.id} type="button" className="chip stress" onClick={() => onPreset(preset.id)}>
              {preset.label}
            </button>
          ))}
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
