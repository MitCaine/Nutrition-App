// Jest exposes `global` as an alias of the test environment's global object.
// TypeScript 6 no longer loads transitive @types/node globals implicitly.
declare const global: typeof globalThis;
