import { test, expect } from "vitest";
import { evidenceBand } from "./band";

test("bands map correctly", () => {
  expect(evidenceBand(0.8)).toBe("strong");
  expect(evidenceBand(0.5)).toBe("moderate");
  expect(evidenceBand(0.2)).toBe("weak");
});
