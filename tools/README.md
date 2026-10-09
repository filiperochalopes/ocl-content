# Shared Tools

## `ocl_source_config.py`

Validates and synchronizes declarative OCL Source metadata kept in a terminology `source.json` file.

It manages:

- `properties` definitions and their display labels/descriptions;
- `filters` and their configured order;
- `meta.display.concept_summary_properties` and `concept_filter_order`;
- optionally, `hierarchy_meaning` and `hierarchy_root_url`.

The default invocation is local-only. `--check` reads the target Source; `--apply` requires both `--check` and an exact `--confirm-target OWNER/SOURCE` acknowledgement. Remote calls default to the production API origin; custom HTTPS origins and local HTTP development servers require explicit opt-in flags, and redirects are rejected to prevent token forwarding. After a PATCH it reads the Source back and verifies every managed field.

```bash
python3 tools/ocl_source_config.py --config terminologies/icd/icd-10/source.json
```

See [`../skills/ocl-api/SKILL.md`](../skills/ocl-api/SKILL.md) for CLI and API operation guidance.
