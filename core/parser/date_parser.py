from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo


def parse_date(date):
    try:
        if date is None:
            return None
        if "T" in date and "Z" in date:
            return datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%f%z').astimezone(ZoneInfo('Asia/Kolkata')).date()
        return datetime.strptime(date, "%d/%m/%Y").date()
    except Exception as e:
        print(e)
        print("error parsing date")


def parse_date_to_datetime(date):
    try:
        if date is None:
            return None
        if "T" in date and "Z" in date:
            return datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%f%z').astimezone(ZoneInfo('Asia/Kolkata'))
        return datetime.strptime(date, "%d/%m/%Y")
    except Exception as e:
        print(e)
        print("error parsing date")

def parse_date_to_str(date):
    try:
        if date is None:
            return None
        return date.strftime('%d/%m/%Y')
    except Exception as e:
        print(e)
        print("error parsing date")

def parse_time_to_str(date):
    try:
        if date is None:
            return None
        return date.strftime('%H:%M')
    except Exception as e:
        print(e)
        print("error parsing date")

def yf_date_to_str(date):
    try:
        if date is None:
            return None
        return date.strftime('%Y-%m-%d')
    except Exception as e:
        print(e)
        print("error parsing date")

def parse_yf_to_df(date):
    try:
        if date is None:
            return None
        if "T" in date and "Z" in date:
            return datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%f%z').astimezone(ZoneInfo('Asia/Kolkata')).date()
        return datetime.strptime(date, '%Y-%m-%d').date()
    except Exception as e:
        print(e)
        print("error parsing date")

def parse_datetime_to_str(date):
    try:
        if date is None:
            return None
        return date.strftime('%d-%m-%Y %H:%M:%S')
    except Exception as e:
        print(e)
        print("error parsing date")
