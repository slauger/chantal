# RPM fixtures

- `demo-1.0-1.noarch.rpm6-signed.rpm` was built and signed with **rpm 6.0.1**
  (Ubuntu 26.04, `rpmbuild -bb` + `rpmsign --addsign`). rpm 6 stores the
  header signature in `RPMSIGTAG_OPENPGP` (278) as base64 text and writes no
  `RSAHEADER`/`DSAHEADER` (268/267) tag.
- `rpm6-signing-key.asc` is the throwaway public key it was signed with
  (`rpm-test@chantal.local`, generated only for this fixture).
