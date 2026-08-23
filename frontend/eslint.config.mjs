// Flat config — required by ESLint 9+ and by Next 16, which removed `next lint`.
// eslint-config-next 16 ships flat-config arrays directly, so no compat layer.
import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescriptConfig from "eslint-config-next/typescript";

const config = [
  {
    ignores: [".next/**", "node_modules/**", "next-env.d.ts", "*.tsbuildinfo"],
  },
  ...coreWebVitals,
  ...typescriptConfig,
  {
    rules: {
      // The marketing footer intentionally links to hash anchors on "/".
      "@next/next/no-html-link-for-pages": "off",
    },
  },
];

export default config;
