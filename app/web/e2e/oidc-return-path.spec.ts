import { expect, test } from "@playwright/test";

for (const target of [
  "/console/graph/?root=safeguard%3ASG-IDENTITY-001#details",
  "/console/evidence/?id=record-one",
  "https://example.com",
  "/console/../api/",
  "/console/%252e%252e/api/",
]) {
  test(`OIDC sign-in carries only a safe console destination: ${target}`, async ({
    page,
  }) => {
    await page.route("**/api/v1/auth/methods", (route) =>
      route.fulfill({
        json: {
          data: {
            require_auth: true,
            methods: [
              {
                id: "oidc",
                label: "Sign in with SSO",
                configured: true,
                login_url: "/api/v1/auth/login",
                provider_label: "Company SSO",
                provider_kind: "oidc",
              },
            ],
          },
        },
      }),
    );
    await page.goto(`/console/login/?return_to=${encodeURIComponent(target)}`);
    const link = page.getByRole("link", {
      name: "Sign in with SSO",
      exact: true,
    });
    const expected =
      target.includes("graph") || target.includes("evidence")
        ? target
        : "/console/dashboard";
    await expect(link).toHaveAttribute(
      "href",
      `/api/v1/auth/login?return_to=${encodeURIComponent(expected)}`,
    );
  });
}
