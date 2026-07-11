# Bulk import templates

Fill these CSVs (open in Excel/Sheets, keep the header row) and send them back —
we'll load them with one command each. Codes (`ITM-…`, `EMP-…`) are assigned
automatically; don't add them.

## items_template.csv
One row per catalogue item.

| column | required | notes |
|--------|----------|-------|
| description | ✅ | the item name / spec |
| unit | ✅ | bag, kg, nos, m, m3, length … |
| category | | must match an **Item Category** already set up (Civil, MEP, Finishes …); leave blank if unsure |
| brand | | optional |
| spec_ref | | optional standard/spec |
| is_major | | `yes` to flag a key material that appears on the DPR loader; else blank |

## employees_template.csv
One row per employee.

| column | required | notes |
|--------|----------|-------|
| full_name | ✅ | |
| site_code | | current site, e.g. `SJR`, `VKR`, `MLE` (Head Office); creates their allocation |
| job_category | | worker category, e.g. `Mason`, `Supervisor`, `Project Manager` |
| nationality | | |
| basic_pay | | monthly salary (numbers only) |
| currency | | `MVR` (default) or `USD` |
| passport_no | | used to avoid duplicate imports |
| date_of_birth | | `YYYY-MM-DD` (or `DD/MM/YYYY`) |
| join_date | | `YYYY-MM-DD` |
| work_permit_no | | permanent staff |
| work_permit_expiry | | `YYYY-MM-DD` |
| emergency_contact | | |

## tools_template.csv
One row per **physical tool** already on a site (existing register / mobilised
tools). Tools received later via GRN are added automatically.

| column | required | notes |
|--------|----------|-------|
| site_code | ✅ | the site the tool is at, e.g. `CNR`, `SJR`, `MLE` |
| name | ✅ | tool name, e.g. `Battery drill` — keep spelling consistent so the DPR summary groups them |
| category | | e.g. `Tools & Equipment`, `Machinery` |
| serial_no | | used to avoid duplicate imports |
| model | | |
| brand | | |
| state | | `IN_USE` (default) / `FAULTY` / `UNDER_REPAIR` / `RETIRED` |
| notes | | |

## Loading (we'll run these together)
```
python manage.py import_items     items.csv     --dry-run   # preview
python manage.py import_items     items.csv                 # commit
python manage.py import_employees staff.csv     --dry-run
python manage.py import_employees staff.csv
python manage.py import_tools     tools.csv     --dry-run
python manage.py import_tools     tools.csv
```
Re-running the same file is safe — existing items (by description) and
employees (by passport no.) are skipped, not duplicated.
