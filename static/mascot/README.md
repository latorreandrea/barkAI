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

The clips are real footage: the filenames above are what the UI requests, and
each one should stay **under ~600 KB** so the page stays light (the whole set is
served from the same container as the app, see the Deployment section of the
README).

Recording tips for new clips:

* Keep them short (1-3 s) and loop-friendly: they play muted and on a loop.
* Keep the **source aspect ratio**. The player uses `object-contain`, so it scales
  the clip to fit and never crops it. Forcing a square frame would only make the
  dog smaller, with empty bands around it. (An earlier version of this file
  claimed the player cropped with `object-cover`: that was wrong.)
* Encode with **H.264 + `yuv420p`** for maximum browser compatibility (Safari
  included), and start the file with the index so it plays immediately:

  ```bash
  ffmpeg -i source.mov -an \
    -vf "scale=960:960:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2" \
    -c:v libx264 -profile:v high -crf 30 -preset slow -r 24 \
    -pix_fmt yuv420p -movflags +faststart speaking.mp4
  ```

  `-crf` is the main size/quality dial (28 = safer, 32 = lighter); `-r 24` drops
  the frame rate without a visible loss on a short loop.

* Replace the files **keeping the exact filenames**: `chat.js` builds the URL as
  `/static/mascot/<state>.mp4`.

> Cache note: WhiteNoise serves these files with a one-year cache header
> (`WHITENOISE_MAX_AGE`). Replacing a clip *after* launch therefore needs a cache
> bump — a versioned `ASSET_VERSION` is on the project roadmap for that.

