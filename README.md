# DCP Clipper

PC software that turns a Double Coverage clip slate (`.docx`) into finished split-screen Shorts.
It runs on your own Windows PC and opens in your browser. Nothing is uploaded or hosted.

For each clip in the slate it:

1. Downloads that stretch of the episode (yt-dlp) and transcribes it (faster-whisper).
2. Finds the exact clip from the slate's timestamps, "Start ..." phrase and payoff quote, and cuts in true silence.
3. Removes pauses and builds one-word captions (name fixes and bleeps included).
4. Searches YouTube for each B-roll line and proposes clean shots.
5. Times every B-roll shot to the moment its subject is spoken ("belt" shot on the word "belt").
6. Renders the split-screen Short: face-tracked podcast cam on top, B-roll below, captions on the seam,
   logo, grade, hook box, music under the voice at -14 LUFS.
7. Makes a contact sheet for checking, then writes the pack folder and the `CLIP_TRACKER.txt` line.

## Install (once)

You need Python 3.11+, FFmpeg on PATH, and the **Lato Black** font installed (the caption font).

1. Double-click `setup.bat`.
2. Copy `bgm_under.mp3` into the `assets` folder (setup does this itself if it finds your
   `D:\YT SHORTS\brolls\_pipeline` copy). The music file is deliberately not stored in the repo.
3. Open `config.json` and check `output_dir` (where pack folders go).
4. Optional: double-click `setup_ai.bat` to add the automatic B-roll picker (uses the RTX 3050).

## Use

1. Double-click `run.bat`. The app opens at http://127.0.0.1:8765.
2. Press **Load slate (.docx)** and pick the slate.
3. On the left, check the episode ID and add caption name fixes, one per line: `sir gone = Gane`.
4. Click a clip and press **Build this clip** (or **Build all clips**).
5. Review the clip: click words to add or remove them, fix captions, swap B-roll shots, then **4 Render** again.
6. Check the contact sheet, then press **5 Save pack folder**.

## B-roll picking

- **Without `setup_ai.bat`:** the app downloads search results and offers three evenly spaced
  moments per video, marked "not scored". You choose, or add a shot by link and time.
- **With it:** a local image-matching model picks the moments that best match each B-roll line,
  an on-screen-text check and a rough woman-in-frame check add warnings, and a face detector sets the crop.
  These are warnings, not guarantees. Always check the contact sheet.
- **Exact sources in the slate:** a B-roll item written as `Floyd belts Ck_l3DOg9iQ 0:56-1:05`
  uses that video and time with no searching.

## Slate format

The format of `Hokit_14_Clip_Slate.docx`: a title, an intro paragraph containing `episode <YouTube ID>`,
then per clip a numbered heading followed by `HOOK to PAYOFF:`, `Source:`, `Hook box:`, `B-roll ...:` lines.
Free-text notes in the Source line (for example `skip the "better to die" lines`) are shown in yellow
for you to apply by clicking the words; they are not applied automatically.

## Not included

Choosing which clips to make, Triple Hook scoring, and writing titles, descriptions and X posts.

## Tests

    python -m unittest tests.test_core
