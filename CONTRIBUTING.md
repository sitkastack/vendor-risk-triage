# Contributing

This is a public reference implementation built in the open. Outside contributions are welcome — particularly from practitioners with real-world audit, procurement, security, or AI governance experience.

## What's useful

- **Issues.** Questions, observations, disagreements with the taxonomy, real-world experience that contradicts what's documented here, and pointers to relevant regulatory guidance are all valuable. You don't need a code change in mind to open one.
- **Pull requests for typos, broken links, clarifications, and additional examples.** These are the easiest to land — open one directly.
- **Pull requests that add or change patterns.** For anything substantial — a new risk category, a change to the eval methodology, a new governance artifact — please open an issue first so we can align on direction before you spend time on the implementation.

## Code of conduct

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Be direct, be kind, assume good faith.

## License

This project is licensed under Apache 2.0. By submitting a contribution, you agree your contribution is offered under the same license.

## Developer Certificate of Origin (DCO)

All commits must be signed off under the [Developer Certificate of Origin](https://developercertificate.org/). The DCO is a lightweight, per-commit statement that you have the right to submit the contribution under the project's license. It is *not* a CLA — there is nothing to sign and no rights are assigned. It exists so the project has a clean, auditable provenance trail for every contribution, which matters for a repository that other people may adopt inside regulated environments.

To sign off, add the `-s` flag when you commit:

```
git commit -s -m "your commit message"
```

This appends a `Signed-off-by: Your Name <your@email>` line to the commit message, which is the DCO attestation. Configure `user.name` and `user.email` in git first if you haven't.

PRs with unsigned commits will be asked to rebase with sign-offs before merge.

## Getting started

1. Fork the repo and create a topic branch
2. Make your change
3. Commit with `-s` to sign off
4. Open a PR with a clear description of what changed and why

If you're not sure whether a change is worth making, opening an issue first is always fine.
