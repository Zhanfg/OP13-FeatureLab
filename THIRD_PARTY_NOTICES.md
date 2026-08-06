# Third-party notices

OP13 FeatureLab is designed to interoperate with Android root/module environments and may incorporate or adapt separately licensed components.

## Known upstream projects

### KernelSU

- Project: KernelSU
- License: GPL-3.0
- Use: module lifecycle, WebUI host API and systemless module environment
- Requirement: preserve upstream copyright and license notices for any copied or modified file.

### Magisk module installer components

- Project: Magisk
- License: GPL-3.0-or-later
- Use: compatible installation entry points and module packaging conventions
- Requirement: pin imported files to an upstream commit and retain original notices.

### Android Open Source Project

- Project: Android Open Source Project
- License: file-dependent, commonly Apache-2.0 and other stated licenses
- Use: public interfaces, service behavior, schemas and documentation references
- Requirement: preserve the license of each imported file; do not assume the repository-wide GPL replaces it.

## Attribution procedure

Every imported third-party file must be listed with:

- upstream repository and exact commit;
- original path;
- local path;
- original license identifier;
- whether the file is unmodified or modified;
- modification summary and date.

## Exclusion

No ColorOS/OPlus/OPPO/OnePlus/Qualcomm/Dolby/ODM firmware configuration is licensed by this project's GPL license merely because it was used as local input. See PROPRIETARY_ASSETS.md.