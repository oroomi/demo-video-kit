# Hackathon video: shot list (2 minutes)

Lesson that made this kit (JunctionX Turku, lost): the demo video showed screen footage with a separate narrator. The judges
never saw the assistant actually talking. **The video must show the live assistant speaking in the first 20 seconds**, in the
same take as the screen, with its real voice, our spoken question, and captions. Everything below serves that.

Record it with `./demo-video` (see README.md). One live take = one capture of picture + sound; shots are cut from it, never
re-voiced.

## Structure and timing

| Time | Beat | What is on screen / in the ears | Rule |
|---|---|---|---|
| 0:00-0:05 | **Hook** | The hero screen with the assistant already speaking (cut from the live take, starting on its first word). One line on top, 6 words or fewer. | Voice from the first 0.5 s. No logo, no name, no "Hello". The moment first. |
| 0:05-0:08 | Title card | Product name + one-line promise + team. | 3 s maximum. Not before the hook. |
| 0:08-0:35 | **Live voice moment** | Mic click, our spoken question (cyan caption), the thinking state, the real answer in its real voice (white captions). | Question 5 words or fewer. Whole moment 27 s or less. Thinking gap: real speed up to 3 s; longer is sped up and labelled with the real wait. Nothing edited out of the answer. |
| 0:35-1:20 | **Proof 1, 2, 3** (about 15 s each) | One claim each, with its source on screen: (1) the answer's record opened, (2) a number traced to its row, (3) the case the system refuses or gets wrong, shown plainly. | One claim per shot. Caption states the claim in 10 words or fewer. A visible change every 5 s (scroll, click, expand). |
| 1:20-1:45 | **Transfer / scale line** | The one thing that lets this go to another domain (config swap, second dataset, second city) shown working, not described. | One sentence, said or captioned. Show the second case on screen. |
| 1:45-2:00 | **End card** | URL (large), QR code, team, the ask. | 4 s minimum so the QR can be scanned. The URL must be the one that is live today. |

The kit's `assemble.py` builds: hook, title, live moment, any number of proof shots (`--proof "P1:caption,P2:caption,P3:caption" --proof-s 12`),
and the end card (transfer line + URL + QR from the profile). The 40-second proof clip is the same structure with one proof shot.

## Timing rules (hard)

1. First voice on the tape at or before 0:01; the full live moment starts before 0:20. `proof.json` reports `first_voice_s`, `voice_in_first_5s`, `voice_in_first_20s`; all must be true.
2. No silence longer than 1.5 s except the thinking gap (sped up and labelled if over 3 s).
3. No screen without a caption while someone is speaking. Captions come from the real transcript (known question + the assistant's streamed text), timed to the recorded audio.
4. The assistant's answer is at most about 300 characters (about 20 s of voice). If the model writes more, change the question or the system prompt, not the edit.
5. Total 2:00 or less; file 50 MB or less (assemble re-encodes to fit); loudness -16 LUFS; 1920x1080, 30 fps, H.264 + AAC. A 9:16 cut (`*_vertical.mp4`) for social, same audio.
6. Names never first: the moment first, then the name.

## Shot table (fill in before recording)

| # | Beat | Shot script / name | Caption (10 words max) | Seconds | Source visible? |
|---|---|---|---|---|---|
| 0 | Hook | cut from live take | (hook line) | 4 | n/a |
| 1 | Live voice | `./demo-video live --question "..."` | the question, then the reply | 27 | spoken answer names sources |
| 2 | Proof 1 | P1 | | 12-15 | yes |
| 3 | Proof 2 | P2 | | 12-15 | yes |
| 4 | Proof 3 | P3 | | 12-15 | yes (the refusal / the miss) |
| 5 | Transfer | P4 or end card line | | 10-20 | the second case |
| 6 | End | end card | URL + QR | 4 | n/a |

## Checklist

Before recording
- [ ] `./demo-video doctor` prints ALL PASS (sound on tape, 1920x1080, capture keeps up, slate skew stable).
- [ ] The live URL smoke-tested in the last 3 hours; `/api/.../status` says the assistant is available and TTS is on.
- [ ] Question worded for a short, sourced answer (5 words, one entity). Rehearse with `--mock` first (no live model or TTS cost).
- [ ] Live-voice budget set (at most 3 takes; each answer is about 300 characters of TTS).
- [ ] The machine is quiet (`uptime` load under 2). Other browsers and builds stopped (not killed by pattern: by PID).
- [ ] Profile (`profiles/<site>.json`) has the right URL, headline, tagline, transfer line, end line, QR target.

After recording
- [ ] `proof.json`: `voice_in_first_5s` true; `final_vs_edit_list` deltas under 50 ms; `raw_capture.drift_s` under 0.1; `whole_file_volume.mean_db` not -inf.
- [ ] `./demo-video frames out/<site>/<name>.mp4 --every 5`: read every frame. No blank, cut-off or mid-load frame; captions never cover the thing being said; cursor ring visible only while clicking.
- [ ] Listen once with eyes closed: the question is audible and clear, the reply is the real voice, no clipping, no echo.
- [ ] Captions spelled right (names, numbers). Only companies on screen, no private individuals, no keys or personal data in any frame.
- [ ] Vertical cut checked on a phone-size preview. QR on the end card scans. URL on the end card is the live one.
- [ ] File under 50 MB; the same video uploaded where the rules say, and a copy saved on the phone as the expo fallback.
