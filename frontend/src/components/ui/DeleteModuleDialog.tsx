"use client";

// Deleting a module, after a dialog that says what happens to it: it stops for good, its data is copied aside first
// and its code stays in git under a tag of its own. Opened from the module's page and from its row in the rail;
// nothing is deleted until Delete is pressed. Cancel has the focus, Escape closes it, and it stays open while the
// deletion runs, with the builder's reason if it refuses (being built, hand-written). Whoever opens it keeps it
// mounted until it closes: the module leaves the list before the builder answers (the supervisor drops its row first).

import { AlertDialog } from "@base-ui/react/alert-dialog";
import { useRemoveModule } from "@/lib/queries";
import { Button } from "./Button";
import { ErrorLine, Spinner } from "./Primitives";

export interface DeleteTarget {
  name: string;
  version: string | null; // null: its row is gone already (a deletion that stopped halfway)
  grown: boolean; // its code is in grown/'s git; a row whose folder is gone has none left to keep
}

export function DeleteModuleDialog({
  target,
  onClose,
  onDeleted,
}: {
  target: DeleteTarget | null; // open while there is one
  onClose: () => void;
  onDeleted?: (name: string) => void;
}) {
  const remove = useRemoveModule();
  const close = () => {
    if (remove.isPending) return; // it runs on the builder whatever this says: wait for its answer
    remove.reset();
    onClose();
  };
  const run = (name: string) =>
    remove.mutate(name, {
      onSuccess: () => {
        remove.reset();
        onClose();
        onDeleted?.(name);
      },
    });

  return (
    <AlertDialog.Root open={target !== null} onOpenChange={(open) => !open && close()}>
      <AlertDialog.Portal>
        <AlertDialog.Backdrop className="fixed inset-0 z-40 bg-night/30" />
        <AlertDialog.Popup className="fixed top-1/2 left-1/2 z-50 flex w-[min(420px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-card border border-line-strong bg-surface p-5 shadow-raised">
          {target && (
            <>
              <AlertDialog.Title className="m-0 text-[15px] font-medium">
                Delete <span className="font-mono">{target.name}</span>?
              </AlertDialog.Title>
              <AlertDialog.Description render={<div />} className="flex flex-col gap-2 text-[13px] leading-normal text-ink2">
                <p className="m-0">It stops for good and leaves your modules, and its name is free for a new one.</p>
                <p className="m-0">{target.grown ? "To bring it back later:" : "To bring its data back later:"}</p>
                <ul className="m-0 flex list-disc flex-col gap-1 pl-5">
                  <li>its data is copied aside to a Docker volume first</li>
                  {target.grown && (
                    <li>
                      its code stays in git, under the tag{" "}
                      <span className="font-mono text-[12.5px]">{`${target.name}-${target.version ? `v${target.version}-` : ""}removed-…`}</span>
                    </li>
                  )}
                </ul>
              </AlertDialog.Description>
              {remove.error && <ErrorLine>{remove.error.message}</ErrorLine>}
              <div className="mt-1 flex justify-end gap-2">
                <Button size="sm" onClick={close} disabled={remove.isPending}>
                  Cancel
                </Button>
                <Button size="sm" variant="danger" onClick={() => run(target.name)} disabled={remove.isPending}>
                  {remove.isPending && <Spinner className="border-white/40 border-t-white" />}
                  {remove.isPending ? "Deleting…" : `Delete ${target.name}`}
                </Button>
              </div>
            </>
          )}
        </AlertDialog.Popup>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
