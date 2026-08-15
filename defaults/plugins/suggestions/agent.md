<!-- Injected into every spawn, flattened to one line and capped at [limits]
     plugin_fragment. Written to fit well under that cap rather than be cut by it: this is
     paid on every spawn forever, so it says the verb, the bar, and nothing else.

     The bar is stated here as well as enforced in code on purpose. Enforcement alone gets
     an agent a refusal it then has to guess its way past; three named questions get a
     filed suggestion on the first try. -->
# suggestions

- Switchboard worked but cost you anyway — recurring friction, not a bug? File it: `sb plugin suggestions file "<the improvement>" --friction "<what you hit>" --cost "<time, retries, agents, work thrown away>" --recurs "<why it will happen again, or where you saw it before>"`.
- All three flags are required and it is refused without them. Concrete only: friction from the task you were actually doing, never a hypothetical.
- Bugs go to `report-bug` instead. Filing either never changes anything — carry on with your task.
