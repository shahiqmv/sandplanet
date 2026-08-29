// A deliberately small lint gate. Its whole job is `no-undef`.
//
// Two bugs have now shipped from an identifier that nothing defines:
// `setPayFx`, left behind when the per-payment FX field was removed, which
// blanked the payment-vouchers page for signatories; and `ghostButton`, used
// in the procurement planner without being imported, caught only because the
// first one had just taught us to look. Vite bundles both happily — they are
// valid JavaScript, they just throw at runtime, and React turns a throw
// inside an effect into a white screen.
//
// Style is not policed here. The rules are the ones that catch code which
// cannot possibly work.
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser, ...globals.serviceworker },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...js.configs.recommended.rules,
      "no-undef": "error",
      // Registered so the existing eslint-disable comments resolve, and
      // warn-only: dependency arrays are a judgement call, an identifier
      // that does not exist is not.
      "react-hooks/rules-of-hooks": "warn",
      "react-hooks/exhaustive-deps": "warn",
      // JSX makes a component look unused to the base parser, and unused
      // variables are untidy rather than broken — off, so the signal stays
      // sharp.
      "no-unused-vars": "off",
      "no-empty": "off",
      "no-useless-escape": "off",
    },
  },
];
