const queryKeys = new Set([
  "view",
  "root",
  "depth",
  "version",
  "layers",
  "limit",
  "root_offset",
  "search",
]);

const rootKinds = {
  controls: new Set([
    "control",
    "safeguard",
    "ccf_category",
    "ccf_family",
    "framework",
  ]),
  environment: new Set([
    "environment",
    "account",
    "repository",
    "asset",
    "canonical_entity",
    "entity_alias",
  ]),
  investigation: new Set(["finding", "source", "vendor", "evidence_type"]),
};

// Only offer roots whose exact standard queries exist at every offered depth,
// including pinned navigation and unpinned refresh. Never infer a missing slice.
export function buildGraphNavigation(recorded, origin, layers) {
  const candidates = new Map();
  for (const [key, { status, body }] of recorded) {
    const url = new URL(key, origin);
    const params = url.searchParams;
    const view = params.get("view");
    if (
      status !== 200 ||
      url.pathname !== "/api/v1/graph/investigation" ||
      [...params.keys()].some((key) => !queryKeys.has(key)) ||
      !Object.hasOwn(rootKinds, view) ||
      !params.get("root") ||
      params.get("layers") !== layers ||
      params.get("limit") !== "150" ||
      params.get("root_offset") !== "0" ||
      params.get("search") ||
      params.has("framework") ||
      params.has("control_offset")
    )
      continue;
    const data = JSON.parse(body).data;
    const node = data?.nodes.find((node) => node.id === params.get("root"));
    if (
      !node ||
      data.depth !== Number(params.get("depth")) ||
      data.root !== node.id ||
      data.root_missing ||
      !data.version ||
      !rootKinds[view].has(node.kind) ||
      (params.has("version") && params.get("version") !== data.version)
    )
      continue;
    const identity = JSON.stringify([view, node.id, data.version]);
    const candidate = candidates.get(identity) ?? {
      view,
      node: {
        id: node.id,
        label: node.label,
        kind: node.kind,
        version: data.version,
      },
      variants: new Set(),
    };
    candidate.variants.add(`${params.get("depth")}:${params.has("version")}`);
    candidates.set(identity, candidate);
  }
  const views = Object.fromEntries(
    Object.keys(rootKinds).map((view) => [view, []]),
  );
  for (const { view, node, variants } of candidates.values()) {
    if (
      [1, 2, 3].every((depth) =>
        [false, true].every((pinned) => variants.has(`${depth}:${pinned}`)),
      )
    )
      views[view].push(node);
  }
  for (const nodes of Object.values(views))
    nodes.sort(
      (a, b) => a.label.localeCompare(b.label) || a.id.localeCompare(b.id),
    );
  return views;
}
