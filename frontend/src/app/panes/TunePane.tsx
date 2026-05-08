import type { DemoState } from '../types';

interface TunePaneProps {
  state: DemoState;
  onChange: <K extends keyof DemoState>(key: K, value: DemoState[K]) => void;
  onApply: (nextState: DemoState) => void;
  activeStep: string;
}

const updateTuning = (state: DemoState, key: keyof DemoState['tuning'], value: number): DemoState => ({
  ...state,
  tuning: {
    ...state.tuning,
    [key]: value
  }
});

export function TunePane({ state, onChange, onApply, activeStep }: TunePaneProps) {
  const applyTuning = (key: keyof DemoState['tuning'], value: number) => {
    const nextState = updateTuning(state, key, value);
    onChange('tuning', nextState.tuning);
    onApply(nextState);
  };

  return (
    <div className="pane-stack">
      <div className="pane-header">
        <div>
          <p className="pane-kicker">阶段 2</p>
          <h2>微调画像</h2>
        </div>
        <span className="status-badge">{activeStep === '微调画像' ? '当前聚焦' : '可调整'}</span>
      </div>

      <div className="slider-group">
        <label className="field">
          <span>信心权重</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={state.tuning.confidence}
            onChange={(event) => applyTuning('confidence', Number(event.target.value))}
          />
          <strong>{state.tuning.confidence.toFixed(2)}</strong>
        </label>

        <label className="field">
          <span>探索权重</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={state.tuning.exploration}
            onChange={(event) => applyTuning('exploration', Number(event.target.value))}
          />
          <strong>{state.tuning.exploration.toFixed(2)}</strong>
        </label>

        <label className="field">
          <span>负向容忍度</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={state.tuning.penaltyTolerance}
            onChange={(event) => applyTuning('penaltyTolerance', Number(event.target.value))}
          />
          <strong>{state.tuning.penaltyTolerance.toFixed(2)}</strong>
        </label>
      </div>

      <div className="micro-summary">
        <div>
          <span>当前策略</span>
          <p>更高的信心会放大直接命中，更高的探索会保留更多 bridge 候选。</p>
        </div>
        <div>
          <span>设计原则</span>
          <p>前端不直接篡改推荐逻辑，只把画像和场景参数组织成可视化输入。</p>
        </div>
      </div>
    </div>
  );
}
