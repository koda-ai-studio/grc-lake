import { access, cp, mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { assertPackageBundle } from "./static_export_guard.mjs";

const source = new URL("../out/", import.meta.url);
const destination = new URL("../../../src/security_lakehouse/web/dist/", import.meta.url);

// A failed or missing export must never remove the last usable package bundle.
await access(new URL("index.html", source));
await assertPackageBundle(fileURLToPath(source));
await rm(destination, { recursive: true, force: true });
await mkdir(destination, { recursive: true });
await cp(source, destination, { recursive: true });
console.log(`Static console copied to ${fileURLToPath(destination)}`);
