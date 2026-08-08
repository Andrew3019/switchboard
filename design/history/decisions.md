# Human decisions — binding

These override any assumption in your brief. Rework your proposal to fit them.

1. **Naming.** Prompt side = **presets**. Code side = **plugins**. So `sb delegate --with X`
   pulls a *preset*; `sb plugin todo add …` is a *plugin*. `sb plugins` as it exists today
   (listing prompt fragments) must be renamed — say exactly what to.

2. **Where they live.** Both presets and plugins must support **shipping in sb's
   `defaults/`** and **per-repo override in `.switchboard/`**. For now, author everything
   in `defaults/` — but the layering must exist in the design. Note that today plugin
   *files* are deliberately NOT layered from defaults/ (only bindings are); say what
   changes and why that original decision is or is not still right.

3. **Execution model.** Python, imported in-process by sb. No manifest DSL, no subprocess
   protocol. Keep the registration surface small enough that a future out-of-process
   escape hatch is not precluded, but do not build it.

4. **`todo` plugin.** Serves humans and agents equally. It is *just a database or
   filesystem store* — deliberately dumb. Agents manage it through the CLI. Global per
   repo identity, shared across worktrees. Surfacing todos in `sb status` is explicitly
   **out of scope for now** — design so it is possible later, do not spec it.

5. **`report-bug` plugin.** Whichever is simplest. Files on disk are fine. Do not design a
   GitHub integration.

6. **Scope.** High-level design alignment first. No implementation. Keep the doc focused
   on the contract and the shape of things, not on exhaustive code.
