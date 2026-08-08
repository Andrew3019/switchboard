+++
model   = "default"
cleanup = "close"
+++

<!--
The fallback role, in two senses: it is what `sb delegate` uses when nobody says
otherwise, and a role NOBODY has defined inherits its fields while keeping its own name.
So an ad-hoc `--role archaeologist` works without anyone editing a file first — vocabulary
is data. Both behaviours point at `[vocabulary] default_role` / `fallback_role` in
settings.toml rather than at the string "worker" anywhere in Python.

Change what a worker is and you change what an undefined role is. That is intended.
-->

Do exactly the task you are given and nothing beyond it.
