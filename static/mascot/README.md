# static/mascot — BarklAI reaction videos

This folder holds the MP4 reaction clips played by the Web UI. The filenames
are contractual: `chat/templates/chat/index.html` switches the `<video>` src
to `/static/mascot/<state>.mp4` based on the BarklAI state returned by the API.

| File                | When it plays                                      |
|---------------------|----------------------------------------------------|
| `idle.mp4`          | Default state while waiting for the recruiter      |
| `sniffing.mp4`      | First-visit onboarding: BarklAI approaches the visitor |
| `searching.mp4`     | While the API/agent is working on a reply          |
| `typing.mp4`        | While the visitor is writing in the composer       |
| `speaking.mp4`      | BarklAI delivering his answer                      |
| `celebrating.mp4`   | An interview has been requested 🎉                 |

The clips are real footage: the filenames above are what the UI requests. The
whole set is served from the same container as the app (see the Deployment
section of the README), so mind the total payload: the six clips weigh **3.9 MB**
together (~0.27 MB for `typing`, ~1.77 MB for the 17 s `searching`), after being
re-encoded at the content ratio described below — that step cut them from 7.5 MB.

## The neutral pose is part of the contract

Every clip **starts and ends on the same neutral pose** (and holds it for a moment at both ends). The
player hands the stage over with a hard cut — a cross-fade would show the dog twice, since these are
hand-drawn poses on white — and it lands that cut on the outgoing clip's loop seam whenever the seam is
within a few hundred milliseconds. The shared pose is what makes the cut invisible: a clip that starts
mid-action, or ends somewhere else, would make every hand-over snap.

The player itself is in `static/js/chat.js` (section 3a): **two stacked `<video>` elements**, because
changing the `src` of a single one tears its decoder down and the stage draws nothing until the new file's
first keyframe arrives. The hidden element pre-rolls the next clip — paused, on its first frame — while
the one on screen keeps playing, and replaces it only once it can draw, so a clip change costs a frame
instead of a gap. `typing` is switched from the composer's `input` event (see 3b in the same file),
`SWAP_BLINK_MS` can cover a cut that missed the seam with a white blink, and the two clips the visitor is
most likely to need next are fetched while the page is quiet. A clip that fails to load does not blank the
stage: the hand-over is cancelled and the mascot keeps the previous reaction (the emoji fallback shows
when there is nothing else to show).

## Frame geometry (the 472:720 box)

The clips are the **vertical take**: **472x720** (DAR 59:90), the shape the player
gives the `<video>` with `aspect-[472/720]` in `chat/templates/chat/index.html`.
Box ratio and file ratio therefore match, and the `object-cover object-center`
next to it has nothing left to cut.

That ratio is fixed by the footage and measured, not guessed, because the files
once arrived as 1280x720 exports that **pillarboxed** this take in black (401 px
per side), which showed as a black rectangle around the dog on the white page.
Cropping the bars back off had to stop at x=404..875 — not at the 476 columns of
clean content — because the H.264 black→white transition leaves a grey column at
each end (x=401 ≈ `#ACACAC`, x=878 ≈ `#ABABAB`, ~170/255) that showed as a
hairline down both sides of the player. The clips were then re-encoded to
472x720, so those grey columns are gone from the files too; the box keeps the
ratio anyway, and `chat.css` keeps a 1 px white fade on
`.js-video-shell::before/::after` as a safety net, so a future clip with a darker
edge column still cannot draw a line.

## Recording tips

* Keep them short (1-3 s) and loop-friendly: they play muted and on a loop.
* Keep the same **472:720** ratio, and the subject a few px away from the
  left/right edges: the player crops a couple of px per side when the file ratio
  is not exactly that. *Never* force a square or 16:9 frame — that is what
  produced the pillarbox, and with it the grey hairline.
* Keep the background the same white as the page (`#ffffff`): the clips are drawn
  straight on the white stage, so an off-white background shows as a faint
  rectangle around the dog. The current files sit at 253-255 on their edge columns.
* Encode with **H.264 + `yuv420p`**, 24 fps, for maximum browser compatibility
  (Safari included), and start the file with the index so it plays immediately:

  ```bash
  # From a vertical master (e.g. 848x1280): scale to 720 px tall, then crop to the
  # exact 472x720 the player expects (the 2-3 px it drops are background), and
  # drop the silent audio track the old exports carried.
  ffmpeg -i source.mov -an \
    -vf "scale=-2:720,crop=472:720:(iw-472)/2:0" \
    -c:v libx264 -profile:v high -preset slow -tune animation -crf 28 \
    -pix_fmt yuv420p -movflags +faststart idle.mp4

  # Straight from one of the old 1280x720 pillarboxed exports, the crop offsets
  # are the measured ones above and the encoder flags are the same:
  ffmpeg -i old_1280x720.mp4 -an -vf "crop=472:720:404:0" \
    -c:v libx264 -profile:v high -preset slow -tune animation -crf 28 \
    -pix_fmt yuv420p -movflags +faststart idle.mp4
  ```

  `-crf` is the size/quality dial: 28 is visually identical to the source at this
  size, 30 is ~20% lighter but the fur looks softer already under a 3x zoom.
  `-tune animation` pays off on this flat cartoon artwork, and `-an` removes the
  2 kb/s silent AAC track (the player is muted).

* Replace the files **keeping the exact filenames**: `chat.js` builds the URL as
  `/static/mascot/<state>.mp4`.

> Cache note: WhiteNoise serves these files with a one-year cache header
> (`WHITENOISE_MAX_AGE`) and the storage backend is the non-Manifest one, so their
> URL never changes on its own. `chat.js` therefore appends `?v=<ASSET_VERSION>`,
> the same query string the templates put on `barkai.css`/`chat.js` — and that
> token is derived from the assets' own timestamps, so a clip replaced in place
> gets a fresh URL by itself. Export `ASSET_VERSION` only to pin it by hand.

