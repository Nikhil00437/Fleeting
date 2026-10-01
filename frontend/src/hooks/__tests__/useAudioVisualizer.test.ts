import { describe, expect, it } from "vitest";
import { WAVE_BARS, smoothLevels, useAudioVisualizer } from "../useAudioVisualizer";

describe("audio visualizer smoothing", () => {
  it("smooths incoming audio frequency buckets", () => {
    const prev = [0, 0, 0];
    const target = [1, 0.5, 0.2];
    const result = smoothLevels(prev, target);
    expect(result[0]).toBeCloseTo(0.3);
    expect(result[1]).toBeCloseTo(0.15);
    expect(result[2]).toBeCloseTo(0.06);
  });

  it("handles custom smoothing weight factor", () => {
    const prev = [0.5, 0.5];
    const target = [1.0, 0.0];
    // With smoothing factor 0.8: prev * 0.8 + target * 0.2
    const result = smoothLevels(prev, target, 0.8);
    expect(result[0]).toBeCloseTo(0.4 + 0.2); // 0.6
    expect(result[1]).toBeCloseTo(0.4 + 0.0); // 0.4
  });

  it("handles missing target elements gracefully", () => {
    const prev = [0.8, 0.4];
    const target = [1.0]; // second element missing
    const result = smoothLevels(prev, target);
    expect(result[0]).toBeCloseTo(0.8 * 0.7 + 1.0 * 0.3);
    expect(result[1]).toBeCloseTo(0.4 * 0.7 + 0 * 0.3);
  });

  it("handles 9-bar array dimensions matching WAVE_BARS", () => {
    expect(WAVE_BARS).toBe(9);
    const prev = Array(WAVE_BARS).fill(0);
    const target = Array(WAVE_BARS).fill(1);
    const result = smoothLevels(prev, target);
    expect(result).toHaveLength(9);
    result.forEach((val) => {
      expect(val).toBeCloseTo(0.3);
    });
  });

  it("exports useAudioVisualizer hook function", () => {
    expect(typeof useAudioVisualizer).toBe("function");
  });
});
