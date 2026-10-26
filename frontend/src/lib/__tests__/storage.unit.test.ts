import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { readStored, useStored, writeStored } from "@/lib/storage";

const EMPTY: string[] = [];

describe("localStorage as a store", () => {
  beforeEach(() => window.localStorage.clear());

  it("reads the fallback, keeps one reference while the string is unchanged, and re-parses on a write", () => {
    expect(readStored("k", EMPTY)).toBe(EMPTY);
    writeStored("k", ["a"]);
    const first = readStored("k", EMPTY);
    expect(first).toEqual(["a"]);
    expect(readStored("k", EMPTY)).toBe(first);
    writeStored("k", ["a", "b"]);
    expect(readStored("k", EMPTY)).toEqual(["a", "b"]);
  });

  it("a hook on the key updates on a write and not on a write of the same value", () => {
    const { result } = renderHook(() => useStored("votes", EMPTY));
    expect(result.current[0]).toBe(EMPTY);
    act(() => writeStored("votes", ["x"]));
    const after = result.current[0];
    expect(after).toEqual(["x"]);
    act(() => writeStored("votes", ["x"]));
    expect(result.current[0]).toBe(after);
    act(() => result.current[1](["x", "y"]));
    expect(result.current[0]).toEqual(["x", "y"]);
    expect(window.localStorage.getItem("votes")).toBe('["x","y"]');
  });

  it("re-rendering a hook does not churn its subscription", () => {
    const { result, rerender } = renderHook(() => useStored("threads", EMPTY));
    rerender();
    rerender();
    // the subscriber is memoised per key: a write after several renders still reaches the hook exactly once
    act(() => writeStored("threads", ["t1"]));
    expect(result.current[0]).toEqual(["t1"]);
  });
});
