import { expect, test } from "@playwright/test";
import taxonomy from "../../../controls/families.json";
import { controlFamily } from "../src/components/framework/ControlFamilyIcon";

test("all console family names match the canonical CCF taxonomy", () => {
  for (const family of taxonomy.families) {
    expect(controlFamily(family.family_id).label, family.family_id).toBe(
      family.label,
    );
  }
  expect(controlFamily("unknown-family").label).toBe("unknown family");
});

type Coverage = {
  categories: { category_id: string; label: string; family_ids: string[] }[];
  families: { family_id: string; label: string; category_id: string }[];
};

test("control families render under their categories and link to review", async ({
  page,
}) => {
  const { data } = (await (
    await page.request.get("/api/v1/ccf/coverage")
  ).json()) as { data: Coverage };
  expect(data.categories.length).toBeGreaterThan(0);

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/console/dashboard/");
  await page
    .getByRole("tab", { name: "Control families", exact: true })
    .click();
  const panel = page.getByRole("tabpanel", { name: "Control families" });
  const sections = panel.locator("section[data-category]");
  await expect(sections).toHaveCount(data.categories.length);

  // The list scrolls inside the tab, so its scope is stated up front.
  await expect(
    panel.getByText(
      `${data.categories.length} categories · ${data.families.length} families`,
    ),
  ).toBeVisible();

  // Headings render in taxonomy order, each holding exactly its families.
  await expect(panel.getByRole("heading", { level: 3 })).toHaveText(
    data.categories.map((row) => row.label),
  );
  const seen = new Set<string>();
  for (const category of data.categories) {
    const section = panel.locator(
      `section[data-category="${category.category_id}"]`,
    );
    const ids = await section
      .locator("details[data-family]")
      .evaluateAll((nodes) =>
        nodes.map((node) => node.getAttribute("data-family") ?? ""),
      );
    expect(ids).toEqual(category.family_ids);
    for (const id of ids) {
      expect(seen.has(id), `${id} appears in two categories`).toBe(false);
      seen.add(id);
    }
  }
  expect(seen.size).toBe(data.families.length);

  const family = data.families.find((row) => row.family_id === "identity")!;
  expect(family.label).toBe("Identity and access management");
  const row = panel.locator('details[data-family="identity"]');
  await row.locator("summary").click();
  await row
    .getByRole("link", { name: `Review ${family.label} mappings` })
    .click();
  await expect(page).toHaveURL(/\/mapping-review\/\?family=identity/);
  await expect(page.getByLabel("Filter by family")).toHaveValue("identity");
});

test("control families stay inside the viewport on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/console/dashboard/");
  await page
    .getByRole("tab", { name: "Control families", exact: true })
    .click();
  const panel = page.getByRole("tabpanel", { name: "Control families" });
  const iam = panel.locator('details[data-family="identity"]');
  await iam.locator("summary").click();
  const name = iam.getByText("Identity and access management", { exact: true });
  await expect(name).toBeVisible();
  expect(
    await name.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("crosswalk displays the canonical IAM name instead of its internal id", async ({
  page,
}) => {
  await page.goto("/console/crosswalk/");
  const groups = page.locator("#equivalence-groups");
  await expect(
    groups.getByText("Identity and access management", { exact: true }).first(),
  ).toBeVisible();
  await expect(groups.getByText("identity", { exact: true })).toHaveCount(0);
});
