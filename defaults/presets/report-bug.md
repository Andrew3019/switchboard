# report-bug

If you hit a bug in switchboard itself (the `sb` command or anything under
`switchboard/`), do not work around it and do not fix it inline unless that is your task.

- File it: `sb plugin report-bug file "<what broke>" --command "<what you ran>"
  --expected "..." --actual "<the exact error text>"`. One markdown file per report,
  kept per machine rather than per repo, so you can find it again from anywhere.
- Keep going with your actual task afterwards.
- If the bug blocks you entirely, run `sb block` instead.

A silent workaround hides the bug from everyone else and is worse than the bug.
