import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const graphBundlePath = resolve(root, "data/entity_expansion/llm_expanded_graph.clean.json");
const outputPath = resolve(root, "frontend/public/kg-overview-data.json");

function countBy(items, key) {
  return items.reduce((acc, item) => {
    const value = item[key] || "unknown";
    acc[value] = (acc[value] || 0) + 1;
    return acc;
  }, {});
}

function normalizeRelation(relation) {
  const value = String(relation || "").trim().toLowerCase();
  if (["support", "supports", "evidence", "evidences"].includes(value)) {
    return "supports";
  }
  return value || "unknown";
}

const graphBundle = await readFile(graphBundlePath, "utf8").then(JSON.parse);
const nodes = graphBundle.nodes || [];
const edges = graphBundle.edges || [];

const runtimeEdges = edges.map((edge) => ({
  ...edge,
  relation: normalizeRelation(edge.relation),
}));

const payload = {
  schema_version: "career-kg-overview/v1",
  generated_at: new Date().toISOString(),
  source: {
    graph_bundle: "data/entity_expansion/llm_expanded_graph.clean.json",
  },
  stats: {
    node_count: nodes.length,
    edge_count: runtimeEdges.length,
    layers: countBy(nodes, "layer"),
    node_types: countBy(nodes, "node_type"),
    relations: countBy(runtimeEdges, "relation"),
  },
  nodes,
  edges: runtimeEdges,
};

await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`);
console.log(`Wrote ${outputPath}`);
