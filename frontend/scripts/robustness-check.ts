import {
  buildDiagnosticExport,
  buildDiagnosticSnapshot,
  buildRecommendationResponse,
  buildRobustnessReport,
  defaultDemoState,
  scenarioPresets
} from '../src/app/demoData.ts';

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

function almostEqual(left: number, right: number, epsilon = 1e-6): boolean {
  return Math.abs(left - right) <= epsilon;
}

const normalPresets = scenarioPresets.filter((item) => item.kind === 'normal');
const stressPresets = scenarioPresets.filter((item) => item.kind === 'stress');

const backendResponse = buildRecommendationResponse(normalPresets.find((item) => item.id === 'backend')!.state);
assert(backendResponse.recommendations[0]?.label === '后端开发工程师', '后端场景应该优先推荐后端开发工程师');

const frontendResponse = buildRecommendationResponse(normalPresets.find((item) => item.id === 'frontend')!.state);
assert(frontendResponse.recommendations[0]?.label === '前端开发工程师', '前端场景应该优先推荐前端开发工程师');

const dataResponse = buildRecommendationResponse(normalPresets.find((item) => item.id === 'data')!.state);
assert(dataResponse.recommendations[0]?.label === '数据工程师', '数据场景应该优先推荐数据工程师');

const mixedResponse = buildRecommendationResponse(stressPresets.find((item) => item.id === 'mixed')!.state);
assert(mixedResponse.recommendations.length > 0, '中英混合输入至少应保留一条推荐');
assert(mixedResponse.propagationSnapshot.layers.length === 5, '传播快照应该保持五层结构');

const conflictResponse = buildRecommendationResponse(stressPresets.find((item) => item.id === 'conflict')!.state);
assert(
  conflictResponse.inputTrace.signalTrace.negatedSignals.includes('不擅长 C++'),
  '冲突输入应该识别出不擅长 C++ 这个否定信号'
);
assert(conflictResponse.inputTrace.signalTrace.clauses.length >= 2, '冲突输入应该能切分出多个句子片段');

const sparseResponse = buildRecommendationResponse(stressPresets.find((item) => item.id === 'sparse')!.state);
assert(sparseResponse.bridgeRecommendations.length > 0, '稀疏输入应该保留桥接建议');

const defaultReport = buildRobustnessReport(defaultDemoState);
assert(defaultReport.cases.length === stressPresets.length, '鲁棒性报告应覆盖全部极端场景');
assert(defaultReport.averageTopScore >= 0 && defaultReport.averageTopScore <= 1, '平均最高分应该在 0 到 1 之间');
assert(defaultReport.averageDelta >= -1 && defaultReport.averageDelta <= 1, '平均变化应该在合理范围内');
assert(defaultReport.improvedCount >= 0 && defaultReport.improvedCount <= defaultReport.cases.length, '改善场景数应该在合理范围内');
assert(defaultReport.fragileCount >= 0 && defaultReport.fragileCount <= defaultReport.cases.length, '脆弱场景计数应在合理范围内');
assert(defaultReport.bestImprovementLabel.length > 0, '最佳提升场景标签不能为空');
assert(defaultReport.worstRegressionLabel.length > 0, '最差回落场景标签不能为空');
assert(defaultReport.tuningAdvice.length >= 2, '调参建议至少应包含两条');
assert(defaultReport.tuningAdvice.some((item) => item.includes('探索权重')), '调参建议应包含探索权重提示');
assert(defaultReport.cases.every((item) => item.coverage >= 0 && item.coverage <= 1), '覆盖率必须在 0 到 1 之间');
assert(defaultReport.cases.every((item) => item.baselineTopScore >= 0 && item.baselineTopScore <= 1), '默认权重分数必须在 0 到 1 之间');

const boostedReport = buildRobustnessReport({
  ...defaultDemoState,
  tuning: {
    confidence: 1,
    exploration: 1,
    penaltyTolerance: 0
  }
});

assert(
  boostedReport.averageTopScore >= defaultReport.averageTopScore || almostEqual(boostedReport.averageTopScore, defaultReport.averageTopScore),
  '提高信心和探索后，平均最高分不应下降'
);

const diagnosticSnapshot = buildDiagnosticSnapshot('结果解释', defaultDemoState, backendResponse, defaultReport);
assert(diagnosticSnapshot.generatedAt.length > 0, '诊断快照应该有生成时间');
assert(diagnosticSnapshot.activeStep === '结果解释', '诊断快照应该记录当前阶段');
assert(diagnosticSnapshot.recommendation.recommendations.length > 0, '诊断快照应该包含推荐结果');
assert(diagnosticSnapshot.robustness.tuningAdvice.length > 0, '诊断快照应该包含鲁棒性建议');

const exportResult = buildDiagnosticExport(diagnosticSnapshot);
const diagnosticFilename = exportResult.filename;
assert(diagnosticFilename.startsWith('career-kg-结果解释-后端开发工程师'), '诊断快照文件名应该包含阶段和目标岗位');
assert(!/[\\/:*?"<>| ]/.test(diagnosticFilename), '诊断快照文件名不应包含非法字符或空格');
assert(JSON.parse(exportResult.content).generatedAt === diagnosticSnapshot.generatedAt, '导出内容应该能稳定序列化为 JSON');

console.log(
  [
    '鲁棒性烟测通过',
    `正常场景 ${normalPresets.length} 个`,
    `极端场景 ${stressPresets.length} 个`,
    `默认报告脆弱场景 ${defaultReport.fragileCount} 个`
  ].join(' | ')
);
