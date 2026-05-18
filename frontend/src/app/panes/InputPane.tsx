import type { DemoState, EvidenceItem, RoleOption, ScenarioPreset } from '../types';

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

const updateEvidenceItem = (
  evidence: EvidenceItem[],
  nodeId: string,
  updater: (item: EvidenceItem) => EvidenceItem
): EvidenceItem[] => evidence.map((item) => (item.nodeId === nodeId ? updater(item) : item));

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
  const handleEvidenceScoreChange = (nodeId: string, nextScore: number) => {
    onChange(
      'evidence',
      updateEvidenceItem(state.evidence, nodeId, (item) => ({
        ...item,
        score: nextScore
      }))
    );
  };

  const handleEvidenceTextChange = (nodeId: string, nextText: string) => {
    onChange(
      'evidence',
      updateEvidenceItem(state.evidence, nodeId, (item) => ({
        ...item,
        rawText: nextText
      }))
    );
  };

  return (
    <div className="pane-stack input-workflow">
      <div className="pane-header">
        <div>
          <h2>填写个人画像</h2>
        </div>
        <div className="header-inline-actions">
          <button className="ghost-button header-peer-button" type="button" onClick={onReset} disabled={isRunning}>
            重置默认
          </button>
          <button className="primary-button next-step-button" type="button" onClick={onRun} disabled={isRunning}>
            {isRunning ? '正在推荐...' : '生成推荐'}
          </button>
        </div>
      </div>

      <div className="pane-scroll support-pane-scroll unified-input-flow">
        <section className="section-card support-panel profile-editor">
          <label className="field-block">
            <span className="micro-label">画像描述</span>
            <textarea
              className="editor-textarea profile-textarea"
              value={state.text}
              onChange={(event) => onChange('text', event.target.value)}
            />
          </label>
        </section>

        <section className="section-card input-control-panel">
          <div className="field-grid">
            <label className="field-block">
              <span className="micro-label">目标岗位</span>
              <select className="editor-select" value={state.targetRole} onChange={(event) => onChange('targetRole', event.target.value)}>
                {roleOptions.map((item) => (
                  <option key={item.nodeId} value={item.label}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="field-block">
              <span className="micro-label">Top K</span>
              <input
                className="editor-input"
                type="number"
                min={3}
                max={10}
                value={state.topK}
                onChange={(event) => onChange('topK', Number(event.target.value))}
              />
            </label>
          </div>

          <div className="preset-row">
            <span className="micro-label">快捷场景</span>
            <div className="chip-row">
              {presets.map((preset) => (
                <button key={preset.id} type="button" className="button-chip" onClick={() => onPreset(preset.id)}>
                  {preset.label}
                </button>
              ))}
            </div>
          </div>

          <div className="preset-row">
            <span className="micro-label">极端测试</span>
            <div className="chip-row">
              {stressPresets.map((preset) => (
                <button key={preset.id} type="button" className="button-chip stress" onClick={() => onPreset(preset.id)}>
                  {preset.label}
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="section-card evidence-panel">
          <div className="section-head">
            <div>
              <h3>结构化证据</h3>
            </div>
            <span className="mini-badge">{state.evidence.length} 条</span>
          </div>
          <div className="evidence-grid">
            {state.evidence.map((item) => (
              <article key={item.nodeId} className="signal-card evidence-card">
                <div className="signal-topline">
                  <div>
                    <strong>{item.label}</strong>
                    <p>{item.source}</p>
                  </div>
                  <span className="score-badge">{item.score.toFixed(2)}</span>
                </div>

                <label className="field-block compact-field">
                  <span className="micro-label">证据权重</span>
                  <input
                    className="editor-range"
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={item.score}
                    onChange={(event) => handleEvidenceScoreChange(item.nodeId, Number(event.target.value))}
                  />
                </label>

                <label className="field-block compact-field">
                  <span className="micro-label">证据原文</span>
                  <textarea
                    className="editor-textarea compact"
                    rows={3}
                    value={item.rawText}
                    onChange={(event) => handleEvidenceTextChange(item.nodeId, event.target.value)}
                  />
                </label>
              </article>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
