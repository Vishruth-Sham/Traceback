"use client";

import { Suspense, useState } from "react";
import useSWR from "swr";
import { completeTask, listTasks, reopenTask } from "@/lib/traceback";
import {
  formatDayLabel,
  groupOpenTasks,
  groupTasksForDay,
  isDayString,
  shiftDay,
  toDayString,
} from "@/lib/taskGrouping";
import { Item } from "@/lib/types";
import { TaskRow } from "@/components/TaskRow";
import { TaskQuickAdd } from "@/components/TaskQuickAdd";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { ItemDetailPanel } from "@/components/ItemDetailPanel";
import { useDetailPanel } from "@/lib/useDetailPanel";
import { useToast } from "@/components/Toast";
import { PageHeader } from "@/components/PageHeader";
import { Segmented } from "@/components/Segmented";
import { useUrlParameter } from "@/lib/useUrlParameter";

type Filter = "open" | "daily" | "completed";

function TasksPageInner() {
  const [storedFilter, setStoredFilter] = useUrlParameter("status", "open");
  const filter: Filter = storedFilter === "completed" || storedFilter === "daily" ? storedFilter : "open";
  const today = toDayString(new Date());
  const [storedDay, setStoredDay] = useUrlParameter("day", "");
  const day = isDayString(storedDay) ? storedDay : today;
  const setDay = (next: string) => setStoredDay(next === today ? "" : next);
  const { openId, open, close } = useDetailPanel();
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const toast = useToast();

  // The daily view reads both lists (open for what's due, completed for what's
  // done that day) and shares the cache keys with the other two views.
  const wantsOpen = filter !== "completed";
  const wantsCompleted = filter !== "open";
  const openTasks = useSWR(wantsOpen ? "tasks:open" : null, () => listTasks({ status: "open", limit: 100 }));
  const completedTasks = useSWR(wantsCompleted ? "tasks:completed" : null, () =>
    listTasks({ status: "completed", limit: 100 }),
  );
  const isLoading = (wantsOpen && openTasks.isLoading) || (wantsCompleted && completedTasks.isLoading);
  const error = (wantsOpen && openTasks.error) || (wantsCompleted && completedTasks.error);
  const mutate = () => {
    if (wantsOpen) openTasks.mutate();
    if (wantsCompleted) completedTasks.mutate();
  };

  async function handleToggle(item: Item) {
    setTogglingId(item.id);
    try {
      const updated =
        item.status === "open"
          ? await completeTask(item.id, item.version)
          : await reopenTask(item.id, item.version);
      mutate();
      toast.push(item.status === "open" ? "Task completed." : "Task reopened.", "success", {
        label: "Undo",
        onClick: async () => {
          if (item.status === "open") {
            await reopenTask(updated.id, updated.version);
          } else {
            await completeTask(updated.id, updated.version);
          }
          mutate();
        },
      });
    } catch {
      toast.push("Could not update the task. Please retry.", "error");
    } finally {
      setTogglingId(null);
    }
  }

  const openItems = openTasks.data?.items ?? [];
  const completedItems = completedTasks.data?.items ?? [];
  const items = filter === "completed" ? completedItems : openItems;
  const groups = filter === "open" ? groupOpenTasks(items) : null;
  const dayGroups = filter === "daily" ? groupTasksForDay(openItems, completedItems, day, today) : null;
  const dayIsEmpty =
    dayGroups !== null && dayGroups.overdue.length + dayGroups.due.length + dayGroups.done.length === 0;

  const renderRows = (rows: Item[]) =>
    rows.map((item) => (
      <TaskRow
        key={item.id}
        item={item}
        onOpen={() => open(item.id)}
        onToggle={() => handleToggle(item)}
        toggling={togglingId === item.id}
      />
    ));

  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <PageHeader
        eyebrow="one list, not a calendar"
        title="Tasks"
        description="Every task, one list. No dates hidden, nothing scheduled you didn't ask for."
      />

      <Segmented
        value={filter}
        onChange={setStoredFilter}
        options={[
          { value: "open", label: "open" },
          { value: "daily", label: "daily" },
          { value: "completed", label: "completed" },
        ]}
      />

      {filter === "open" && <TaskQuickAdd onTaskCreated={() => mutate()} />}
      {isLoading && <LoadingState label="Loading tasks…" />}
      {error && <ErrorState message="Could not load tasks." onRetry={() => mutate()} />}

      {filter === "daily" && <DayNav day={day} today={today} onChange={setDay} />}

      {!isLoading && !error && filter !== "daily" && items.length === 0 && (
        <EmptyState
          title={filter === "open" ? "No open tasks." : "No completed tasks yet."}
          hint={filter === "open" ? "Add one above to get started." : undefined}
        />
      )}

      {!isLoading && !error && groups && (
        <>
          {groups.overdue.length > 0 && (
            <Section title="Overdue">
              {renderRows(groups.overdue)}
            </Section>
          )}
          {groups.upcoming.length > 0 && (
            <Section title="Upcoming">
              {renderRows(groups.upcoming)}
            </Section>
          )}
          {groups.undated.length > 0 && (
            <Section title="No date">
              {renderRows(groups.undated)}
            </Section>
          )}
        </>
      )}

      {!isLoading && !error && dayGroups && (
        <>
          {dayIsEmpty && (
            <EmptyState
              title={day === today ? "Nothing due today." : `Nothing due ${formatDayLabel(day, today).toLowerCase()}.`}
              hint="Tasks show up here on the day they're due."
            />
          )}
          {dayGroups.overdue.length > 0 && <Section title="Overdue">{renderRows(dayGroups.overdue)}</Section>}
          {dayGroups.due.length > 0 && <Section title="Due">{renderRows(dayGroups.due)}</Section>}
          {dayGroups.done.length > 0 && <Section title="Done">{renderRows(dayGroups.done)}</Section>}
        </>
      )}

      {!isLoading && !error && filter === "completed" && (
        <div>
          {renderRows(items)}
        </div>
      )}

      {openId && <ItemDetailPanel itemId={openId} onClose={close} />}
    </div>
  );
}

function DayNav({ day, today, onChange }: { day: string; today: string; onChange: (day: string) => void }) {
  const button = "rounded border border-hairline px-2.5 py-1 text-ink-muted hover:text-ink";
  return (
    <div className="mb-2 flex items-center gap-2 text-[12.5px]">
      <button className={button} onClick={() => onChange(shiftDay(day, -1))} aria-label="Previous day">
        ‹
      </button>
      <div className="min-w-[120px] text-center font-medium text-ink">{formatDayLabel(day, today)}</div>
      <button className={button} onClick={() => onChange(shiftDay(day, 1))} aria-label="Next day">
        ›
      </button>
      {day !== today && (
        <button className={button} onClick={() => onChange(today)}>
          today
        </button>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <div className="mb-1 mt-4 text-[11px] uppercase tracking-wide text-ink-faint">{title}</div>
      {children}
    </div>
  );
}

export default function TasksPage() {
  return (
    <Suspense>
      <TasksPageInner />
    </Suspense>
  );
}
