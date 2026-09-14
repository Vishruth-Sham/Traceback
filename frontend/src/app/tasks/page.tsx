"use client";

import { Suspense, useState } from "react";
import useSWR from "swr";
import { completeTask, listTasks, reopenTask } from "@/lib/traceback";
import { groupOpenTasks } from "@/lib/taskGrouping";
import { Item } from "@/lib/types";
import { TaskRow } from "@/components/TaskRow";
import { TaskQuickAdd } from "@/components/TaskQuickAdd";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { ItemDetailPanel } from "@/components/ItemDetailPanel";
import { useDetailPanel } from "@/lib/useDetailPanel";
import { useToast } from "@/components/Toast";
import { PageHeader } from "@/components/PageHeader";
import { Segmented } from "@/components/Segmented";

type Filter = "open" | "completed";

function TasksPageInner() {
  const [filter, setFilter] = useState<Filter>("open");
  const { openId, open, close } = useDetailPanel();
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const toast = useToast();

  const { data, error, isLoading, mutate } = useSWR(
    `tasks:${filter}`,
    () => listTasks({ status: filter, limit: 100 }),
  );

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

  const items = data?.items ?? [];
  const groups = filter === "open" ? groupOpenTasks(items) : null;

  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <PageHeader
        eyebrow="one list, not a calendar"
        title="Tasks"
        description="Every task, one list. No dates hidden, nothing scheduled you didn't ask for."
      />

      <Segmented
        value={filter}
        onChange={setFilter}
        options={[
          { value: "open", label: "open" },
          { value: "completed", label: "completed" },
        ]}
      />

      {filter === "open" && <TaskQuickAdd onTaskCreated={() => mutate()} />}

      {isLoading && <LoadingState label="Loading tasks…" />}
      {error && <ErrorState message="Could not load tasks." onRetry={() => mutate()} />}

      {!isLoading && !error && items.length === 0 && (
        <EmptyState
          title={filter === "open" ? "No open tasks." : "No completed tasks yet."}
          hint={filter === "open" ? "Add one above to get started." : undefined}
        />
      )}

      {!isLoading && !error && groups && (
        <>
          {groups.overdue.length > 0 && (
            <Section title="Overdue">
              {groups.overdue.map((item) => (
                <TaskRow
                  key={item.id}
                  item={item}
                  onOpen={() => open(item.id)}
                  onToggle={() => handleToggle(item)}
                  toggling={togglingId === item.id}
                />
              ))}
            </Section>
          )}
          {groups.upcoming.length > 0 && (
            <Section title="Upcoming">
              {groups.upcoming.map((item) => (
                <TaskRow
                  key={item.id}
                  item={item}
                  onOpen={() => open(item.id)}
                  onToggle={() => handleToggle(item)}
                  toggling={togglingId === item.id}
                />
              ))}
            </Section>
          )}
          {groups.undated.length > 0 && (
            <Section title="No date">
              {groups.undated.map((item) => (
                <TaskRow
                  key={item.id}
                  item={item}
                  onOpen={() => open(item.id)}
                  onToggle={() => handleToggle(item)}
                  toggling={togglingId === item.id}
                />
              ))}
            </Section>
          )}
        </>
      )}

      {!isLoading && !error && !groups && (
        <div>
          {items.map((item) => (
            <TaskRow
              key={item.id}
              item={item}
              onOpen={() => open(item.id)}
              onToggle={() => handleToggle(item)}
              toggling={togglingId === item.id}
            />
          ))}
        </div>
      )}

      {openId && <ItemDetailPanel itemId={openId} onClose={close} />}
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
