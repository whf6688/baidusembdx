import type { KeywordTierRules } from "./types";

export type KeywordTierRuleField = {
  key: keyof KeywordTierRules;
  label: string;
  suffix: string;
  step: string;
  min: string;
  description: string;
};

export const keywordTierRuleFields: KeywordTierRuleField[] = [
  {
    key: "a_add_cost_max",
    label: "A 实际加粉成本上限",
    suffix: "元",
    step: "0.01",
    min: "0.01",
    description: "累计消费 ÷ 累计加粉数不高于该值时，判为 A 级。",
  },
  {
    key: "b_next_add_cost_max",
    label: "B 假设再加 1 粉成本上限",
    suffix: "元",
    step: "0.01",
    min: "0.01",
    description: "未命中 A 时，按再增加 1 个粉后的成本判断是否进入 B 级。",
  },
  {
    key: "c_add_growth_factor",
    label: "C 推算加粉倍数",
    suffix: "倍",
    step: "0.01",
    min: "1.01",
    description: "用当前加粉数乘以该倍数，推算 C 级可能达到的加粉量。",
  },
  {
    key: "c_projected_cost_max",
    label: "C 推算成本上限",
    suffix: "元",
    step: "0.01",
    min: "0.01",
    description: "推算后的加粉成本低于该值时，判为 C 级。",
  },
  {
    key: "empty_spend_min",
    label: "无粉空耗消费起点",
    suffix: "元",
    step: "0.01",
    min: "0.01",
    description: "没有加粉且累计消费达到该值时，判为空耗并进入黑名单。",
  },
  {
    key: "d_spend_min",
    label: "无粉 D 级最低消费",
    suffix: "元",
    step: "0.01",
    min: "0",
    description: "没有加粉且消费达到该值、但低于空耗起点时，判为 D 级。",
  },
];

export const keywordTierRuleFieldMap = Object.fromEntries(
  keywordTierRuleFields.map((field) => [field.key, field]),
) as Record<keyof KeywordTierRules, KeywordTierRuleField>;
