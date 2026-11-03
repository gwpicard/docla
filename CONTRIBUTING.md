# Contributing

doclo uses the Developer Certificate of Origin (DCO) instead of a contributor license agreement. By signing off a commit, you certify that you wrote the change or have the right to submit it under the project's license. The full text is at <https://developercertificate.org>.

## Signing off

Add a sign-off to every commit with the `-s` flag:

```
git commit -s -m "Describe the change"
```

This appends a line with your name and email to the commit message:

```
Signed-off-by: Your Name <you@example.com>
```

To add a missing sign-off to your latest commit, run `git commit --amend -s --no-edit`.

## Pull requests

Every pull request needs a `Signed-off-by:` line on each of its commits. Merge commits are exempt. Check your branch before opening the pull request:

```
python scripts/check_dco.py origin/main..HEAD
```

The script prints `unsigned: <short hash> <subject>` for each commit without a sign-off and exits 1.
