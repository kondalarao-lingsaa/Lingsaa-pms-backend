from datetime import datetime , timezone
import pytz
import traceback
from local.logging_config import performence_logger,error_logger

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


def parse_date_to_datetime_c(date):
    try:
        if date is None:
            return None
        if "T" in date and "Z" in date:
            return datetime.strptime(date, '%Y-%m-%d %H:%M:%S.%f%z').astimezone(ZoneInfo('Asia/Kolkata'))
        return datetime.strptime(date, "%Y-%m-%d %H:%M:%S")
    except Exception as e:
        print(e)
        print("error parsing date")

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

def parse_date_to_str(date):
    try:
        if date is None:
            return None
        return date.strftime('%d/%m/%Y')
    except Exception as e:
        print(e)
        print("error parsing date")
def parse_date_to_db_time(date):
    try:
        if date is None:
            return None
        return date.strftime('%Y-%m-%d')
    except Exception as e:
        print(e)
        print("error parsing date")

def str_date_parse_date(date):
    try:
        if date is None:
            return None
        if "T" in date and "Z" in date:
            dt = datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%f%z')
            formatted_date = dt.strftime('%d-%m-%Y')
            return formatted_date
        return datetime.strptime(date, "%d-%m-%Y").strftime("%d-%m-%Y")
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

def parse_str_date_to_str(date):
    try:
        if date is None:
            return None
        if "T" in date and "Z" in date:
            dt = datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%f%z')
            formatted_date = dt.strftime('%d-%m-%Y')
            return formatted_date
        dt = datetime.strptime(date, '%Y-%m-%d')
        formatted_date = dt.strftime('%d-%m-%Y')
        return formatted_date
    except Exception as e:
        print(e)
        print("errorparse_str_date_to_str")

def parse_datetime_to_str_for_live(date):
    import pandas as pd
    date = pd.to_datetime(date)
    try:
        if date is None:
            return None
        return date.strftime('%d-%m-%Y %H:%M:%S')
    except Exception as e:
        print(e)
        print("error parsing date")


def get_timediff_in_minutes(olddate, newdate):
    diff = str(newdate-olddate)
    minutes = 0
    # more than or a day
    a = diff.split(",")
    if len(a) > 1:
        minutes += int(a[0].split(" ")[0])*1440
        minutes += int(a[1].split(":")[0])*60
        minutes += int(a[1].split(":")[1])
    else:
        minutes += int(a[0].split(":")[0])*60
        minutes += int(a[0].split(":")[1])
    return minutes


def parse_date_to_str_yfirst(date):
    try:
        if date is None:
            return None
        return date.strftime('%Y-%m-%d')
    except Exception as e:
        print(e)
        print("error parsing date")


def parse_datetime_to_str_yfirst(date):
    try:
        if date is None:
            return None
        return date.strftime('%Y-%m-%dT%H:%M:%S+05:30')
    except Exception as e:
        print(e)
        print("error parsing date")


    
def parse_date_to_str_formate(date):
    try:
        if date is None:
            return None
        return date.strftime('%d-%m-%Y')
    except Exception as e:
        print(e)
        print("error parsing date")

def rounding_close_value(close):
    res_modulous = close % 100
    # rounded_close_value = 0

    if res_modulous >= 50:
        rounded_close_value = close + (100 - res_modulous)
        # print("ronded_close_value",rounded_close_value)
    else:
        rounded_close_value = close - res_modulous
    return rounded_close_value

def converted_indiantime():
    from datetime import datetime
    import pytz

    # Get the current date and time
    kolkata_tz = pytz.timezone('Asia/Kolkata')
    current_datetime = datetime.now(kolkata_tz)
    formatted_datetime = current_datetime.strftime('%Y-%m-%d %H:%M:%S')
    return formatted_datetime
        
def convert_dict_to_object():
    from types import SimpleNamespace
    temp = {}
    temp['status'] = '1'
    result = SimpleNamespace(**temp)
    return result

def convert_unix_timestamp_to_time(timestamp):
    try:
        if timestamp is None:
            return None
        
        timestamp = timestamp  

        # Convert to UTC datetime using timezone-aware method
        utc_time = datetime.fromtimestamp(timestamp, timezone.utc)

        # Define IST timezone
        ist_timezone = pytz.timezone('Asia/Kolkata')

        # Convert to IST datetime
        ist_time = utc_time.astimezone(ist_timezone)

        # Print result
        print("IST Date & Time:", ist_time.strftime('%Y-%m-%d %H:%M:%S'))

        return ist_time.strftime('%Y-%m-%d %H:%M:%S')
    except Exception as e:
        traceback.print_exc()
        error_logger.error(f"Error in convert_unix_timestamp_to_time: {e}")

def convert_datetime_to_unix_timestamp(datetime_str):
    try:

        ist = pytz.timezone('Asia/Kolkata')

        localizing = ist.localize(datetime.strptime(datetime_str,"%Y-%m-%d %H:%M:%S"))

        unix_timestamp = int(localizing.timestamp())
        performence_logger.debug('unix timestamp is',unix_timestamp)

        return unix_timestamp
    except Exception as e:
        traceback.print_exc()
        error_logger.error('Error in converting datetime to unix timestamp %s',e)
    
def format_amount_indian(amount):
    amount_str = str(int(amount))  # remove decimals if any
    # First group (last 3 digits)
    last_three = amount_str[-3:]
    rest = amount_str[:-3]
    if rest != '':
        # Add commas every 2 digits in the rest
        rest = ','.join([rest[max(i-2,0):i] for i in range(len(rest)%2, len(rest)+1, 2)]).lstrip(',')
        return rest + ',' + last_three
    else:
        return last_three


