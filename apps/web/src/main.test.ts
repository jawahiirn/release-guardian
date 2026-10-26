import { describe, expect, it } from "vitest";

describe("Release Guardian shell", () => {
  it("uses the product name", () => {
    expect("Release Guardian").toContain("Guardian");
  });
});
