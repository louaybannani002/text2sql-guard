import { GUARDRAIL_LAYERS } from "./api/types";
import { LAYERS, codeLabel, layerInfo } from "./guardrails";

describe("guardrails", () => {
  it("describes every layer the API can report, in pipeline order", () => {
    expect(LAYERS.map((l) => l.layer)).toEqual([...GUARDRAIL_LAYERS]);
    for (const layer of GUARDRAIL_LAYERS) expect(layerInfo(layer).name).toBeTruthy();
  });

  it("labels known codes and falls back to a readable code", () => {
    expect(codeLabel("prompt_injection")).toMatch(/override/);
    expect(codeLabel("read_only")).toBe("The query tried to change data");
    expect(codeLabel("brand_new_rule")).toBe("brand new rule");
  });
});
