"""Company Settings: the working calendar (hours per day, working weekdays) and holidays."""
from datetime import date

from sqlalchemy.orm import Session

from app.core.industries import DEFAULT_INDUSTRY, INDUSTRIES, preset
from app.models.settings import CompanySettings, Holiday
from app.repositories import approvals, work_calendar
from app.repositories.notifications import person_name
from app.schemas.rules import utc_iso


class SettingsError(Exception):
    """A settings rule was broken; the message is safe to show to the user."""


def holiday_out(h: Holiday) -> dict:
    return {"id": h.id, "holiday_date": h.holiday_date.isoformat(), "name": h.name, "weekday": work_calendar.WEEKDAY_NAMES[h.holiday_date.weekday()]}


def get_settings(db: Session, principal, year=None) -> dict:
    cal = work_calendar.for_client(db, principal.client_id)
    row = db.query(CompanySettings).filter(CompanySettings.client_id == principal.client_id).one_or_none()
    year = year or date.today().year
    holidays = (
        db.query(Holiday)
        .filter(Holiday.client_id == principal.client_id, Holiday.holiday_date >= date(year, 1, 1), Holiday.holiday_date <= date(year, 12, 31))
        .order_by(Holiday.holiday_date)
        .all()
    )
    start, end = date(year, 1, 1), date(year, 12, 31)
    return {
        "hours_per_day": cal.hours_per_day,
        "working_days": sorted(cal.weekdays),
        "weekday_names": work_calendar.WEEKDAY_NAMES,
        "is_default": row is None,
        "updated_by_name": row.updated_by_name if row else None,
        "updated_at": utc_iso(row.updated_at) if row else None,
        "year": year,
        "holidays": [holiday_out(h) for h in holidays],
        "industry": industry_of(row),
        # True when the company typed its own industry instead of picking one of the presets.
        "custom_industry": industry_of(row) not in INDUSTRIES,
        "member_roles": company_roles(db, principal.client_id),
        # Presets, so the screen can fill the role list when the industry changes.
        "industries": [{"name": name, "roles": p["roles"], "template": p["template"]["name"]} for name, p in INDUSTRIES.items()],
        # What the calendar means for the year, so people see the effect of a change.
        "year_working_days": cal.count(start, end),
        "year_working_hours": round(cal.count(start, end) * cal.hours_per_day, 1),
        "approvals": approvals.limits_out(db, principal.client_id),
    }


def save_calendar(db: Session, principal, hours_per_day, working_days) -> None:
    row = db.query(CompanySettings).filter(CompanySettings.client_id == principal.client_id).one_or_none()
    if row is None:
        row = CompanySettings(client_id=principal.client_id)
        db.add(row)
    row.hours_per_day = hours_per_day
    row.working_days = ",".join(str(d) for d in working_days)
    row.updated_by = principal.user_id
    row.updated_by_name = person_name(principal.user_name) or principal.user_name
    db.commit()


def industry_of(row) -> str:
    return row.industry if row is not None and row.industry else DEFAULT_INDUSTRY


def company_roles(db: Session, client_id) -> list[str]:
    """The team roles this company uses: its own list, else its industry's preset."""
    row = db.query(CompanySettings).filter(CompanySettings.client_id == client_id).one_or_none()
    if row is not None and row.member_roles:
        return [r for r in row.member_roles.split("|") if r]
    return list(preset(industry_of(row))["roles"])


def save_industry(db: Session, principal, industry, roles) -> None:
    row = db.query(CompanySettings).filter(CompanySettings.client_id == principal.client_id).one_or_none()
    if row is None:
        row = CompanySettings(client_id=principal.client_id)
        db.add(row)
    row.industry = industry
    row.member_roles = "|".join(roles)
    row.updated_by = principal.user_id
    row.updated_by_name = person_name(principal.user_name) or principal.user_name
    db.commit()


def add_holiday(db: Session, principal, holiday_date, name) -> Holiday:
    existing = db.query(Holiday).filter(Holiday.client_id == principal.client_id, Holiday.holiday_date == holiday_date).one_or_none()
    if existing:
        raise SettingsError(f"{holiday_date.strftime('%d %b %Y')} is already a holiday ({existing.name})")
    h = Holiday(client_id=principal.client_id, holiday_date=holiday_date, name=name, created_by=principal.user_id)
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


def delete_holiday(db: Session, principal, holiday_id) -> str:
    h = db.query(Holiday).filter(Holiday.client_id == principal.client_id, Holiday.id == holiday_id).one_or_none()
    if h is None:
        raise LookupError("Holiday not found")
    name = h.name
    db.delete(h)
    db.commit()
    return name
