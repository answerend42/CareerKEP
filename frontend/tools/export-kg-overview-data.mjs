import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const nodesPath = resolve(root, "data/seeds/nodes.json");
const edgesPath = resolve(root, "data/seeds/edges.json");
const outputPath = resolve(root, "frontend/public/kg-overview-data.json");

function countBy(items, key) {
  return items.reduce((acc, item) => {
    const value = item[key] || "unknown";
    acc[value] = (acc[value] || 0) + 1;
    return acc;
  }, {});
}

const [nodes, edges] = await Promise.all([
  readFile(nodesPath, "utf8").then(JSON.parse),
  readFile(edgesPath, "utf8").then(JSON.parse),
]);

const payload = {
  schema_version: "career-kg-overview/v1",
  generated_at: new Date().toISOString(),
  source: {
    nodes: "data/seeds/nodes.json",
    edges: "data/seeds/edges.json",
  },
  stats: {
    node_count: nodes.length,
    edge_count: edges.length,
    layers: countBy(nodes, "layer"),
    node_types: countBy(nodes, "node_type"),
    relations: countBy(edges, "relation"),
  },
  nodes,
  edges,
};

await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`);
console.log(`Wrote ${outputPath}`);
