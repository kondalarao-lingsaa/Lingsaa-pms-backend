"""The company's working calendar: which days are worked and how many hours. One place for every screen that
counts working days (Capacity, Utilization, Sprint capacity, Reports), so changing Settings changes them all."""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.settings import DEFAULT_HOURS_PER_DAY, DEFAULT_WORKING_DAYS, CompanySettings, Holiday

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class WorkCalendar:
    def __init__(self, hours_per_day, weekdays, holidays):
        self.hours_per_day = float(hours_per_day)
        self.weekdays = set(weekdays)
        self.holidays = holidays  # {date: name}

    def is_working(self, d: date) -> bool:
        return d.weekday() in self.weekdays and d not in self.holidays

    def days(self, start: date, end: date) -> list:
        if not start or not end or end < start:
            return []
        return [start + timedelta(days=i) for i in range((end - start).days + 1) if self.is_working(start + timedelta(days=i))]

    def count(self, start: date, end: date) -> int:
        return len(self.days(start, end))

    def holidays_between(self, start: date, end: date) -> list:
        return sorted((d, n) for d, n in self.holidays.items() if start <= d <= end)


def parse_weekdays(text) -> list:
    return sorted({int(x) for x in (text or DEFAULT_WORKING_DAYS).split(",") if x.strip().isdigit() and 0 <= int(x) <= 6})


def for_client(db: Session, client_id: int) -> WorkCalendar:
    row = db.query(CompanySettings).filter(CompanySettings.client_id == client_id).one_or_none()
    holidays = dict(db.query(Holiday.holiday_date, Holiday.name).filter(Holiday.client_id == client_id).all())
    if row is None:
        return WorkCalendar(DEFAULT_HOURS_PER_DAY, parse_weekdays(DEFAULT_WORKING_DAYS), holidays)
    return WorkCalendar(row.hours_per_day, parse_weekdays(row.working_days), holidays)
