Compact state specification showing all nine core states of the one voice-command panel side by side, so it reads as one component transitioning, not nine different UIs.

- Every state uses the same 460px dock, the same 1.5px vs 1px border rule (1.5px = actively listening/thinking; 1px = at rest, resolved, or failed), and the same type scale.
- Only content, border emphasis and the recording dot's pulse change between states; layout, radius and padding never do.
- Future write-command states (create/edit/confirm/undo) extend this same panel rather than introducing a new surface — see the system README's "Future-proofing" section.
