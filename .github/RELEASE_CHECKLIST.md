# Private SEAM Runtime Release Checklist

This checklist governs GitHub Releases created from this private repository.
It does not authorize PyPI publication, a public-client release, or deployment.

## Prepare through a pull request

- [ ] Open a release-proposal issue using the repository form.
- [ ] Choose the exact SemVer version and protected-main target.
- [ ] Update `pyproject.toml` and every version-bearing contract intentionally.
- [ ] Record user-visible changes and migration or compatibility notes.
- [ ] Run the relevant focused tests, canonical non-external suite, and live
      external lane when the changed scope requires it.
- [ ] Pass the required protected-main checks and record advisory failures
      honestly; run the manual Windows lane when the release scope warrants it.
- [ ] Complete SEAM history, handoff, snapshot, secret/session scan, and
      continuity closeout before merge.

## Publish from protected main

- [ ] Confirm the release commit is the current protected-main head.
- [ ] Confirm `v<version>` does not already exist as a tag or release.
- [ ] Dispatch **Package release** on `main` with the exact version already in
      `pyproject.toml`.
- [ ] Let the `private-package-release` environment gate the publishing job.
- [ ] Review the generated draft release notes for private data, secrets,
      provider session links, and unsupported deployment or benchmark claims.
- [ ] After that review, manually publish the reviewed draft from GitHub.
- [ ] Do not add PyPI credentials, `id-token: write`, or a public target.

## Verify the immutable release

- [ ] Confirm the release targets the intended full commit SHA.
- [ ] Confirm the wheel, sdist, and `SHA256SUMS.txt` are attached.
- [ ] Download the assets and verify `sha256sum -c SHA256SUMS.txt`.
- [ ] Confirm the published notes match the reviewed draft and include the
      intended pull requests.
- [ ] Confirm GitHub marks the release immutable.
- [ ] Record the release URL, tag, asset digests, verification boundary, and
      any downstream deployment work in append-only SEAM history.

Public `seam-client` work belongs in the separate `Seam_Runtime` repository.
The retired private-to-public mirror must not be reintroduced here.
