import { readFileSync } from "node:fs";
import ts from "typescript";

/** Import a dependency-free TypeScript module from Node without a build. */
export async function loadTsModule(fileUrl) {
  const source = readFileSync(fileUrl, "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
  );
}
