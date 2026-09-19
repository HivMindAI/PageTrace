import { describe, expect, it } from "vitest";

import { asArray, asRecord, compactId, parseJsonObject, titleCase } from "./format";

describe("display helpers", () => {
  it("compacts long identifiers without losing both ends", () => {
    expect(compactId("sha256-abcdefghijklmnopqrstuvwxyz", 5)).toBe("sha25…vwxyz");
    expect(compactId("short", 5)).toBe("short");
  });

  it("formats machine identifiers as labels", () => {
    expect(titleCase("minimum_query_term_coverage")).toBe("Minimum Query Term Coverage");
  });

  it("narrows JSON containers", () => {
    expect(asRecord({ ok: true })).toEqual({ ok: true });
    expect(asRecord([])).toBeNull();
    expect(asArray([1, 2])).toEqual([1, 2]);
    expect(asArray({})).toEqual([]);
  });

  it("accepts object JSON and rejects other values", () => {
    expect(parseJsonObject('{"suite":1}', "Suite")).toEqual({ suite: 1 });
    expect(() => parseJsonObject("[]", "Suite")).toThrow("Suite must be a JSON object.");
    expect(() => parseJsonObject("{", "Suite")).toThrow("Suite must be valid JSON.");
  });
});
