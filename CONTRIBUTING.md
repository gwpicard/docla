# Contributing

docla uses the Developer Certificate of Origin (DCO) instead of a contributor license agreement. By signing off a pull request, you certify that you wrote the change or have the right to submit it under the project's license. The full text is at <https://developercertificate.org>.

## Pull requests

Nothing is committed directly to `main`. Every change arrives through a pull request.

The pull request description must contain a sign-off line with your name and email:

```
Signed-off-by: Your Name <you@example.com>
```

This one line certifies the Developer Certificate of Origin for every commit in the pull request. Individual commits do not need a sign-off.

Signing each commit with `git commit -s` is optional. Use it if you prefer, but the check reads only the line in the pull request description.

Maintainers listed in `MAINTAINERS` are exempt, because they hold the copyright.

To check a pull request event locally:

```
python scripts/check_dco.py --pr-event event.json --maintainers MAINTAINERS
```

The script prints `signed off` or `maintainer: <login>` and exits 0, or prints the missing sign-off message and exits 1.
