import os
import sys
from datetime import datetime, timedelta

import pytz
import requests
from icalendar import Calendar, Event


# --- 설정 ---
NX = int(os.environ.get("KMA_NX", 60))
NY = int(os.environ.get("KMA_NY", 127))
LOCATION_NAME = os.environ.get("LOCATION_NAME", "우리집")
REG_ID_TEMP = os.environ.get("REG_ID_TEMP", "11B10101")
REG_ID_LAND = os.environ.get("REG_ID_LAND", "11B00000")
API_KEY = os.environ.get("KMA_API_KEY")

SEOUL_TZ = pytz.timezone("Asia/Seoul")
SHORT_RELEASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)


def get_weather_info(sky, pty):
    sky, pty = str(sky), str(pty)
    precipitation = {
        "1": ("🌧️", "비"),
        "2": ("🌨️", "비/눈(진눈깨비)"),
        "3": ("❄️", "눈"),
        "4": ("☔", "소나기"),
        "5": ("💧", "빗방울"),
        "6": ("🌨️", "빗방울/눈날림"),
        "7": ("❄️", "눈날림"),
    }
    if pty in precipitation:
        return precipitation[pty]

    sky_map = {
        "1": ("☀️", "맑음"),
        "3": ("⛅", "구름많음"),
        "4": ("☁️", "흐림"),
    }
    return sky_map.get(sky, ("🌡️", "정보없음"))


def get_mid_emoji(weather):
    if not weather:
        return "🌡️"
    text = str(weather).replace(" ", "")
    if "소나기" in text:
        return "☔"
    if "진눈깨비" in text:
        return "🌨️"
    if "눈" in text:
        return "❄️"
    if "비" in text:
        return "🌧️"
    if "구름많음" in text:
        return "⛅"
    if "흐림" in text:
        return "☁️"
    if "맑음" in text:
        return "☀️"
    return "🌡️"


def fetch_api(endpoint, params, retries=2, timeout=15):
    """HTTP 상태와 기상청 resultCode를 모두 검증한다."""
    safe_params = {**params, "authKey": "***"}
    last_error = "unknown error"

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(endpoint, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            header = data.get("response", {}).get("header", {})
            result_code = str(header.get("resultCode", ""))
            result_msg = header.get("resultMsg", "")

            if result_code == "00":
                return data

            last_error = f"resultCode={result_code}, resultMsg={result_msg}"
            print(
                f"[API FAIL] {attempt}/{retries} {last_error} "
                f"endpoint={endpoint} params={safe_params}"
            )
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            print(
                f"[API EXCEPTION] {attempt}/{retries} {last_error} "
                f"endpoint={endpoint} params={safe_params}"
            )

    print(f"[API GIVEUP] {last_error} endpoint={endpoint}")
    return None


def get_short_base_datetime(now):
    """단기예보 발표 직후 지연을 고려해 10분 전 기준 최신 발표시각을 고른다."""
    effective_now = now - timedelta(minutes=10)
    valid_hours = [hour for hour in SHORT_RELEASE_HOURS if hour <= effective_now.hour]

    if valid_hours:
        base_hour = max(valid_hours)
        return effective_now.strftime("%Y%m%d"), f"{base_hour:02d}00"

    previous_day = effective_now - timedelta(days=1)
    return previous_day.strftime("%Y%m%d"), "2300"


def get_mid_tmfc_candidates(now):
    """아직 발표되지 않은 06/18시 자료를 요청하지 않는다."""
    effective_now = now - timedelta(minutes=30)

    if effective_now.hour < 6:
        first = (effective_now - timedelta(days=1)).replace(
            hour=18, minute=0, second=0, microsecond=0
        )
        second = (effective_now - timedelta(days=2)).replace(
            hour=18, minute=0, second=0, microsecond=0
        )
    elif effective_now.hour < 18:
        first = effective_now.replace(hour=6, minute=0, second=0, microsecond=0)
        second = (effective_now - timedelta(days=1)).replace(
            hour=18, minute=0, second=0, microsecond=0
        )
    else:
        first = effective_now.replace(hour=18, minute=0, second=0, microsecond=0)
        second = effective_now.replace(hour=6, minute=0, second=0, microsecond=0)

    return [first, second]


def load_cached_events(path):
    cached = {}
    if not os.path.exists(path):
        return cached

    try:
        with open(path, "rb") as file:
            calendar = Calendar.from_ical(file.read())

        for component in calendar.walk("VEVENT"):
            dtstart = component.get("dtstart")
            if not dtstart:
                continue
            value = dtstart.dt
            if isinstance(value, datetime):
                value = value.date()
            cached[value.strftime("%Y%m%d")] = component.to_ical()
    except Exception as exc:
        print(f"[CACHE WARN] 기존 ICS 파싱 실패: {type(exc).__name__}: {exc}")

    return cached


def event_from_cache(raw_ical):
    try:
        wrapped = (
            b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            + raw_ical
            + b"\r\nEND:VCALENDAR\r\n"
        )
        calendar = Calendar.from_ical(wrapped)
        events = calendar.walk("VEVENT")
        return events[0] if events else None
    except Exception as exc:
        print(f"[CACHE WARN] 캐시 이벤트 복원 실패: {type(exc).__name__}: {exc}")
        return None


def add_cached_event(calendar, cached_events, date_str, processed_dates):
    raw = cached_events.get(date_str)
    if not raw:
        return False

    event = event_from_cache(raw)
    if not event:
        return False

    # 과거 잘못 생성된 None°C 이벤트는 캐시로도 되살리지 않는다.
    summary = str(event.get("summary", ""))
    if "None" in summary:
        print(f"[CACHE WARN] {date_str} 캐시에 잘못된 값이 있어 무시합니다: {summary}")
        return False

    calendar.add_component(event)
    processed_dates.add(date_str)
    return True


def parse_short_forecast(data):
    result = {}
    if not data:
        return result

    try:
        items = data["response"]["body"]["items"]["item"]
    except (KeyError, TypeError):
        return result

    for item in items or []:
        try:
            date_str = item["fcstDate"]
            time_str = item["fcstTime"]
            category = item["category"]
            value = item["fcstValue"]
        except KeyError:
            continue
        result.setdefault(date_str, {}).setdefault(time_str, {})[category] = value

    return result


def make_short_event(target_date, day_data, now, update_ts):
    temperatures = []
    for hourly in day_data.values():
        if "TMP" not in hourly:
            continue
        try:
            temperatures.append(float(hourly["TMP"]))
        except (TypeError, ValueError):
            pass

    if not temperatures:
        return None

    sorted_times = sorted(day_data.keys())
    if not sorted_times:
        return None

    representative_time = "1200" if "1200" in day_data else sorted_times[0]
    representative = day_data[representative_time]
    representative_emoji, _ = get_weather_info(
        representative.get("SKY", "1"), representative.get("PTY", "0")
    )

    state = {
        "TMP": None,
        "SKY": "1",
        "PTY": "0",
        "REH": None,
        "WSD": None,
        "POP": "0",
    }
    description = []

    for time_str in sorted_times:
        hourly = day_data[time_str]
        for category in state:
            if category in hourly:
                state[category] = hourly[category]

        try:
            event_time = SEOUL_TZ.localize(
                datetime.strptime(target_date.strftime("%Y%m%d") + time_str, "%Y%m%d%H%M")
            )
        except ValueError:
            continue

        if event_time < now or state["TMP"] is None:
            continue

        emoji, weather_text = get_weather_info(state["SKY"], state["PTY"])
        details = []
        if state["PTY"] != "0":
            details.append(f"☔{state['POP']}%")
        if state["REH"] is not None:
            details.append(f"💧{state['REH']}%")
        if state["WSD"] is not None:
            details.append(f"🚩{state['WSD']}m/s")
        detail_text = f" ({' '.join(details)})" if details else ""
        description.append(
            f"[{time_str[:2]}시] {emoji} {weather_text} {state['TMP']}°C{detail_text}"
        )

    event = Event()
    event.add(
        "summary",
        f"{representative_emoji} {int(min(temperatures))}°C/{int(max(temperatures))}°C",
    )
    event.add("location", LOCATION_NAME)
    if description:
        description.append(f"\n최종 업데이트: {update_ts} (KST)")
        event.add("description", "\n".join(description))
    event.add("dtstart", target_date)
    event.add("dtend", target_date + timedelta(days=1))
    event.add("uid", f"{target_date.strftime('%Y%m%d')}@short-summary")
    return event


def make_mid_event(target_date, tmfc_date, temp_items, land_items, update_ts):
    field_index = (target_date - tmfc_date).days
    if field_index < 3 or field_index > 10:
        return None

    temp_min = temp_items.get(f"taMin{field_index}")
    temp_max = temp_items.get(f"taMax{field_index}")
    if temp_min is None or temp_max is None:
        return None

    if field_index <= 7:
        weather_am = land_items.get(f"wf{field_index}Am")
        weather_pm = land_items.get(f"wf{field_index}Pm")
        rain_am = land_items.get(f"rnSt{field_index}Am")
        rain_pm = land_items.get(f"rnSt{field_index}Pm")
        if weather_am is None or weather_pm is None:
            return None
        representative_weather = weather_pm or weather_am
        lines = [
            f"[오전] {get_mid_emoji(weather_am)} {weather_am} (☔{rain_am}%)",
            f"[오후] {get_mid_emoji(weather_pm)} {weather_pm} (☔{rain_pm}%)",
        ]
    else:
        weather_day = land_items.get(f"wf{field_index}")
        rain_day = land_items.get(f"rnSt{field_index}")
        if weather_day is None:
            return None
        representative_weather = weather_day
        lines = [f"[종일] {get_mid_emoji(weather_day)} {weather_day} (☔{rain_day}%)"]

    lines.append(f"\n최종 업데이트: {update_ts} (KST)")

    event = Event()
    event.add(
        "summary",
        f"{get_mid_emoji(representative_weather)} {temp_min}°C/{temp_max}°C",
    )
    event.add("location", LOCATION_NAME)
    event.add("description", "\n".join(lines))
    event.add("dtstart", target_date)
    event.add("dtend", target_date + timedelta(days=1))
    event.add("uid", f"{target_date.strftime('%Y%m%d')}@mid")
    return event


def main():
    if not API_KEY:
        print("::error::KMA_API_KEY GitHub Secret이 설정되어 있지 않습니다.")
        return 2

    now = datetime.now(SEOUL_TZ)
    today = now.date()
    update_ts = now.strftime("%Y-%m-%d %H:%M:%S")

    calendar = Calendar()
    calendar.add("prodid", "-//Adamkk111//KMA Weather Calendar//KO")
    calendar.add("version", "2.0")
    calendar.add("X-WR-CALNAME", "기상청 날씨")
    calendar.add("X-WR-TIMEZONE", "Asia/Seoul")

    cached_events = load_cached_events("weather.ics")
    processed_dates = set()
    used_cache_dates = []

    print(f"[START] {update_ts} KST")
    print(f"[CONFIG] nx={NX}, ny={NY}, temp={REG_ID_TEMP}, land={REG_ID_LAND}")

    # --- 단기예보 D+0 ~ D+3 ---
    base_date, base_time = get_short_base_datetime(now)
    print(f"[SHORT] base_date={base_date} base_time={base_time}")
    short_response = fetch_api(
        "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst",
        {
            "dataType": "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": NX,
            "ny": NY,
            "numOfRows": 1000,
            "authKey": API_KEY,
        },
    )
    forecast_map = parse_short_forecast(short_response)

    for delta in range(4):
        target_date = today + timedelta(days=delta)
        date_str = target_date.strftime("%Y%m%d")
        event = make_short_event(target_date, forecast_map.get(date_str, {}), now, update_ts)

        if event is not None:
            calendar.add_component(event)
            processed_dates.add(date_str)
        elif add_cached_event(calendar, cached_events, date_str, processed_dates):
            used_cache_dates.append(date_str)
            print(f"[SHORT CACHE] {date_str}")
        else:
            print(f"::error::단기예보 {date_str}의 새 데이터와 정상 캐시가 모두 없습니다.")

    # --- 중기예보 D+4 ~ D+10 ---
    temp_items = None
    land_items = None
    used_tmfc = None

    for candidate in get_mid_tmfc_candidates(now):
        tmfc = candidate.strftime("%Y%m%d%H%M")
        print(f"[MID] tmFc={tmfc} 시도")

        temp_response = fetch_api(
            "https://apihub.kma.go.kr/api/typ02/openApi/MidFcstInfoService/getMidTa",
            {
                "dataType": "JSON",
                "regId": REG_ID_TEMP,
                "tmFc": tmfc,
                "authKey": API_KEY,
            },
        )
        if not temp_response:
            continue

        land_response = fetch_api(
            "https://apihub.kma.go.kr/api/typ02/openApi/MidFcstInfoService/getMidLandFcst",
            {
                "dataType": "JSON",
                "regId": REG_ID_LAND,
                "tmFc": tmfc,
                "authKey": API_KEY,
            },
        )
        if not land_response:
            continue

        try:
            temp_items = temp_response["response"]["body"]["items"]["item"][0]
            land_items = land_response["response"]["body"]["items"]["item"][0]
            used_tmfc = candidate
            break
        except (KeyError, IndexError, TypeError) as exc:
            print(f"[MID PARSE FAIL] {type(exc).__name__}: {exc}")
            temp_items = None
            land_items = None
            used_tmfc = None

    for delta in range(4, 11):
        target_date = today + timedelta(days=delta)
        date_str = target_date.strftime("%Y%m%d")
        event = None

        if temp_items and land_items and used_tmfc:
            event = make_mid_event(
                target_date,
                used_tmfc.date(),
                temp_items,
                land_items,
                update_ts,
            )

        if event is not None:
            calendar.add_component(event)
            processed_dates.add(date_str)
        elif add_cached_event(calendar, cached_events, date_str, processed_dates):
            used_cache_dates.append(date_str)
            print(f"[MID CACHE] {date_str}")
        else:
            print(f"::error::중기예보 {date_str}의 새 데이터와 정상 캐시가 모두 없습니다.")

    expected_dates = {
        (today + timedelta(days=delta)).strftime("%Y%m%d") for delta in range(11)
    }
    missing_dates = sorted(expected_dates - processed_dates)
    if missing_dates:
        print(f"::error::날씨 이벤트가 없는 날짜: {', '.join(missing_dates)}")
        print("[ABORT] 불완전한 weather.ics로 기존 파일을 덮어쓰지 않습니다.")
        return 1

    output = calendar.to_ical()
    if b"None" in output:
        print("::error::생성 결과에서 None 값이 발견되어 저장을 중단합니다.")
        return 1

    with open("weather.ics", "wb") as file:
        file.write(output)

    print(f"[DONE] {len(processed_dates)}일치 예보 생성 완료")
    if used_cache_dates:
        print(f"[CACHE USED] {', '.join(sorted(used_cache_dates))}")
    else:
        print("[CACHE USED] 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
