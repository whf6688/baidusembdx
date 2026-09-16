import { useMemo } from "react";
import BookingSelector from "react-booking-selector";
import styled from "styled-components";

export type WeeklyScheduleWindow = {
  weekDay: number;
  startHour: number;
  endHour: number;
};

const SELECTOR_YEAR = 2024;
const SELECTOR_MONTH = 0;
const SELECTOR_START = new Date(SELECTOR_YEAR, SELECTOR_MONTH, 1);
const WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

const WeeklyBookingSelector = styled(BookingSelector)`
  min-width: 0;
  height: 238px;

  > div {
    height: 238px;
  }

  > div > div:first-child,
  > div > div:not(:first-child) > :first-child {
    display: none;
  }

  > div > div:not(:first-child) {
    height: 238px;
  }

  button.rgdp__grid-cell {
    height: 34px;
    border-right: 1px solid var(--ads-border-subtle);
    border-bottom: 1px solid var(--ads-border-subtle);
    border-radius: 0;
    background: var(--ads-surface);
  }

  > div > div:last-child button.rgdp__grid-cell {
    border-right: 0;
  }

  button.rgdp__grid-cell:nth-child(8) {
    border-bottom: 0;
  }

  button.rgdp__grid-cell:hover:not(:disabled) {
    background: var(--ads-surface-selected);
  }

  button.rgdp__grid-cell:focus-visible {
    z-index: 1;
    border-radius: 0;
    outline: 1px solid var(--ads-primary);
    outline-offset: -1px;
  }
`;

function slotDate(weekDay: number, hour: number) {
  return new Date(SELECTOR_YEAR, SELECTOR_MONTH, hour + 1, weekDay - 1, 0, 0, 0);
}

export function scheduleWindowsToDates(windows: WeeklyScheduleWindow[]) {
  const dates: Date[] = [];
  windows.forEach(({ weekDay, startHour, endHour }) => {
    for (let hour = startHour; hour < endHour; hour += 1) {
      dates.push(slotDate(weekDay, hour));
    }
  });
  return dates;
}

export function datesToScheduleWindows(dates: Date[]) {
  const hoursByDay = new Map<number, Set<number>>();
  dates.forEach((date) => {
    const weekDay = date.getHours() + 1;
    const hour = date.getDate() - 1;
    if (weekDay < 1 || weekDay > 7 || hour < 0 || hour > 23) return;
    const hours = hoursByDay.get(weekDay) ?? new Set<number>();
    hours.add(hour);
    hoursByDay.set(weekDay, hours);
  });

  const windows: WeeklyScheduleWindow[] = [];
  for (let weekDay = 1; weekDay <= 7; weekDay += 1) {
    const hours = Array.from(hoursByDay.get(weekDay) ?? []).sort((a, b) => a - b);
    let start: number | null = null;
    let previous: number | null = null;
    hours.forEach((hour) => {
      if (start === null) {
        start = hour;
      } else if (previous !== null && hour !== previous + 1) {
        windows.push({ weekDay, startHour: start, endHour: previous + 1 });
        start = hour;
      }
      previous = hour;
    });
    if (start !== null && previous !== null) {
      windows.push({ weekDay, startHour: start, endHour: previous + 1 });
    }
  }
  return windows;
}

export function formatWeeklySchedule(windows: WeeklyScheduleWindow[]) {
  const selectedHours = windows.reduce(
    (total, window) => total + window.endHour - window.startHour,
    0,
  );
  if (!selectedHours) return "未选择时段";
  if (selectedHours === 168) return "全部时段";
  return windows
    .map(
      ({ weekDay, startHour, endHour }) =>
        `${WEEKDAY_LABELS[weekDay - 1]} ${String(startHour).padStart(2, "0")}:00–${String(endHour).padStart(2, "0")}:00`,
    )
    .join("；");
}

export function WeeklyScheduleSelector({
  value,
  onChange,
  disabled = false,
  ariaLabel = "每周时段",
  selectedLabel = "已选时段",
  unselectedLabel = "未选时段",
}: {
  value: WeeklyScheduleWindow[];
  onChange: (value: WeeklyScheduleWindow[]) => void;
  disabled?: boolean;
  ariaLabel?: string;
  selectedLabel?: string;
  unselectedLabel?: string;
}) {
  const selection = useMemo(() => scheduleWindowsToDates(value), [value]);
  const blocked = useMemo(
    () =>
      disabled
        ? Array.from({ length: 7 }, (_, day) =>
            Array.from({ length: 24 }, (_, hour) => slotDate(day + 1, hour)),
          ).flat()
        : [],
    [disabled],
  );

  return (
    <div className="weekly-schedule-selector">
      <div className="weekly-schedule-scroll">
        <div className="weekly-schedule-layout">
          <div className="weekly-schedule-corner">时段</div>
          <div className="weekly-schedule-hours" aria-hidden="true">
            {Array.from({ length: 24 }, (_, hour) => (
              <span key={hour}>{hour}</span>
            ))}
          </div>
          <div className="weekly-schedule-days" aria-hidden="true">
            {WEEKDAY_LABELS.map((label) => (
              <span key={label}>{label}</span>
            ))}
          </div>
          <WeeklyBookingSelector
            className="weekly-schedule-engine"
            aria-label={ariaLabel}
            startDate={SELECTOR_START}
            numDays={24}
            minTime={0}
            maxTime={6}
            margin={0}
            selectionScheme="square"
            selection={selection}
            blocked={blocked}
            onChange={(dates) => onChange(datesToScheduleWindows(dates))}
            renderDateCell={(date, selected) => (
              <span
                className={`weekly-schedule-cell${selected ? " is-selected" : ""}`}
                data-weekday={date.getHours() + 1}
                data-hour={date.getDate() - 1}
              />
            )}
          />
        </div>
      </div>
      <div className="weekly-schedule-footer">
        <div className="weekly-schedule-legend" aria-hidden="true">
          <span><i className="is-selected" />{selectedLabel}</span>
          <span><i />{unselectedLabel}</span>
        </div>
        <button
          type="button"
          className="weekly-schedule-clear"
          disabled={disabled || selection.length === 0}
          onClick={() => onChange([])}
        >
          清空
        </button>
      </div>
      <div className="weekly-schedule-summary" aria-live="polite">
        {formatWeeklySchedule(value)}
      </div>
    </div>
  );
}
