import { expect, test } from "@playwright/test";
import { graphConnection } from "../src/lib/graph-layout";

const visible = new Set(["a", "b", "c", "isolated"]);
const edges = [
  { id: "ab", source: "a", target: "b" },
  { id: "ba", source: "b", target: "a" },
  { id: "cb", source: "c", target: "b" },
];

test("a connection retains one exact edge per hop independent of response order", () => {
  for (const ordered of [edges, [...edges].reverse()]) {
    const result = graphConnection(ordered, visible, "a", "c");
    expect(result.status).toBe("found");
    expect([...result.nodes].sort()).toEqual(["a", "b", "c"]);
    expect([...result.edges].sort()).toEqual(["ab", "cb"]);
  }
});

test("a connection never walks hidden intermediates or merges distinct identities", () => {
  expect(graphConnection(edges, new Set(["a", "c"]), "a", "c").status).toBe(
    "disconnected",
  );
  expect(graphConnection(edges, visible, "a", "isolated").status).toBe(
    "disconnected",
  );
  expect(graphConnection(edges, visible, "a", "other-account:a").status).toBe(
    "hidden",
  );
  expect(graphConnection(edges, visible, null, "a").status).toBe("idle");
});

test("same-node selection and cycles do not invent traversed edges", () => {
  const result = graphConnection(edges, visible, "a", "a");
  expect(result.status).toBe("same");
  expect([...result.edges]).toEqual([]);
  const cycle = [...edges, { id: "self", source: "a", target: "a" }];
  expect([...graphConnection(cycle, visible, "a", "c").edges].sort()).toEqual([
    "ab",
    "cb",
  ]);
});
