# Q4R3 R0 Read-only Guarantees

The R0 audit may read files, systemd metadata, process metadata, and Git history. It may write only:

- its dedicated runtime evidence directory
- a detached temporary Git worktree
- sanitized evidence files on its audit branch

It must not restart, stop, start, enable, disable, mask, unmask, or reload any service. It must not modify the active repository tree, Formal Ledger, Producer, Writer, Strategy, Method, Skill Registry, Paper, Live, or Order surfaces.

The runner verifies Producer and Writer PIDs and verifies that the pre-existing Formal Ledger prefix is byte-identical after the audit.
