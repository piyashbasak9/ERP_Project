# ERP Management System

This repository contains the Django platform and phased implementation of a microfinance ERP. The complete functional requirements, security rules, business rules and delivery roadmap are documented in [README_Django_ERP.md](README_Django_ERP.md).

## Current platform

The existing application includes:

- Dashboard and authentication with safe post-login redirects and POST-only logout.
- Django ORM user and role management with default-deny route permissions.
- Branch hierarchy and branch-scoped organization/member foundations.
- Member profiles, status history and KYC document handling.
- Accounting foundations: chart of accounts, fiscal periods, balanced journals, reversals, reconciliation and trial balance.
- Savings foundation: configurable products, individual/group accounts, audited transactions, interest and fee postings, statements and branch-scoped balances.
- Audit-log foundation, shared page layout, popup workflows and timed notifications.
- PostgreSQL as the database and Django migrations as the sole schema-management system.

The MFI modules in the specification are being delivered in roadmap order. See the status tables in [README_Django_ERP.md](README_Django_ERP.md); do not treat planned or partial features as production-ready.

## Requirements

- Python 3.12
- PostgreSQL
- Dependencies pinned in `requirements.txt`

## Local setup

1. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Configure the environment. Copy `.env.example` to `.env`, replace all placeholders with local values, and keep `.env` out of version control. The required settings are `DJANGO_SECRET_KEY`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`. Export those variables into your shell before running Django (for Bash, use `set -a; source .env; set +a`). Use a least-privilege PostgreSQL application user, not the database superuser.

4. Create an empty PostgreSQL database and apply Django migrations:

   ```bash
   python manage.py migrate
   python manage.py sync_permissions
   ```

5. Create the initial administrator and start the development server:

   ```bash
   python manage.py createsuperuser
   python manage.py runserver
   ```

   Open `http://127.0.0.1:8000/`. The public health endpoint is `/health/`.

## Security notes

- Never put credentials or production secrets in source code, examples, logs or commits.
- All model access and schema changes must use Django ORM and Django migrations; do not introduce raw SQL, SQLAlchemy or Alembic.
- Route access is denied by default. Only an explicitly assigned active role permission grants access; `is_staff` alone is not an application-level bypass.
- Private uploads are stored outside public static paths and must be served by authorized views.
- State-changing views require POST and CSRF protection.

## Validation

Run the Django system checks and migration consistency check:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
```

Run automated tests with:

```bash
python manage.py test
```
