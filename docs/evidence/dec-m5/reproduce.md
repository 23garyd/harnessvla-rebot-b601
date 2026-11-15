# Technical notes on reproduction and archiving

Compilation date: 2026-11-14. This directory prepares the December technical delivery; it does not indicate December acceptance or completion of all final work.

Checked-out source commit: `e48995c4ca156bacf45cf60b70194d6bffd47957`. [archive-manifest.csv](archive-manifest.csv) provides a pinned GitHub link, byte count, and SHA-256 for each code file and existing attachment. The archive covers all tracked files in that source commit; it excludes the newly created dec-m5 directory itself, whose integrity is recorded separately in [manifest.csv](manifest.csv) to avoid circular hashes.

```bash
git clone https://github.com/23garyd/harnessvla-rebot-b601.git
cd harnessvla-rebot-b601
git checkout e48995c4ca156bacf45cf60b70194d6bffd47957
```

Paths in the archive CSV are relative to the repository root. Verify each item with SHA-256 after downloading/checking out; Git attributes for the evidence directories protect file bytes. The repository remains private and requires existing access authorization.

[Test commands and actual output from the existing environment](../nov-m4/verification/2026-11-14-tests.txt) establish only that the specified hardware-free software subset runs. Prepare the full software dependencies, GPU, vendor SDK, models, and raw data separately according to the [repository instructions](../../../README.md) and the original environment lock files.

Work completed here consists of checking out code from the existing private source and verifying attachments and a software subset. The complete system has not been rebuilt on a clean machine, and independent third-party execution of real trials has not been verified. Do not directly run physical robot entry points on an unmeasured/uncalibrated machine; the current software checks do not require powering on the arm.

[setup.sh](../../../b601/setup/setup.sh), [requirements.txt](../../../b601/setup/requirements.txt), and [pin_check.sh](../../../b601/setup/pin_check.sh) are the environment setup and gate entry points. Recording new pins changes the environment baseline and should follow confirmation of the actual configuration; do not use --record for routine read-only verification. Raw data, ACT weights, and all videos are not included in the archive CSV.
