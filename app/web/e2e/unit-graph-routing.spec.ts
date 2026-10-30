import { expect, test } from "@playwright/test";
import {
  investigationPositions,
  investigationRoute,
} from "../src/lib/graph-layout";

const nodes = [
  { id: "f", kind: "framework", label: "Framework" },
  { id: "c", kind: "control", label: "Control" },
  { id: "s", kind: "source", label: "Source", source_account_id: "a" },
  { id: "e", kind: "evidence_type", label: "Evidence" },
  { id: "a", kind: "asset", label: "Asset" },
  { id: "s2", kind: "source", label: "Source", source_account_id: "b" },
  { id: "e2", kind: "evidence_type", label: "Evidence" },
];
const edges = [
  { id: "fc", source: "f", target: "c", kind: "framework_has_control" },
  { id: "ce", source: "c", target: "e", kind: "control_requires_evidence" },
  { id: "se", source: "s", target: "e", kind: "produces" },
  { id: "ea", source: "e", target: "a", kind: "evidence_covers_asset" },
  { id: "s2e2", source: "s2", target: "e2", kind: "produces" },
];

test("assurance stays above lineage, recorded chains align, accounts stay distinct", () => {
  const p = investigationPositions(nodes, edges);
  expect(p.get("c")!.y + 92).toBeLessThan(p.get("s")!.y);
  expect(p.get("s")!.y).toBe(p.get("e")!.y);
  expect(p.get("e")!.y).toBe(p.get("a")!.y);
  expect(p.get("s")!.x).toBeLessThan(p.get("e")!.x);
  expect(p.get("e")!.x).toBeLessThan(p.get("a")!.x);
  expect(p.get("s2")).not.toEqual(p.get("s"));
  expect(
    investigationPositions([...nodes].reverse(), [...edges].reverse()),
  ).toEqual(p);
});

test("orthogonal routes keep every link outside all other card interiors", () => {
  const p = investigationPositions(nodes, edges);
  const boxes = nodes.map((n) => ({
    id: n.id,
    ...p.get(n.id)!,
    width: 220,
    height: 92,
  }));
  for (const edge of [
    ...edges,
    { id: "reverse", source: "a", target: "f", kind: "test" },
    { id: "same", source: "s", target: "s2", kind: "test" },
  ]) {
    const s = p.get(edge.source)!;
    const t = p.get(edge.target)!;
    const route = investigationRoute(
      { x: s.x + 220, y: s.y + 46 },
      { x: t.x, y: t.y + 46 },
      boxes,
    );
    expect(route.length).toBeGreaterThan(1);
    for (let i = 1; i < route.length; i++) {
      const a = route[i - 1],
        b = route[i];
      expect(a.x === b.x || a.y === b.y).toBe(true);
      for (const box of boxes) {
        const crosses =
          a.x === b.x
            ? a.x > box.x &&
              a.x < box.x + box.width &&
              Math.max(a.y, b.y) > box.y &&
              Math.min(a.y, b.y) < box.y + box.height
            : a.y > box.y &&
              a.y < box.y + box.height &&
              Math.max(a.x, b.x) > box.x &&
              Math.min(a.x, b.x) < box.x + box.width;
        expect(crosses, `${edge.id} crosses ${box.id}`).toBe(false);
      }
    }
  }
});

test("a 500-node bounded graph retains routable links without expensive layout", () => {
  const records = Array.from({ length: 500 }, (_, i) => ({
    id: String(i),
    label: `Record ${i}`,
    kind:
      i < 50
        ? "control"
        : i < 100
          ? "source"
          : i < 300
            ? "evidence_type"
            : "asset",
  }));
  const links = Array.from({ length: 200 }, (_, i) => [
    { source: String(i % 50), target: String(i + 100) },
    { source: String(50 + (i % 50)), target: String(i + 100) },
    { source: String(i + 100), target: String(i + 300) },
  ]).flat();
  const started = performance.now();
  const positions = investigationPositions(records, links);
  const boxes = records.map((n) => ({
    ...positions.get(n.id)!,
    width: 220,
    height: 92,
  }));
  for (const link of links) {
    const s = positions.get(link.source)!,
      t = positions.get(link.target)!;
    expect(
      investigationRoute(
        { x: s.x + 220, y: s.y + 46 },
        { x: t.x, y: t.y + 46 },
        boxes,
      ).length,
    ).toBeGreaterThan(1);
  }
  expect(positions.size).toBe(500);
  expect(performance.now() - started).toBeLessThan(5000);
});

test("assurance links enter the top of evidence without sharing the source arrow", () => {
  const p = investigationPositions(nodes, edges);
  const boxes = nodes.map((n) => ({ ...p.get(n.id)!, width: 220, height: 92 }));
  const s = p.get("c")!,
    t = p.get("e")!;
  const route = investigationRoute(
    { x: s.x + 220, y: s.y + 46 },
    { x: t.x + 110, y: t.y },
    boxes,
    0,
    "top",
  );
  expect(route.length).toBeGreaterThan(1);
  expect(route.at(-2)!.x).toBe(t.x + 110);
  expect(route.at(-2)!.y).toBeLessThan(t.y);
});
