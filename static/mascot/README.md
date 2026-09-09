# static/mascot — BarklAI reaction videos

This folder holds the MP4 reaction clips played by the Web UI. The filenames
are contractual: `chat/templates/chat/index.html` switches the `<video>` src
to `/static/mascot/<state>.mp4` based on the BarklAI state returned by the API.

| File                | When it plays                                      |
|---------------------|----------------------------------------------------|
| `idle.mp4`          | Default state while waiting for the recruiter      |
| `sniffing.mp4`      | First-visit onboarding: BarklAI approaches the visitor |
| `searching.mp4`     | While the API/agent is working on a reply          |
| `typing.mp4`        | Alternative "working" clip (ready to use)          |
| `speaking.mp4`      | BarklAI delivering his answer                      |
| `celebrating.mp4`   | An interview has been requested 🎉                 |

The `.mp4` files currently here are small generated placeholders (solid color
clips) so the UI can be demoed before the real BarklAI footage is available.
Replace them with real clips, keeping the exact filenames above.

Tips for your own clips:

* Keep them short (1–3 s) and loop-friendly.
* Encode with **H.264 + yuv420p** for maximum browser compatibility, e.g.:
  `ffmpeg -i source.mov -c:v libx264 -pix_fmt yuv420p -movflags +faststart speaking.mp4`
* Match the square framing: the player crops with `object-cover`, so 1:1
  footage (e.g. 640×640) works best for both the desktop and circular mobile
  layouts.
