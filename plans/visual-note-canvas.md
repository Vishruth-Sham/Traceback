# Visual note canvas

Status: idea for later. No implementation planned yet.

Traceback notes could offer an Excalidraw-like canvas for thinking visually: text, shapes,
arrows, freehand drawing, and images placed anywhere. The canvas would be another way to
view or edit a note, not a replacement for every text note.

Claude should be able to work on the canvas through structured MCP actions: read the scene,
add or update elements, connect them, and place uploaded images. Each action should use the
note's current version so Claude cannot silently overwrite a person's edits. The scene
format should remain editable and exportable, with a useful text summary for search and
accessibility.

When revisiting this, first prototype one note with a canvas and test whether moving between
Claude and the visual editor feels natural. Decide then whether to use Excalidraw's scene
format or a smaller Traceback format.
