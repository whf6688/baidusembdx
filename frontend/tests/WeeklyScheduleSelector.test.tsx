import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  datesToScheduleWindows,
  formatWeeklySchedule,
  scheduleWindowsToDates,
  WeeklyScheduleSelector,
} from "../src/ui/WeeklyScheduleSelector";

describe("WeeklyScheduleSelector conversions", () => {
  it("round trips independent weekday windows", () => {
    const windows = [
      { weekDay: 1, startHour: 8, endHour: 12 },
      { weekDay: 1, startHour: 14, endHour: 18 },
      { weekDay: 5, startHour: 9, endHour: 24 },
    ];
    expect(datesToScheduleWindows(scheduleWindowsToDates(windows))).toEqual(windows);
  });

  it("compresses adjacent selected cells into one window", () => {
    const dates = scheduleWindowsToDates([
      { weekDay: 3, startHour: 8, endHour: 9 },
      { weekDay: 3, startHour: 9, endHour: 11 },
    ]);
    expect(datesToScheduleWindows(dates)).toEqual([
      { weekDay: 3, startHour: 8, endHour: 11 },
    ]);
  });

  it("formats empty and full-week selections", () => {
    expect(formatWeeklySchedule([])).toBe("未选择时段");
    expect(
      formatWeeklySchedule(
        Array.from({ length: 7 }, (_, index) => ({
          weekDay: index + 1,
          startHour: 0,
          endHour: 24,
        })),
      ),
    ).toBe("全部时段");
  });

  it("allows each platform to provide its own selected and unselected semantics", () => {
    render(
      <WeeklyScheduleSelector
        value={[]}
        onChange={() => undefined}
        ariaLabel="每周计划启用时段"
        selectedLabel="启用时段"
        unselectedLabel="暂停时段"
      />,
    );
    expect(screen.getByRole("group", { name: "每周计划启用时段" })).toBeInTheDocument();
    expect(screen.getByText("启用时段")).toBeInTheDocument();
    expect(screen.getByText("暂停时段")).toBeInTheDocument();
  });
});
