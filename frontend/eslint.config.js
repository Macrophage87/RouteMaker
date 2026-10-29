// The React hooks rules alone (`npm run lint`): a hook called conditionally or in a loop, and an
// effect, memo or callback that reads a value its dependency list leaves out (a stale closure).
// Nothing else: tsc checks the types and the tests the behaviour.
//
// The parser is Babel's with its TypeScript and JSX syntax, not typescript-eslint's, which does
// not support the TypeScript this project builds with; the hooks rules need the syntax only.
import babelParser from "@babel/eslint-parser";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  {
    ignores: ["dist/**", "node_modules/**", "notices/**", "public/**", "src/**/*.test.ts", "src/**/*.test.mjs"],
  },
  {
    files: ["src/**/*.{ts,tsx,js,mjs}"],
    languageOptions: {
      parser: babelParser,
      parserOptions: {
        requireConfigFile: false,
        babelOptions: { babelrc: false, configFile: false, parserOpts: { plugins: ["jsx", "typescript"] } },
      },
    },
    linterOptions: { reportUnusedDisableDirectives: "off" },
    plugins: { "react-hooks": reactHooks },
    // rules-of-hooks is an error, so `npm run lint` fails CI on a hook called conditionally or in a
    // loop (the owner, 2026-10-29). exhaustive-deps stays a warning while the existing reports are
    // worked through (the 2026-10-29 review): reported on every run, failing nothing yet.
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
];
