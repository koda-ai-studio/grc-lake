import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`AWS setup submits exactly the account scope shown at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.route("**/api/v1/connectors?*", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.data = body.data.map((row: { connector_id: string }) =>
        row.connector_id === "aws-posture"
          ? {
              ...row,
              state: "disabled",
              last_probe: null,
              last_sync: null,
              configured_options: {},
            }
          : row,
      );
      await route.fulfill({ response, json: body });
    });
    await page.route("**/api/v1/connectors/aws-posture/link/start", (route) =>
      route.fulfill({
        json: {
          data: {
            session_id: "synthetic-scope-session",
            connector_id: "aws-posture",
            status: "pending",
            role_name: "GrcLakePostureReadOnlyRole",
            external_id: "synthetic-external-id",
            runtime_identity_ready: true,
            trusted_principal: "arn:aws:iam::222222222222:role/Runtime",
            cloudshell_command:
              "aws cloudformation deploy --template-file readonly-role.yaml",
          },
        },
      }),
    );
    let submitted: Record<string, unknown> | undefined;
    await page.route(
      "**/api/v1/connectors/aws-posture/link/complete",
      async (route) => {
        submitted = route.request().postDataJSON();
        await route.fulfill({
          json: {
            data: {
              configure: {
                credentials: {
                  account_id: "111111111111",
                  role_arn: submitted?.role_arn,
                },
              },
            },
          },
        });
      },
    );
    await page.goto("/console/connectors/?connect=aws-posture");
    const dialog = page.getByRole("dialog");
    await dialog
      .getByRole("button", { name: "Connect cloud account", exact: true })
      .click();
    await expect(dialog).toContainText("One active AWS account per workspace");
    await expect(dialog).toContainText(
      "does not discover or sync organization members",
    );
    await expect(
      dialog.getByRole("button", {
        name: /AWS Organization|Selected accounts/,
      }),
    ).toHaveCount(0);
    await dialog
      .getByRole("button", { name: "2. Configure target", exact: true })
      .click();
    await expect(
      dialog.getByRole("button", { name: "Add another account" }),
    ).toHaveCount(0);
    await expect(
      dialog.getByPlaceholder("AWS account ID or role ARN"),
    ).toHaveCount(1);
    await dialog
      .getByLabel("Account ID or Role ARN", { exact: true })
      .fill("111111111111");
    await expect(dialog).toContainText(
      "Changing the target replaces the current connection",
    );
    await expect(
      dialog.getByRole("button", { name: "Next: verify access", exact: true }),
    ).toBeEnabled();
    for (const colorScheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme });
      await expect(page.locator("html")).toHaveAttribute(
        "data-theme",
        colorScheme,
      );
      await page.screenshot({
        path: testInfo.outputPath(`account-target-${colorScheme}.png`),
        animations: "disabled",
      });
    }
    await dialog
      .getByRole("button", { name: "Next: verify access", exact: true })
      .click();
    await expect
      .poll(() => submitted?.role_arn)
      .toBe("arn:aws:iam::111111111111:role/GrcLakePostureReadOnlyRole");
    expect(submitted).not.toHaveProperty("account_ids");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}
