Clarification state for same-named items, the strict version of the multiple-matches panel: Traceback never guesses which one the user meant.

- Triggered only when names collide (not merely when there are several results) — copy names the collision explicitly: "I found two projects named Renovation."
- Distinguishing information is mandatory, not optional: full breadcrumb, and item type or last-modified date when breadcrumbs alone don't disambiguate.
- No default selection, no auto-timeout that picks one; the session stays open until the user chooses or cancels.
