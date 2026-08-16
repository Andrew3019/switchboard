# worktree-model — brief (Andrew's words, verbatim)

help me understnad how worktrees work right now .
1. who creates worktrees? who shares worktrees? what happens if worktree is shared due to rules when it should be split further?
2. worktree lifecycle? when its abandoned, cleaned up, etc. all the paths that go to it
3. is this the correct way its supposed to be ? what i want right now is
a) worktrees can be created as needed. dont always need to have write agents to justify a worktree
b) worktrees are cleaned. when merged, when all agents on a worktree are closed (abandoned), when worktree contains only docs changes that are like artifacts or audits and provide no benefit in a week (closed). basically worktrees only persist as long as agents on it do. if a worktree needs to be kept longer, it should be pushed as a pr already, then can be removed / restored from origin.

investigate the state of this. keep the main investiagtion agent, ill communitcate with them before returning to u
