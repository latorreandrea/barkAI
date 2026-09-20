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

The clips are real footage: the filenames above are what the UI requests. The
whole set is served from the same container as the app (see the Deployment
section of the README), so mind the total payload — the current clips run from
~0.5 MB (`typing`, `idle`) to ~3.3 MB (`searching`, 17 s), and re-exporting them
at the content ratio below is what would roughly halve that.

## Frame geometry (why the player crops)

The current files are **1280x720**, but their real content is the **vertical
take in the middle**: the exported frame is pillarboxed in black, 401 px per
side. That black frame is what used to show as a black rectangle around the dog
on the white page.

The player therefore gives the video a box with the aspect ratio of the content
and lets `object-cover` do the cropping (`chat/templates/chat/index.html`):

* `aspect-[472/720]` + `object-cover object-center` → source columns **x=404..875**.
* 472 and not the 476 clean pixels, on purpose: the H.264 black→white transition
  leaves a grey column at each end of the content (x=401 ≈ `#ACACAC`, x=878 ≈
  `#ABABAB`, ~170/255), which showed as a hairline down both sides of the
  player. The window above keeps both edge columns at 253-255, i.e. white on a
  white page.
* `chat.css` adds a 1 px white fade on `.js-video-shell::before/::after` as a
  safety net, so a future clip with a darker edge column still cannot draw a line.

**Consequence for new exports:** export the vertical take at its **own** ratio
(472:720 ≈ 0.656, e.g. `scale=-2:960` → 636x960 from an 848x1280 master). Box
ratio and file ratio then match and `object-cover` has nothing left to cut — and
*never* force a square or 16:9 frame: that is exactly what produced the pillarbox
(and, with it, the grey hairline).

## Recording tips

* Keep them short (1-3 s) and loop-friendly: they play muted and on a loop.
* Keep the subject a few px away from the left/right edges: `object-cover` crops
  a couple of px per side when the file ratio is not exactly 472:720.
* Keep the background the same white as the page (`#ffffff`): the clips are
  drawn straight on the white stage, so an off-white background shows as a faint
  rectangle around the dog.
* Encode with **H.264 + `yuv420p`** for maximum browser compatibility (Safari
  included), and start the file with the index so it plays immediately:

  ```bash
  # From the vertical master: keep its ratio, and drop the audio track (the
  # player is muted, so it would only be dead weight).
  ffmpeg -i source.mov -an \
    -vf "scale=-2:960" \
    -c:v libx264 -profile:v high -crf 30 -preset slow -r 24 \
    -pix_fmt yuv420p -movflags +faststart idle.mp4
  ```

  `-crf` is the main size/quality dial (28 = safer, 32 = lighter); `-r 24` drops
  the frame rate without a visible loss on a short loop.

* Replace the files **keeping the exact filenames**: `chat.js` builds the URL as
  `/static/mascot/<state>.mp4`.

> Cache note: WhiteNoise serves these files with a one-year cache header
> (`WHITENOISE_MAX_AGE`) and the storage backend is the non-Manifest one, so their
> URL never changes on its own. `chat.js` therefore appends `?v=<ASSET_VERSION>`,
> the same query string the templates put on `barkai.css`/`chat.js` — and that
> token is derived from the assets' own timestamps, so a clip replaced in place
> gets a fresh URL by itself. Export `ASSET_VERSION` only to pin it by hand.

