import type { DemoState } from '../types';

interface TunePaneProps {
  state: DemoState;
  onApply: (nextState: DemoState) => void;
  onNext: () => void;
}

const updateTuning = (state: DemoState, key: keyof DemoState['tuning'], value: number): DemoState => ({
  ...state,
  tuning: {
    ...state.tuning,
    [key]: value
  }
});

export function TunePane({ state, onApply, onNext }: TunePaneProps) {
  const applyTuning = (key: keyof DemoState['tuning'], value: number) => {
    const nextState = updateTuning(state, key, value);
    onApply(nextState);
  };

  return (
    <div className="pane-stack tune-workflow">
      <div className="pane-header">
        <div>
          <h2>微调画像</h2>
        </div>
        <div className="header-inline-actions">
          <button className="primary-button next-step-button" type="button" onClick={onNext}>
            下一步：看图谱
          </button>
        </div>
      </div>

      <div className="pane-scroll tune-scroll">
        <div className="tune-list">
          <article className="tune-row">
            <div className="tune-name">
              <span>系统</span>
              <strong>信心权重</strong>
            </div>
            <label className="tune-control">
              <input
                className="editor-range"
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={state.tuning.confidence}
                onChange={(event) => applyTuning('confidence', Number(event.target.value))}
              />
              <strong>{state.tuning.confidence.toFixed(2)}</strong>
              <em>直接命中</em>
            </label>
          </article>

          <article className="tune-row">
            <div className="tune-name">
              <span>探索</span>
              <strong>探索权重</strong>
            </div>
            <label className="tune-control">
              <input
                className="editor-range"
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={state.tuning.exploration}
                onChange={(event) => applyTuning('exploration', Number(event.target.value))}
              />
              <strong>{state.tuning.exploration.toFixed(2)}</strong>
              <em>候选保留</em>
            </label>
          </article>

          <article className="tune-row">
            <div className="tune-name">
              <span>约束</span>
              <strong>负向容忍度</strong>
            </div>
            <label className="tune-control">
              <input
                className="editor-range"
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={state.tuning.penaltyTolerance}
                onChange={(event) => applyTuning('penaltyTolerance', Number(event.target.value))}
              />
              <strong>{state.tuning.penaltyTolerance.toFixed(2)}</strong>
              <em>抑制放宽</em>
            </label>
          </article>
        </div>
      </div>
    </div>
  );
}
