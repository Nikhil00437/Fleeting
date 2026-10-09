/**
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import ChartPalettePicker from "../ChartPalettePicker";
import { getActivePaletteId } from "../../chartPalettes";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("ChartPalettePicker component (#175)", () => {
  it("renders inline palette selection and switches to Okabe-Ito", () => {
    render(<ChartPalettePicker variant="inline" />);

    const radioGroup = screen.getByRole("radiogroup");
    expect(radioGroup).toBeTruthy();

    const okabeItoBtn = screen.getByRole("radio", { name: /Colorblind-Safe/i });
    expect(okabeItoBtn).toBeTruthy();

    fireEvent.click(okabeItoBtn);
    expect(getActivePaletteId()).toBe("okabe_ito");
    expect(okabeItoBtn.getAttribute("aria-checked")).toBe("true");
  });

  it("renders compact dropdown variant and switches palette", () => {
    render(<ChartPalettePicker variant="compact" />);

    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select).toBeTruthy();
    expect(select.value).toBe("default");

    fireEvent.change(select, { target: { value: "high_contrast" } });
    expect(getActivePaletteId()).toBe("high_contrast");
    expect(select.value).toBe("high_contrast");
  });
});
