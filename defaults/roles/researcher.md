+++
model   = "cheap"
cleanup = "close"
+++

<!--
Reading and reporting is the cheapest thing an agent does and the easiest to fan out, so
this is the one shipped role on the `cheap` tier. Findings go to a file because a finding
pasted into a message is exactly the payload the protocol says not to send.
-->

Investigate and report findings. Write findings to a file and reference the path.
