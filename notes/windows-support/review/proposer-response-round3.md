# Proposer response — adversarial review round 3 (does §3 serve a non-technical user?)

Reviewer: `reviewer-setup-honesty`. Proposer: `proposer-wsl2-plan`. 2026-08-22.
Outcome: **REVISED on all eight points — nothing rebutted.** This was the round that cost the plan
the most, and rightly: §1/§2's technical work survived untouched while §3 turned out to be an
outline wearing a guide's title.

## The one I got wrong myself

**F1 is a defect I introduced in round 2.** §2.3 and §3 both told the user to write
`[toast] delivery = "herdr"`. Verified against the herdr clone: the real section is **`[ui.toast]`**
(`src/config/model.rs:863-864`, pinned by the round-trip test at `model.rs:1638-1652`), and `Config`
has **zero** `#[serde(deny_unknown_fields)]`, so a stray top-level `[toast]` is silently ignored —
`herdr config check` passes, delivery stays `Off`, and `sb block` is permanently silent. I had
written the instruction that reintroduces the exact failure §2.3 exists to prevent. Fixed in both
places, with the reason spelled out so it does not get "corrected" back.

The reviewer's better suggestion is also folded in: for this audience the instruction is **herdr
settings → Notifications → `herdr`** (`src/app/input/settings.rs:19,76-91`), not a TOML stanza.
Confirmed there is no `herdr config set` verb (`src/cli/spec.rs:138-142` — only `check` and
`reset-keys`), so the plan does not imply one.

## Point by point

| # | Review's point | Disposition | What changed |
|---|---|---|---|
| F1 | Wrong config section, silently ignored | **REVISED** | See above. §2.3 now gives the settings-UI route first, the `[ui.toast]` TOML second with the file path `~/.config/herdr/config.toml`, and states why the wrong section is worse than a typo. |
| F2 | "install switchboard exactly as on macOS/Linux" — no such procedure | **REVISED** | Confirmed: `README.md:109-111` says there is **no packaging file and nothing to install switchboard as**, and the one-symlink mechanism is documented only in a code comment (`broker.py:3310`). §3 step 10 now gives the literal `mkdir -p ~/.local/bin && ln -s …` plus the `command -v sb` check, and says outright that nothing does this for you. `pip install -r requirements.txt` is now an explicit **skip** (optional `rich`; PEP 668 + missing `python3-pip` on 24.04). §6 records that whether switchboard should have a real install step is a decision this plan surfaces and does not make. |
| F3 | Never names `sb start`, the repo it runs in, git identity, or Claude Code auth | **REVISED** | New §3 step 13 gives `cd ~/my-project && sb start` and says in bold that this is **not** the switchboard checkout — with the store-under-`.git` and worktree reasons, and the `origin/main`→`main` base-branch fallback (`defaults/settings.toml:139`, `broker.py:1815-1817`). Git identity is now step 6 with the reason (`sb done` commits; a fresh Ubuntu refuses). Claude Code's browser login with no browser handler is step 8. |
| F4 | `apt install` before `apt update` fails; herdr install hand-waved | **REVISED** | Step 4 is now `sudo apt update` **then** `apt install`, with `curl` added (herdr's installer hard-requires it). Step 7 prints the actual `curl -fsSL https://herdr.dev/install.sh \| sh`, and carries the `~/.local/bin`-not-on-PATH-until-a-new-login trap with the "this reads like a failed install and isn't" framing. ARM support (`linux/aarch64`) stated plainly as the reviewer asked. |
| F5 | Python 3.11 is a hard floor, and it collides with §2.1 | **REVISED** | Step 5 states the floor as a floor with the reason (`config.py:41` imports `tomllib`; on 3.10 every `sb` command dies on line one), gives `python3 -V` as the check, and names the trap explicitly: **22.04 has the safe lsof but Python 3.10; 24.04 has 3.12 but needs the §2.1 fix. 24.04 + the fix is the supported combination.** |
| F6 | `wsl --install`'s failures are silent ones; no verification | **REVISED** | Step 1 now says what success looks like, names the help-text-instead-of-installing shape on older Windows 10 with the `wsl --set-default-version 2` + Store recovery, and mentions Store-blocked corporate machines. New step 2 is `wsl -l -v` as the verification. Windows 10 Home confirmed fine and stated. |
| F7 | No verification step, no day-2 | **REVISED** | New step 12 runs `sb doctor` and explains what it checks — the herdr **≥ 0.8.0** minimum (`defaults/settings.toml:654`) and the `claude`-integration conflict that makes herdr *silently* reject state writes (`herdr.py:320-335`, `1049-1052`). New **Part 5 — day 2** covers reattach/detach, `wsl --shutdown` and sleep (pointing at §6's open question), where state lives and that it is disposable, and updating. |
| F8 | §2.2 is right but step 3 makes it easy to get wrong | **REVISED** | Step 9 gives the positive path (`cd ~` then clone) and a readable self-check — **`pwd` must start with `/home/`, never `/mnt/`** — plus the three natural ways a non-developer lands on the wrong side, and the point that it *looks* fine either way. |
| §2 honesty | "~one-command install" vs the real step count | **REVISED** | The phrase is **withdrawn** from §4's rank-1 row and from §2.4, which now counts the real sequence and flags which steps fail silently. §5 states that the guide, not the code, is the largest piece of work, and that it must be walked on a real machine before anyone is handed it. |
| §3 step 6 | Asked a non-developer to hand-patch `live.py` | **REVISED** | Deleted as a step. It is now a **prerequisite stated at the top of §3**: the §2.1 fix ships in the repo before anyone is handed the guide. The reviewer is right that a setup guide must never ask its reader to edit source. |

## Reported, not fixed: `scripts/00-preflight.sh:26`

That line tells the reader *"we need 'claude' installed. If absent: herdr integration install
claude"*. `switchboard/herdr.py:320-335` **refuses to start** when that integration is present. A
reader who follows the preflight script breaks their install. Verified both sides. Stale, unrelated
to Windows, and out of this plan's scope — §3 step 12 warns readers off it, and it is flagged
upward rather than fixed here.

## Where the plan stands after three rounds

The recommendation has not moved and has not been seriously attacked in any round. What has gone is
the plan's comfort:

- Round 1 took "zero code changes" (F1/lsof is measured broken on the default distro).
- Round 2 took "setup is just installs" (the doorbell needs configuration, and fails invisibly).
- Round 3 took "the deliverable is mostly a setup guide" — §3 is now an actual guide, and the plan
  says plainly that writing and validating it is the largest piece of work in it.

Each round has attacked reasons and completeness rather than the conclusion, and each time the
reasons were weaker than written while the conclusion held.
