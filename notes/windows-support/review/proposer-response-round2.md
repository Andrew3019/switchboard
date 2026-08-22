# Proposer response — adversarial review round 2 (is "herdr under WSL2 is clean" established?)

Reviewer: `reviewer-herdr-wsl2`. Proposer: `proposer-wsl2-plan`. 2026-08-22.
Outcome: **REVISED on all four points — nothing rebutted.** Every citation re-verified against the
herdr clone at `/Users/andrew/Code/herdr` HEAD `69a07fd` and this worktree before folding.

## Point by point

| # | Review's point | Disposition | What changed |
|---|---|---|---|
| 1 | "herdr treats WSL as plain Linux" is false — 3 runtime divergences | **REVISED** | §1's `herdr under WSL2 is clean` paragraph rewritten. It now (a) narrows the strong claim to the **server layer switchboard actually drives**, with the reviewer's better citations — `pty/backend.rs:1-5`, `backend/unix.rs:12-24`, and herdr's own pinning test `api/server.rs:929` `socket_path_defaults_to_config_dir_even_when_xdg_runtime_dir_is_set`, plus `setsid` at `platform/mod.rs:73-85`; and (b) states all three WSL divergences explicitly — drawn cursor (`platform/linux.rs:38-50`) **with the CJK IME anchor consequence and the `[ui] host_cursor = "native"` fix**, OSC 52 clipboard route (`selection.rs:277-320`), and the zero-`TIOCGWINSZ`-pixels cell-size query. Framed as evidence WSL is a cared-for herdr target, with "cared-for is not identical" said out loud. |
| 2 | The `sb block` doorbell can go silent on stock WSL2 | **REVISED** — the important one | New **§2.3**, with a route-by-route table. Verified myself: `terminal_notify.rs:11-31` really does list only Ghostty/iTerm2/Kitty/WezTerm (no Windows Terminal); `platform/linux.rs:534-556` needs `notify-send` **and** returns early with no `DISPLAY`/`WAYLAND_DISPLAY`, against macOS's unconditional `osascript` at `macos.rs:583-597`; `api.rs:1192-1236` maps `Ok(false) \| Err(_)` to `NoForegroundClient` and then `encode_success`, and `herdr.py:1131-1134` discards the response body entirely, so `broker.py:6489-6493`'s `HerdrError`-only catch can never see it. Mitigation added to §3 as a new step 7 (`[toast] delivery = "herdr"`, or `libnotify-bin` + `pulseaudio-utils`). The reviewer's own caveat is carried: herdr's default delivery is `Off` (`config/model.rs:59-65`), so this is a regression relative to a *configured* user — which is the working macOS setup and the one the blocking protocol assumes. |
| 3 | §6 never asks whether the herdr server survives WSL2's VM lifecycle | **REVISED** | Added to §6 **at the top of the list**, as the review asked, and stated as the biggest WSL2-vs-Linux unknown: `vmIdleTimeout`, `wsl --shutdown`, host sleep suspending the VM, and the resume clock jump against switchboard's wall-clock deadlines (confirmed: `herdr.py:1096-1112` uses `time.time()`, not `monotonic`). Named as directly load-bearing for overnight fleets and blocked agents, and as needing a real box rather than more source reading. |
| 4 | Clipboard bullet should narrow to reads | **REVISED** | §6's bullet now says clipboard **reads**, and records why writes are settled by source (herdr deliberately prefers OSC 52 under WSL so Windows Terminal clipboard history is populated) while reads offer only `wl-paste`/`xclip`/`xsel` with no OSC 52 fallback. Notes neither direction is a switchboard dependency. |
| 5 (minor, from the detail note) | Foreground-process detection under WSL2 | **REVISED (folded)** | Added to §6 as a low-risk unknown with the `HERDR_PROCESS_DETECTION=child-groups` escape hatch. Kept short — WSL2 has a real `/proc` and switchboard drives agent state explicitly. |

## Note on what round 2 changes about the plan's shape

Round 1 cost the plan its "zero code changes" line. Round 2 costs it something different: the
setup guide is no longer just "install these packages and don't use `/mnt/c`" — it now has a
**configuration** step (§3.7) without which switchboard's blocking protocol degrades silently.
That is worth flagging to whoever writes the user-facing guide: §2.3 is the one WSL2 finding so far
where the failure is invisible to switchboard's own logs, so it cannot be caught after the fact.

The recommendation is unchanged and unthreatened; both rounds have attacked reasons and
completeness, and both times the reasons were weaker than written while the conclusion held.
