Failure state when the local processor (Whisper/Ollama service) isn't reachable, paired with a matching microphone-permission-missing variant (see the state specification card).

- Uses the warning triangle glyph plus red-toned text, never color fill alone, so it reads correctly for colorblind users and in reduced-contrast modes.
- Copy always names the fix: start the service, grant permission, or fall back to typing — never a dead end.
- The border returns to the neutral 1px hairline (not the 1.5px "active" outline used for recording/processing) so a failed state doesn't look like it's still working.
