"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { getItem, listItems } from "@/lib/traceback";
import { ItemRow } from "@/components/ItemRow";
import { FolderTree } from "@/components/FolderTree";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { ItemDetailPanel } from "@/components/ItemDetailPanel";
import { useDetailPanel } from "@/lib/useDetailPanel";

function ProjectDetailInner() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const { openId, open, close } = useDetailPanel();

  const { data: project, error: projectError, isLoading: projectLoading, mutate: mutateProject } = useSWR(
    `project:${projectId}`,
    () => getItem(projectId),
  );

  const { data: tasks, isLoading: tasksLoading, mutate: mutateTasks } = useSWR(
    `project-tasks:${projectId}`,
    () => listItems({ project_id: projectId, item_type: "task", limit: 100 }),
  );

  if (projectLoading) return <LoadingState label="Loading project…" />;
  if (projectError || !project) return <ErrorState message="Could not load this project." onRetry={() => mutateProject()} />;

  return (
    <div className="mx-auto max-w-[760px] px-10 py-10 pb-32">
      <Link href="/projects" className="mb-4 flex items-center gap-1.5 text-[12px] text-ink-faint hover:text-ink">
        <ArrowLeft size={13} /> all projects
      </Link>
      <div className="mb-1 text-[12px] italic text-ink-muted">project</div>
      <h1 className="mb-1 font-serif text-[24px] font-semibold text-ink">{project.title}</h1>
      {project.archived_at && (
        <p className="mb-3 text-[12.5px] text-accent-navy">Archived. Linked tasks and notes remain available below.</p>
      )}
      {project.content_md && <p className="mb-6 whitespace-pre-wrap text-[13.5px] text-ink-muted">{project.content_md}</p>}

      {project.category_id && <FolderTree categoryId={project.category_id} parentId={project.id} />}

      <div className="mt-6 border-t border-hairline pt-4">
        <div className="mb-1 text-[11px] uppercase tracking-wide text-ink-faint">tasks linked to this project</div>
        <p className="mb-2 text-[11.5px] text-ink-faint">
          To link a task here, open it from Tasks and link it from there.
        </p>
        {tasksLoading && <LoadingState />}
        {tasks && tasks.items.length === 0 && <EmptyState title="No tasks linked yet." />}
        {tasks?.items.map((item) => (
          <ItemRow key={item.id} item={item} onOpenTask={open} />
        ))}
      </div>

      {openId && (
        <ItemDetailPanel
          itemId={openId}
          onClose={() => {
            close();
            mutateProject();
            mutateTasks();
          }}
        />
      )}
    </div>
  );
}

export default function ProjectDetailPage() {
  return (
    <Suspense>
      <ProjectDetailInner />
    </Suspense>
  );
}
